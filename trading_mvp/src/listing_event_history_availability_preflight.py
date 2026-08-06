from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from listing_event_history_collect_plan import (
    DEFAULT_GRANULARITIES,
    INTERVAL_SECONDS,
    event_to_plan_row,
    load_history_events,
    load_previous_quality_report,
    summarize_previous_quality,
)
from listing_event_history_collector import CLIENTS, fetch_window


DEFAULT_ANALYSIS_DIR = Path("exports/trading-mvp/analysis")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(path: str | Path, *, repo_root: Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return repo_root / value


def build_availability_event_plan(preview: dict[str, Any], *, repo_root: Path) -> list[dict[str, Any]]:
    calendar_path = resolve_path(preview["calendar_path"], repo_root=repo_root)
    budget = preview.get("request_budget") or {}
    events = load_history_events(calendar_path, quote="USDT")
    pre_window_sec = int(budget.get("pre_window_sec") or 3600)
    post_window_sec = int(budget.get("post_window_sec") or 259200)
    return [
        event_to_plan_row(event, pre_window_sec=pre_window_sec, post_window_sec=post_window_sec)
        for event in events
    ]


def _is_active_event(event: dict[str, Any]) -> bool:
    status = str(event.get("survivorship_status") or "").strip().lower()
    is_delisted = bool(event.get("is_delisted"))
    return (not is_delisted) and status in {"current_active_snapshot", "active", ""}


def select_probe_events(events: list[dict[str, Any]], *, max_events_per_exchange: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    ordered = sorted(
        events,
        key=lambda item: (
            str(item.get("exchange")),
            0 if _is_active_event(item) else 1,
            -float(item.get("event_ts") or 0),
            str(item.get("symbol")),
        ),
    )
    for event in ordered:
        exchange = str(event.get("exchange") or "")
        event_id = str(event.get("event_id") or "")
        if not exchange or not event_id or event_id in seen:
            continue
        if counts[exchange] >= max_events_per_exchange:
            continue
        selected.append(event)
        counts[exchange] += 1
        seen.add(event_id)
    return selected


def make_probe_event(event: dict[str, Any], *, probe_window_sec: int) -> dict[str, Any]:
    event_ts = float(event.get("event_ts") or event.get("window_start_ts") or 0)
    start_ts = event_ts
    end_ts = event_ts + max(60, int(probe_window_sec))
    return {
        **event,
        "full_window_start_ts": event.get("window_start_ts"),
        "full_window_end_ts": event.get("window_end_ts"),
        "window_start_ts": start_ts,
        "window_end_ts": end_ts,
    }


def planned_probe_row(event: dict[str, Any], granularity: str) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "exchange": event.get("exchange"),
        "symbol": event.get("symbol"),
        "base": event.get("base"),
        "quote": event.get("quote"),
        "event_ts": event.get("event_ts"),
        "event_iso": event.get("event_iso"),
        "granularity": granularity,
        "window_start_ts": event.get("window_start_ts"),
        "window_end_ts": event.get("window_end_ts"),
        "full_window_start_ts": event.get("full_window_start_ts"),
        "full_window_end_ts": event.get("full_window_end_ts"),
    }


def probe_availability(
    events: list[dict[str, Any]],
    *,
    granularities: tuple[str, ...],
    candles_per_request: int,
    timeout_sec: int,
    max_retries: int,
    sleep_sec: float,
    probe_window_sec: int,
) -> list[dict[str, Any]]:
    clients = {exchange: client_cls(timeout_sec=timeout_sec, max_retries=max_retries) for exchange, client_cls in CLIENTS.items()}
    rows: list[dict[str, Any]] = []
    for event in events:
        probe_event = make_probe_event(event, probe_window_sec=probe_window_sec)
        exchange = str(event.get("exchange") or "")
        client = clients.get(exchange)
        for granularity in granularities:
            row = planned_probe_row(probe_event, granularity)
            if client is None:
                rows.append({**row, "probe_status": "unsupported_exchange", "rows": 0, "error": f"unsupported exchange: {exchange}"})
                continue
            try:
                candles, requests_made = fetch_window(
                    client=client,
                    event=probe_event,
                    granularity=granularity,
                    candles_per_request=candles_per_request,
                    sleep_sec=sleep_sec,
                )
                rows.append(
                    {
                        **row,
                        "probe_status": "ok" if candles else "no_data_or_delisted",
                        "rows": len(candles),
                        "requests": requests_made,
                        "first_candle_ts": candles[0].ts if candles else None,
                        "last_candle_ts": candles[-1].ts if candles else None,
                        "error": "",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - preserve endpoint failures as explicit evidence.
                rows.append(
                    {
                        **row,
                        "probe_status": "api_error",
                        "rows": 0,
                        "requests": 0,
                        "first_candle_ts": None,
                        "last_candle_ts": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return rows


def summarize_probe_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("probe_status") or "") for row in rows)
    ok_events_by_exchange: dict[str, set[str]] = {}
    ok_rows_by_exchange: Counter[str] = Counter()
    error_rows_by_exchange: Counter[str] = Counter()
    for row in rows:
        exchange = str(row.get("exchange") or "")
        status = str(row.get("probe_status") or "")
        if status == "ok":
            ok_events_by_exchange.setdefault(exchange, set()).add(str(row.get("event_id") or ""))
            ok_rows_by_exchange[exchange] += int(row.get("rows") or 0)
        elif status == "api_error":
            error_rows_by_exchange[exchange] += 1
    ok_event_counts = {exchange: len(events) for exchange, events in ok_events_by_exchange.items()}
    ok_events_total = sum(ok_event_counts.values())
    max_single_exchange_fraction = max((count / ok_events_total for count in ok_event_counts.values()), default=0.0)
    total_slots = len(rows)
    api_error_slots = int(status_counts.get("api_error") or 0)
    return {
        "slots": total_slots,
        "status_counts": dict(status_counts),
        "ok_exchanges": len([exchange for exchange, count in ok_event_counts.items() if count > 0]),
        "ok_events": ok_events_total,
        "ok_events_by_exchange": ok_event_counts,
        "ok_rows_by_exchange": dict(ok_rows_by_exchange),
        "error_rows_by_exchange": dict(error_rows_by_exchange),
        "api_error_slot_rate": api_error_slots / total_slots if total_slots else 0.0,
        "max_single_exchange_ok_event_fraction": max_single_exchange_fraction,
    }


def decide_from_summary(summary: dict[str, Any], *, probe: bool) -> str:
    if not probe:
        return "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE"
    accepted = (
        int(summary.get("ok_exchanges") or 0) >= 2
        and int(summary.get("ok_events") or 0) >= 2
        and float(summary.get("api_error_slot_rate") or 0.0) <= 0.50
        and float(summary.get("max_single_exchange_ok_event_fraction") or 1.0) <= 0.70
    )
    if accepted:
        return "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET"
    return "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_RESAMPLE_OR_GATE_FIX"


def build_availability_preflight(
    *,
    preview_path: Path,
    output_path: Path | None,
    repo_root: Path,
    previous_quality_report_path: Path | None = None,
    max_events_per_exchange: int = 8,
    granularities: tuple[str, ...] = ("5m",),
    probe: bool = False,
    candles_per_request: int = 100,
    timeout_sec: int = 10,
    max_retries: int = 1,
    sleep_sec: float = 0.0,
    probe_window_sec: int = 3600,
) -> dict[str, Any]:
    preview = read_json(preview_path)
    all_events = build_availability_event_plan(preview, repo_root=repo_root)
    probe_events = select_probe_events(all_events, max_events_per_exchange=max_events_per_exchange)
    previous_quality = summarize_previous_quality(
        load_previous_quality_report(previous_quality_report_path) if previous_quality_report_path else None
    )
    planned_rows = [
        planned_probe_row(make_probe_event(event, probe_window_sec=probe_window_sec), granularity)
        for event in probe_events
        for granularity in granularities
    ]
    probe_rows = (
        probe_availability(
            probe_events,
            granularities=granularities,
            candles_per_request=candles_per_request,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
            sleep_sec=sleep_sec,
            probe_window_sec=probe_window_sec,
        )
        if probe
        else []
    )
    summary = summarize_probe_rows(probe_rows) if probe else {
        "slots": len(planned_rows),
        "status_counts": {},
        "ok_exchanges": 0,
        "ok_events": 0,
        "ok_events_by_exchange": {},
        "ok_rows_by_exchange": {},
        "error_rows_by_exchange": {},
        "api_error_slot_rate": None,
        "max_single_exchange_ok_event_fraction": None,
    }
    decision = decide_from_summary(summary, probe=probe)
    result: dict[str, Any] = {
        "mode": "listing_event_history_availability_preflight",
        "generated_at": utc_now_iso(),
        "decision": decision,
        "would_start_collect": False,
        "would_run_public_probe": bool(probe),
        "research_only": True,
        "public_data_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "actual_collect_requires_explicit_user_approval": True,
        "public_probe_requires_explicit_user_approval": True,
        "preview_path": str(preview_path),
        "previous_quality_report_path": str(previous_quality_report_path) if previous_quality_report_path else "",
        "previous_quality_gate": previous_quality,
        "probe_contract": {
            "max_events_per_exchange": max_events_per_exchange,
            "granularities": list(granularities),
            "candles_per_request": candles_per_request,
            "timeout_sec": timeout_sec,
            "max_retries": max_retries,
            "probe_window_sec": probe_window_sec,
            "planned_slots": len(planned_rows),
            "planned_events": len(probe_events),
            "planned_exchanges": dict(Counter(str(event.get("exchange") or "") for event in probe_events)),
            "acceptance": {
                "min_ok_exchanges": 2,
                "min_ok_events": 2,
                "max_api_error_slot_rate": 0.50,
                "max_single_exchange_ok_event_fraction": 0.70,
            },
        },
        "planned_probe_rows": planned_rows,
        "probe_rows": probe_rows,
        "summary": summary,
        "blocked_actions": [
            "actual_ohlcv_collect",
            "replay",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "hidden_background_long_run",
        ],
        "next_valid_moves": (
            [
                "Run the public REST availability probe visibly with explicit confirmation.",
                "If accepted, build a revised collect approval packet; do not start actual collect automatically.",
            ]
            if not probe
            else [
                "Build revised listing-event history collect approval packet with two-venue coverage evidence.",
                "Keep replay/grid/paper-forward blocked until a new collect passes data-quality and normalizer gates.",
            ]
            if decision == "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET"
            else [
                "Resample/expand event selection or fix Gate endpoint mapping before any actual collect.",
                "Do not repeat MEXC-only history collection.",
            ]
        ),
        "output_path": str(output_path) if output_path else "",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return DEFAULT_ANALYSIS_DIR / f"listing_event_history_availability_preflight_{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PlanOnly/public-probe availability preflight for listing-event OHLCV history.")
    parser.add_argument("--preview", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--previous-quality-report", default="")
    parser.add_argument("--max-events-per-exchange", type=int, default=8)
    parser.add_argument("--granularities", default="5m")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--candles-per-request", type=int, default=100)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--sleep-sec", type=float, default=0.0)
    parser.add_argument("--probe-window-sec", type=int, default=3600)
    args = parser.parse_args(argv)
    granularities = tuple(part.strip() for part in args.granularities.split(",") if part.strip())
    unknown = [granularity for granularity in granularities if granularity not in INTERVAL_SECONDS]
    if unknown:
        raise SystemExit(f"unsupported granularities: {', '.join(unknown)}")
    result = build_availability_preflight(
        preview_path=Path(args.preview),
        output_path=Path(args.output) if args.output else default_output_path(),
        repo_root=Path(args.repo_root),
        previous_quality_report_path=Path(args.previous_quality_report) if args.previous_quality_report else None,
        max_events_per_exchange=args.max_events_per_exchange,
        granularities=granularities,
        probe=bool(args.probe),
        candles_per_request=args.candles_per_request,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        sleep_sec=args.sleep_sec,
        probe_window_sec=args.probe_window_sec,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
