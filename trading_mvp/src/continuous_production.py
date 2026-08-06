from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


POLICY_SCHEMA = "trading_mvp_continuous_production_policy_v1"


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _parse_clock(value: Any, *, label: str) -> time:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"{label} must use HH:MM") from exc


def _combine(day: date, clock: time, tz: timezone) -> datetime:
    return datetime.combine(day, clock, tzinfo=tz)


def _previous_weekday(day: date, target_weekday: int) -> date:
    return day - timedelta(days=(day.weekday() - target_weekday) % 7)


def _next_weekday(day: date, target_weekday: int) -> date:
    delta = (target_weekday - day.weekday()) % 7
    return day + timedelta(days=delta or 7)


def _window_payload(
    *,
    now_local: datetime,
    window_type: str,
    opens_at: datetime,
    hard_deadline: datetime,
    approval_lead: timedelta,
) -> dict[str, Any]:
    remaining_sec = max(
        0,
        int((hard_deadline - now_local).total_seconds()),
    )
    return {
        "status": "OPEN",
        "window_type": window_type,
        "window_id": (
            f"{window_type}_{opens_at.date().isoformat()}_"
            f"{hard_deadline.date().isoformat()}"
        ),
        "observed_at_local": now_local.isoformat(),
        "opens_at_local": opens_at.isoformat(),
        "hard_deadline_local": hard_deadline.isoformat(),
        "approval_request_at_local": (
            opens_at - approval_lead
        ).isoformat(),
        "approval_request_status": "DUE",
        "new_campaign_start_allowed_now": remaining_sec > 0,
        "max_remaining_runtime_sec": remaining_sec,
    }


def resolve_run_window(
    policy: dict[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    if policy.get("schema") != POLICY_SCHEMA:
        raise ValueError(f"expected policy schema {POLICY_SCHEMA}")

    schedule = policy.get("run_windows")
    if not isinstance(schedule, dict):
        raise ValueError("run_windows must be an object")

    timezone_name = str(schedule.get("timezone") or "")
    if timezone_name != "Europe/Volgograd":
        raise ValueError("run_windows.timezone must be Europe/Volgograd")
    offset_minutes = int(schedule.get("utc_offset_minutes") or 0)
    if offset_minutes != 180:
        raise ValueError("run_windows.utc_offset_minutes must be 180")

    start_clock = _parse_clock(
        schedule.get("new_campaign_start_local"),
        label="run_windows.new_campaign_start_local",
    )
    stop_clock = _parse_clock(
        schedule.get("weekday_hard_stop_local"),
        label="run_windows.weekday_hard_stop_local",
    )
    if start_clock != time(19, 0) or stop_clock != time(8, 0):
        raise ValueError("run window must remain 19:00 through 08:00")

    weekend = schedule.get("weekend")
    if not isinstance(weekend, dict):
        raise ValueError("run_windows.weekend must be an object")
    if (
        str(weekend.get("opens") or "") != "FRIDAY 19:00"
        or str(weekend.get("hard_stop") or "") != "MONDAY 08:00"
    ):
        raise ValueError(
            "weekend envelope must remain FRIDAY 19:00 through MONDAY 08:00"
        )

    approval = policy.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("approval must be an object")
    lead_minutes = int(approval.get("request_lead_minutes") or 0)
    if not 0 <= lead_minutes <= 720:
        raise ValueError("approval.request_lead_minutes must be in [0, 720]")
    approval_lead = timedelta(minutes=lead_minutes)

    local_tz = timezone(timedelta(minutes=offset_minutes), name=timezone_name)
    observed = _parse_timestamp(
        observed_at_utc,
        label="observed_at_utc",
    )
    now_local = observed.astimezone(local_tz)
    local_clock = now_local.time().replace(tzinfo=None)
    weekday = now_local.weekday()

    # Friday evening through Monday morning is one continuous weekend envelope.
    if (
        (weekday == 4 and local_clock >= start_clock)
        or weekday in {5, 6}
        or (weekday == 0 and local_clock < stop_clock)
    ):
        friday = _previous_weekday(now_local.date(), 4)
        if weekday == 0:
            friday -= timedelta(days=7)
        opens_at = _combine(friday, start_clock, local_tz)
        hard_deadline = _combine(
            friday + timedelta(days=3),
            stop_clock,
            local_tz,
        )
        return _window_payload(
            now_local=now_local,
            window_type="WEEKEND",
            opens_at=opens_at,
            hard_deadline=hard_deadline,
            approval_lead=approval_lead,
        )

    # Monday-Thursday evening and Tuesday-Friday early morning are weeknights.
    if weekday in {0, 1, 2, 3} and local_clock >= start_clock:
        opens_at = _combine(now_local.date(), start_clock, local_tz)
        hard_deadline = _combine(
            now_local.date() + timedelta(days=1),
            stop_clock,
            local_tz,
        )
        return _window_payload(
            now_local=now_local,
            window_type="WEEKNIGHT",
            opens_at=opens_at,
            hard_deadline=hard_deadline,
            approval_lead=approval_lead,
        )
    if weekday in {1, 2, 3, 4} and local_clock < stop_clock:
        opens_at = _combine(
            now_local.date() - timedelta(days=1),
            start_clock,
            local_tz,
        )
        hard_deadline = _combine(
            now_local.date(),
            stop_clock,
            local_tz,
        )
        return _window_payload(
            now_local=now_local,
            window_type="WEEKNIGHT",
            opens_at=opens_at,
            hard_deadline=hard_deadline,
            approval_lead=approval_lead,
        )

    next_open_date = now_local.date()
    if weekday in {5, 6}:
        next_open_date = _next_weekday(now_local.date(), 4)
    next_open = _combine(next_open_date, start_clock, local_tz)
    if next_open <= now_local:
        next_open += timedelta(days=1)
    next_type = "WEEKEND" if next_open.weekday() == 4 else "WEEKNIGHT"
    approval_at = next_open - approval_lead
    return {
        "status": "CLOSED",
        "window_type": None,
        "window_id": None,
        "observed_at_local": now_local.isoformat(),
        "opens_at_local": None,
        "hard_deadline_local": None,
        "approval_request_at_local": approval_at.isoformat(),
        "approval_request_status": (
            "DUE" if now_local >= approval_at else "NOT_DUE"
        ),
        "new_campaign_start_allowed_now": False,
        "max_remaining_runtime_sec": 0,
        "next_window_type": next_type,
        "next_opens_at_local": next_open.isoformat(),
    }


def validate_runtime_request(
    policy: dict[str, Any],
    *,
    requested_start_local: str,
    expected_duration_sec: int,
    max_runtime_sec: int,
) -> dict[str, Any]:
    start = _parse_timestamp(
        requested_start_local,
        label="requested_start_local",
    )
    expected = int(expected_duration_sec)
    maximum = int(max_runtime_sec)
    if expected <= 0:
        raise ValueError("expected_duration_sec must be positive")
    if maximum < expected:
        raise ValueError("max_runtime_sec must be >= expected_duration_sec")

    runtime = policy.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be an object")
    short_limit = int(runtime.get("short_offline_task_max_runtime_sec") or 0)
    if short_limit <= 0:
        raise ValueError(
            "runtime.short_offline_task_max_runtime_sec must be positive"
        )

    window = resolve_run_window(
        policy,
        observed_at_utc=start.astimezone(timezone.utc).isoformat(),
    )
    if window["status"] != "OPEN":
        raise ValueError("requested start is outside an open run window")
    hard_deadline = _parse_timestamp(
        window["hard_deadline_local"],
        label="hard_deadline_local",
    )
    requested_end = start + timedelta(seconds=maximum)
    if requested_end > hard_deadline:
        raise ValueError(
            "requested max runtime exceeds the rolling window hard deadline"
        )
    return {
        "classification": (
            "LONG_CAMPAIGN" if maximum > short_limit else "BOUNDED_TASK"
        ),
        "requested_start_local": start.isoformat(),
        "expected_duration_sec": expected,
        "max_runtime_sec": maximum,
        "requested_max_end_local": requested_end.isoformat(),
        "hard_deadline_local": hard_deadline.isoformat(),
        "window_id": window["window_id"],
        "window_type": window["window_type"],
    }


def _load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate trading_mvp rolling run windows."
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--observed-at-utc")
    parser.add_argument("--requested-start-local")
    parser.add_argument("--expected-duration-sec", type=int)
    parser.add_argument("--max-runtime-sec", type=int)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = _load_policy(args.policy.expanduser().resolve())
    if args.requested_start_local:
        if args.expected_duration_sec is None or args.max_runtime_sec is None:
            raise ValueError(
                "runtime validation requires expected and max duration"
            )
        result = validate_runtime_request(
            policy,
            requested_start_local=args.requested_start_local,
            expected_duration_sec=args.expected_duration_sec,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        observed_at = args.observed_at_utc or datetime.now(
            timezone.utc
        ).isoformat()
        result = resolve_run_window(
            policy,
            observed_at_utc=observed_at,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
