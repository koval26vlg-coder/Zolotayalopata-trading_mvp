from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ListingEventHistoryQualityConfig:
    min_ok_rows: int = 1000
    min_ok_events: int = 30
    min_ok_bases: int = 20
    min_ok_exchanges: int = 2
    min_ok_event_granularity_slots: int = 30
    min_ok_event_fraction: float = 0.25
    min_ok_slot_fraction: float = 0.20
    max_api_error_slot_rate: float = 0.50
    max_single_exchange_ok_event_fraction: float = 0.70
    require_manifest_final: bool = True
    require_completed_requests: bool = True
    require_line_count_match_manifest: bool = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "data_status": "parse_error",
                        "event_id": f"parse_error:{line_no}",
                        "exchange": "",
                        "base": "",
                        "granularity": "",
                        "error": str(exc),
                    }
                )
                continue
            rows.append(row)
    return rows


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _counter_to_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


def evaluate_listing_event_history_quality(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    config: ListingEventHistoryQualityConfig | None = None,
) -> dict[str, Any]:
    cfg = config or ListingEventHistoryQualityConfig()

    status_counts: Counter[str] = Counter()
    rows_by_exchange: Counter[str] = Counter()
    ok_rows_by_exchange: Counter[str] = Counter()
    rows_by_granularity: Counter[str] = Counter()
    ok_rows_by_granularity: Counter[str] = Counter()
    ok_rows_by_event: Counter[str] = Counter()
    error_rows_by_exchange: Counter[str] = Counter()
    placeholder_rows_by_exchange: Counter[str] = Counter()

    events: set[str] = set()
    event_bases: set[tuple[str, str]] = set()
    event_exchanges: set[str] = set()
    slots: set[tuple[str, str]] = set()
    ok_events: set[str] = set()
    ok_bases: set[tuple[str, str]] = set()
    ok_exchanges: set[str] = set()
    ok_slots: set[tuple[str, str]] = set()
    error_slots: set[tuple[str, str]] = set()

    for row in rows:
        status = str(row.get("data_status") or "unknown")
        exchange = str(row.get("exchange") or "")
        event_id = str(row.get("event_id") or "")
        base = str(row.get("base") or "")
        granularity = str(row.get("granularity") or "")
        status_counts[status] += 1
        if exchange:
            rows_by_exchange[exchange] += 1
        if granularity:
            rows_by_granularity[granularity] += 1
        if event_id:
            events.add(event_id)
        if event_id and granularity:
            slots.add((event_id, granularity))
        if exchange and base:
            event_bases.add((exchange, base))
        if exchange:
            event_exchanges.add(exchange)

        if status == "ok":
            ok_events.add(event_id)
            ok_exchanges.add(exchange)
            ok_bases.add((exchange, base))
            ok_slots.add((event_id, granularity))
            ok_rows_by_exchange[exchange] += 1
            ok_rows_by_granularity[granularity] += 1
            ok_rows_by_event[event_id] += 1
        elif status == "api_error":
            error_rows_by_exchange[exchange] += 1
            if event_id and granularity:
                error_slots.add((event_id, granularity))
        else:
            placeholder_rows_by_exchange[exchange] += 1

    selected_events = int(manifest.get("selected_events") or len(events))
    planned_requests = int(manifest.get("planned_event_granularity_requests") or len(slots))
    completed_requests = int(manifest.get("completed_event_granularity_requests") or 0)
    manifest_ohlcv_rows = int(manifest.get("ohlcv_rows") or 0)
    manifest_placeholder_rows = int(manifest.get("placeholder_rows") or 0)
    manifest_errors = int(manifest.get("errors") or 0)
    expected_line_count = manifest_ohlcv_rows + manifest_placeholder_rows
    line_count = len(rows)
    ok_rows = int(status_counts.get("ok", 0))
    api_error_rows = int(status_counts.get("api_error", 0))

    ok_event_count = len(ok_events)
    ok_base_count = len(ok_bases)
    ok_exchange_count = len({exchange for exchange in ok_exchanges if exchange})
    ok_slot_count = len(ok_slots)
    observed_slot_count = len(slots)
    api_error_slot_count = len(error_slots) if error_slots else api_error_rows
    ok_event_fraction = _safe_div(ok_event_count, selected_events)
    ok_slot_fraction = _safe_div(ok_slot_count, planned_requests)
    api_error_slot_rate = _safe_div(api_error_slot_count, planned_requests)
    max_exchange_ok_events = 0
    ok_events_by_exchange: Counter[str] = Counter()
    for event_id in ok_events:
        matching = next((row for row in rows if row.get("event_id") == event_id and row.get("data_status") == "ok"), {})
        ok_events_by_exchange[str(matching.get("exchange") or "")] += 1
    if ok_events_by_exchange:
        max_exchange_ok_events = max(ok_events_by_exchange.values())
    max_single_exchange_ok_event_fraction = _safe_div(max_exchange_ok_events, ok_event_count)

    reasons: list[str] = []
    if cfg.require_manifest_final and manifest.get("final") is not True:
        reasons.append("manifest_not_final")
    if cfg.require_completed_requests and completed_requests < planned_requests:
        reasons.append("incomplete_event_granularity_requests")
    if cfg.require_line_count_match_manifest and line_count != expected_line_count:
        reasons.append("line_count_mismatch_manifest")
    if ok_rows < cfg.min_ok_rows:
        reasons.append("min_ok_rows")
    if ok_event_count < cfg.min_ok_events:
        reasons.append("min_ok_events")
    if ok_base_count < cfg.min_ok_bases:
        reasons.append("min_ok_bases")
    if ok_exchange_count < cfg.min_ok_exchanges:
        reasons.append("min_ok_exchanges")
    if ok_slot_count < cfg.min_ok_event_granularity_slots:
        reasons.append("min_ok_event_granularity_slots")
    if ok_event_fraction < cfg.min_ok_event_fraction:
        reasons.append("min_ok_event_fraction")
    if ok_slot_fraction < cfg.min_ok_slot_fraction:
        reasons.append("min_ok_slot_fraction")
    if api_error_slot_rate > cfg.max_api_error_slot_rate:
        reasons.append("max_api_error_slot_rate")
    if max_single_exchange_ok_event_fraction > cfg.max_single_exchange_ok_event_fraction:
        reasons.append("max_single_exchange_ok_event_fraction")

    accepted = not reasons
    decision = (
        "LISTING_EVENT_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_NORMALIZER"
        if accepted
        else "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN"
    )

    return {
        "mode": "listing_event_history_data_quality",
        "generated_at": utc_now_iso(),
        "decision": decision,
        "accepted": accepted,
        "replay_allowed": False,
        "normalizer_allowed": accepted,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "reasons": reasons,
        "config": asdict(cfg),
        "metrics": {
            "selected_events": selected_events,
            "planned_event_granularity_requests": planned_requests,
            "completed_event_granularity_requests": completed_requests,
            "line_count": line_count,
            "expected_line_count_from_manifest": expected_line_count,
            "line_count_matches_manifest": line_count == expected_line_count,
            "manifest_ohlcv_rows": manifest_ohlcv_rows,
            "manifest_placeholder_rows": manifest_placeholder_rows,
            "manifest_errors": manifest_errors,
            "ok_rows": ok_rows,
            "api_error_rows": api_error_rows,
            "placeholder_rows": line_count - ok_rows,
            "unique_events_observed": len(events),
            "unique_bases_observed": len(event_bases),
            "unique_exchanges_observed": len({exchange for exchange in event_exchanges if exchange}),
            "observed_event_granularity_slots": observed_slot_count,
            "ok_events": ok_event_count,
            "ok_bases": ok_base_count,
            "ok_exchanges": ok_exchange_count,
            "ok_event_granularity_slots": ok_slot_count,
            "ok_event_fraction": ok_event_fraction,
            "ok_slot_fraction": ok_slot_fraction,
            "api_error_slot_count": api_error_slot_count,
            "api_error_slot_rate": api_error_slot_rate,
            "max_single_exchange_ok_event_fraction": max_single_exchange_ok_event_fraction,
        },
        "counts": {
            "status": _counter_to_dict(status_counts),
            "rows_by_exchange": _counter_to_dict(rows_by_exchange),
            "ok_rows_by_exchange": _counter_to_dict(ok_rows_by_exchange),
            "error_rows_by_exchange": _counter_to_dict(error_rows_by_exchange),
            "placeholder_rows_by_exchange": _counter_to_dict(placeholder_rows_by_exchange),
            "rows_by_granularity": _counter_to_dict(rows_by_granularity),
            "ok_rows_by_granularity": _counter_to_dict(ok_rows_by_granularity),
            "ok_events_by_exchange": _counter_to_dict(ok_events_by_exchange),
        },
        "top_ok_events": [
            {"event_id": event_id, "ok_rows": int(count)}
            for event_id, count in ok_rows_by_event.most_common(20)
        ],
        "next_step_after_ready": (
            "Run listing-event normalizer on accepted history quality; keep replay/grid/live/API blocked until normalizer sets replay_allowed=true."
            if accepted
            else "Do not replay/grid. Revise listing-event history collection plan: improve Gate historical coverage or resample events with two-venue OK coverage while retaining no-data/delisted outcomes."
        ),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate listing-event OHLCV history data quality.")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-ok-rows", type=int, default=ListingEventHistoryQualityConfig.min_ok_rows)
    parser.add_argument("--min-ok-events", type=int, default=ListingEventHistoryQualityConfig.min_ok_events)
    parser.add_argument("--min-ok-bases", type=int, default=ListingEventHistoryQualityConfig.min_ok_bases)
    parser.add_argument("--min-ok-exchanges", type=int, default=ListingEventHistoryQualityConfig.min_ok_exchanges)
    parser.add_argument(
        "--min-ok-event-granularity-slots",
        type=int,
        default=ListingEventHistoryQualityConfig.min_ok_event_granularity_slots,
    )
    parser.add_argument("--min-ok-event-fraction", type=float, default=ListingEventHistoryQualityConfig.min_ok_event_fraction)
    parser.add_argument("--min-ok-slot-fraction", type=float, default=ListingEventHistoryQualityConfig.min_ok_slot_fraction)
    parser.add_argument("--max-api-error-slot-rate", type=float, default=ListingEventHistoryQualityConfig.max_api_error_slot_rate)
    parser.add_argument(
        "--max-single-exchange-ok-event-fraction",
        type=float,
        default=ListingEventHistoryQualityConfig.max_single_exchange_ok_event_fraction,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = ListingEventHistoryQualityConfig(
        min_ok_rows=args.min_ok_rows,
        min_ok_events=args.min_ok_events,
        min_ok_bases=args.min_ok_bases,
        min_ok_exchanges=args.min_ok_exchanges,
        min_ok_event_granularity_slots=args.min_ok_event_granularity_slots,
        min_ok_event_fraction=args.min_ok_event_fraction,
        min_ok_slot_fraction=args.min_ok_slot_fraction,
        max_api_error_slot_rate=args.max_api_error_slot_rate,
        max_single_exchange_ok_event_fraction=args.max_single_exchange_ok_event_fraction,
    )
    input_path = Path(args.input_jsonl)
    manifest_path = Path(args.manifest)
    output_path = Path(args.output)
    result = evaluate_listing_event_history_quality(load_jsonl(input_path), load_json(manifest_path), cfg)
    result["input_jsonl"] = str(input_path)
    result["manifest_path"] = str(manifest_path)
    result["output_path"] = str(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
