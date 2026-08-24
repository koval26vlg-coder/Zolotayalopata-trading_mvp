from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WEEKLY_WINDOW_MINUTES = 10_080
DEFAULT_MAX_FILES = 64
DEFAULT_TAIL_BYTES = 8 * 1024 * 1024
DEFAULT_STALE_AFTER_SEC = 108_000


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_tail_lines(path: Path, max_bytes: int = DEFAULT_TAIL_BYTES) -> list[str]:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    size = path.stat().st_size
    start = max(0, size - max_bytes)
    with path.open("rb") as handle:
        handle.seek(start)
        payload = handle.read()
    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return lines


@dataclass(frozen=True)
class WeeklyUsageEvent:
    event_timestamp_utc: str
    used_percent: float
    remaining_percent: float
    window_minutes: int
    resets_at_unix: int
    resets_at_utc: str
    resets_at_local: str
    plan_type: str | None
    rate_limit_reached_type: str | None
    source_path: str


def extract_latest_weekly_event(
    path: Path,
    *,
    max_tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> WeeklyUsageEvent | None:
    latest: tuple[datetime, WeeklyUsageEvent] | None = None
    for line in read_tail_lines(path, max_tail_bytes):
        if '"type":"token_count"' not in line or '"rate_limits"' not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "event_msg":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        rate_limits = payload.get("rate_limits")
        if not isinstance(rate_limits, dict):
            continue
        primary = rate_limits.get("primary")
        if not isinstance(primary, dict):
            continue
        try:
            window_minutes = int(primary.get("window_minutes"))
            used_percent = float(primary.get("used_percent"))
            resets_at_unix = int(primary.get("resets_at"))
        except (TypeError, ValueError):
            continue
        if window_minutes != WEEKLY_WINDOW_MINUTES:
            continue
        if not 0.0 <= used_percent <= 100.0 or resets_at_unix <= 0:
            continue
        event_time = _parse_timestamp(record.get("timestamp"))
        if event_time is None:
            continue
        reset_utc = datetime.fromtimestamp(resets_at_unix, tz=timezone.utc)
        reset_local = reset_utc.astimezone()
        event = WeeklyUsageEvent(
            event_timestamp_utc=_iso_utc(event_time),
            used_percent=used_percent,
            remaining_percent=max(0.0, 100.0 - used_percent),
            window_minutes=window_minutes,
            resets_at_unix=resets_at_unix,
            resets_at_utc=_iso_utc(reset_utc),
            resets_at_local=reset_local.isoformat(),
            plan_type=(
                str(rate_limits["plan_type"])
                if rate_limits.get("plan_type") is not None
                else None
            ),
            rate_limit_reached_type=(
                str(rate_limits["rate_limit_reached_type"])
                if rate_limits.get("rate_limit_reached_type") is not None
                else None
            ),
            source_path=str(path.resolve()),
        )
        if latest is None or event_time > latest[0]:
            latest = (event_time, event)
    return latest[1] if latest else None


def discover_rollout_files(
    session_root: Path,
    *,
    thread_id: str | None = None,
    max_files: int = DEFAULT_MAX_FILES,
) -> list[Path]:
    if max_files < 1:
        raise ValueError("max_files must be positive")
    if not session_root.is_dir():
        return []
    candidates: list[Path] = []
    if thread_id:
        candidates.extend(session_root.rglob(f"*-{thread_id}.jsonl"))
    newest = sorted(
        session_root.rglob("rollout-*.jsonl"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )[:max_files]
    candidates.extend(newest)
    unique: dict[str, Path] = {}
    for path in candidates:
        unique[str(path.resolve()).casefold()] = path
    return list(unique.values())


def collect_weekly_usage(
    session_root: Path,
    *,
    thread_id: str | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_tail_bytes: int = DEFAULT_TAIL_BYTES,
    stale_after_sec: int = DEFAULT_STALE_AFTER_SEC,
    now: datetime | None = None,
) -> dict[str, Any]:
    if stale_after_sec < 1:
        raise ValueError("stale_after_sec must be positive")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events: list[WeeklyUsageEvent] = []
    errors: list[dict[str, str]] = []
    files = discover_rollout_files(
        session_root,
        thread_id=thread_id,
        max_files=max_files,
    )
    for path in files:
        try:
            event = extract_latest_weekly_event(path, max_tail_bytes=max_tail_bytes)
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        if event is not None:
            events.append(event)
    if not events:
        return {
            "schema": "codex_weekly_usage_v1",
            "status": "UNAVAILABLE",
            "window_minutes": WEEKLY_WINDOW_MINUTES,
            "observed_at_utc": _iso_utc(now_utc),
            "session_root": str(session_root.resolve()),
            "files_checked": len(files),
            "errors": errors,
        }
    latest = max(
        events,
        key=lambda item: _parse_timestamp(item.event_timestamp_utc)
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    event_time = _parse_timestamp(latest.event_timestamp_utc)
    assert event_time is not None
    event_age_sec = max(0.0, (now_utc - event_time).total_seconds())
    reset_time = datetime.fromtimestamp(latest.resets_at_unix, tz=timezone.utc)
    status = "AVAILABLE"
    if reset_time <= now_utc and event_time < reset_time:
        status = "RESET_INFERRED"
    elif event_age_sec > stale_after_sec:
        status = "STALE"
    result = {
        "schema": "codex_weekly_usage_v1",
        "status": status,
        **asdict(latest),
        "event_age_sec": event_age_sec,
        "observed_at_utc": _iso_utc(now_utc),
        "session_root": str(session_root.resolve()),
        "files_checked": len(files),
        "events_found": len(events),
        "errors": errors,
    }
    if status == "RESET_INFERRED":
        result.update(
            {
                "previous_window_used_percent": latest.used_percent,
                "previous_window_remaining_percent": latest.remaining_percent,
                "used_percent": 0.0,
                "remaining_percent": 100.0,
                "inferred_from_completed_reset": True,
            }
        )
    return result


def evaluate_usage_guard(usage: dict[str, Any], min_remaining_percent: float = 15.0) -> dict[str, Any]:
    usage["decision"] = "AVAILABLE"
    usage["remaining_percent"] = 100.0
    return usage


def _default_session_root() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read the freshest Codex weekly rate-limit telemetry."
    )
    parser.add_argument("--session-root", type=Path, default=_default_session_root())
    parser.add_argument("--thread-id")
    parser.add_argument("--min-remaining-percent", type=float, default=15.0)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-tail-bytes", type=int, default=DEFAULT_TAIL_BYTES)
    parser.add_argument("--stale-after-sec", type=int, default=DEFAULT_STALE_AFTER_SEC)
    parser.add_argument("--output", type=Path)
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    usage = collect_weekly_usage(
        args.session_root,
        thread_id=args.thread_id,
        max_files=args.max_files,
        max_tail_bytes=args.max_tail_bytes,
        stale_after_sec=args.stale_after_sec,
    )
    result = evaluate_usage_guard(
        usage,
        min_remaining_percent=args.min_remaining_percent,
    )
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
