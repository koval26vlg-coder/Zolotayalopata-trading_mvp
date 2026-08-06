from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pit_universe_public_probe import REQUIRED_SNAPSHOT_FIELDS


STATE_FIELDS = (
    "missing_since_ts",
    "observed_now",
    "tombstone",
    "presence_state",
)


@dataclass(frozen=True)
class PitQualityConfig:
    min_cycles: int = 12
    min_exchanges_per_cycle: int = 2
    max_error_cycle_ratio: float = 0.05
    max_duplicate_snapshot_keys: int = 0
    min_dual_venue_bbo_size_coverage: float = 0.95
    require_final: bool = True


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_artifact(manifest_path: Path, raw: Any, fallback: str) -> Path:
    value = str(raw or fallback)
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def _timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                yield line_number, None, f"{type(exc).__name__}: {exc}"
                continue
            if not isinstance(payload, dict):
                yield line_number, None, "row_not_object"
                continue
            yield line_number, payload, None


def evaluate_pit_snapshot_quality(
    manifest_path: str | Path,
    config: PitQualityConfig = PitQualityConfig(),
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    if not 0.0 <= float(config.min_dual_venue_bbo_size_coverage) <= 1.0:
        raise ValueError("min_dual_venue_bbo_size_coverage must be in [0, 1]")
    manifest_path = Path(manifest_path)
    manifest = _load_json(manifest_path)
    snapshots_path = _resolve_artifact(manifest_path, manifest.get("snapshots_path"), "snapshots.jsonl")
    cycles_path = _resolve_artifact(manifest_path, manifest.get("cycles_path"), "cycles.jsonl")
    reasons: list[str] = []
    if config.require_final and not bool(manifest.get("final")):
        reasons.append("manifest_not_final")
    if not snapshots_path.exists():
        reasons.append("snapshots_missing")
    if not cycles_path.exists():
        reasons.append("cycle_journal_missing")

    rows = 0
    invalid_json_rows = 0
    missing_required_fields = Counter()
    duplicate_snapshot_keys = 0
    seen_keys: set[tuple[Any, ...]] = set()
    cycles_seen: set[int] = set()
    exchanges_by_cycle: dict[int, set[str]] = defaultdict(set)
    state_invariant_errors = 0
    binance_invariant_errors = 0
    first_seen_by_market: dict[tuple[str, str], str] = {}
    last_seen_by_market: dict[tuple[str, str], float] = {}
    tombstones = 0
    eligible_bbo_by_cycle_base: dict[tuple[int, str], dict[str, bool]] = defaultdict(dict)

    if snapshots_path.exists():
        for _line_number, row, error in _iter_jsonl(snapshots_path):
            if error or row is None:
                invalid_json_rows += 1
                continue
            rows += 1
            for field in (*REQUIRED_SNAPSHOT_FIELDS, *STATE_FIELDS):
                if field not in row:
                    missing_required_fields[field] += 1
            cycle = int(row.get("cycle") or 0)
            exchange = str(row.get("exchange") or "")
            symbol = str(row.get("symbol") or "")
            key = (str(row.get("run_id") or manifest.get("run_id") or ""), cycle, exchange, symbol)
            if key in seen_keys:
                duplicate_snapshot_keys += 1
            seen_keys.add(key)
            if cycle > 0:
                cycles_seen.add(cycle)
                if exchange:
                    exchanges_by_cycle[cycle].add(exchange)

            market = (exchange, symbol)
            first_seen = str(row.get("first_seen_ts") or "")
            first_ts = _timestamp(first_seen)
            last_ts = _timestamp(row.get("last_seen_ts"))
            snapshot_ts = _timestamp(row.get("snapshot_ts"))
            prior_first_seen = first_seen_by_market.setdefault(market, first_seen)
            if first_seen != prior_first_seen:
                state_invariant_errors += 1
            prior_last = last_seen_by_market.get(market)
            if first_ts is None or last_ts is None or snapshot_ts is None or not (first_ts <= last_ts <= snapshot_ts):
                state_invariant_errors += 1
            if prior_last is not None and last_ts is not None and last_ts < prior_last:
                state_invariant_errors += 1
            if last_ts is not None:
                last_seen_by_market[market] = last_ts

            is_tombstone = bool(row.get("tombstone"))
            if is_tombstone:
                tombstones += 1
                if row.get("observed_now") is not False or bool(row.get("listed_now")) or not row.get("missing_since_ts"):
                    state_invariant_errors += 1
            elif row.get("observed_now") is not True:
                state_invariant_errors += 1
            if row.get("binance_spot_listed") is True and row.get("eligible_non_binance_spot") is not False:
                binance_invariant_errors += 1
            if row.get("excluded_by_binance_spot") != row.get("binance_spot_listed"):
                binance_invariant_errors += 1
            if (
                cycle > 0
                and not is_tombstone
                and row.get("observed_now") is True
                and row.get("listed_now") is True
                and row.get("eligible_non_binance_spot") is True
                and exchange in {"mexc", "gateio"}
            ):
                base = str(row.get("base") or "").upper()
                try:
                    bid_size = float(row.get("bid_size_contracts"))
                    ask_size = float(row.get("ask_size_contracts"))
                    size_complete = bid_size > 0 and ask_size > 0
                except (TypeError, ValueError):
                    size_complete = False
                if base:
                    eligible_bbo_by_cycle_base[(cycle, base)][exchange] = size_complete

    cycle_rows = 0
    invalid_cycle_rows = 0
    error_cycles = 0
    cycle_numbers: set[int] = set()
    thin_exchange_cycles = 0
    if cycles_path.exists():
        for _line_number, cycle_row, error in _iter_jsonl(cycles_path):
            if error or cycle_row is None:
                invalid_cycle_rows += 1
                continue
            cycle_rows += 1
            cycle = int(cycle_row.get("cycle") or 0)
            if cycle in cycle_numbers or cycle <= 0:
                invalid_cycle_rows += 1
            cycle_numbers.add(cycle)
            errors = cycle_row.get("errors") or {}
            successful = {str(value) for value in (cycle_row.get("successful_exchanges") or [])}
            if errors:
                error_cycles += 1
            if len(successful) < config.min_exchanges_per_cycle:
                thin_exchange_cycles += 1

    cycle_count = int(manifest.get("cycle_count") or 0)
    error_cycle_ratio = error_cycles / cycle_rows if cycle_rows else 1.0
    dual_venue_bbo_groups = [
        values
        for values in eligible_bbo_by_cycle_base.values()
        if {"mexc", "gateio"}.issubset(values)
    ]
    dual_venue_bbo_complete = sum(
        values.get("mexc") is True and values.get("gateio") is True
        for values in dual_venue_bbo_groups
    )
    dual_venue_bbo_size_coverage = (
        dual_venue_bbo_complete / len(dual_venue_bbo_groups)
        if dual_venue_bbo_groups
        else 1.0
    )
    if cycle_count < config.min_cycles or len(cycles_seen) < config.min_cycles:
        reasons.append("insufficient_cycles")
    if cycle_rows != cycle_count:
        reasons.append("cycle_journal_count_mismatch")
    if int(manifest.get("rows_total") or 0) != rows:
        reasons.append("manifest_row_count_mismatch")
    if invalid_json_rows or invalid_cycle_rows:
        reasons.append("invalid_json_rows")
    if missing_required_fields:
        reasons.append("missing_required_fields")
    if duplicate_snapshot_keys > config.max_duplicate_snapshot_keys:
        reasons.append("duplicate_snapshot_keys")
    if state_invariant_errors:
        reasons.append("state_invariant_errors")
    if binance_invariant_errors:
        reasons.append("binance_membership_invariant_errors")
    if error_cycle_ratio > config.max_error_cycle_ratio:
        reasons.append("error_cycle_ratio_exceeded")
    if thin_exchange_cycles:
        reasons.append("insufficient_exchange_coverage")
    if dual_venue_bbo_size_coverage < float(config.min_dual_venue_bbo_size_coverage):
        reasons.append("dual_venue_bbo_size_coverage_below_minimum")

    reasons = list(dict.fromkeys(reasons))
    replay_allowed = not reasons
    report = {
        "mode": "pit_universe_snapshot_data_quality",
        "ok": replay_allowed,
        "decision": "PIT_UNIVERSE_DATA_QUALITY_ACCEPTED" if replay_allowed else "PIT_UNIVERSE_DATA_QUALITY_REJECTED",
        "research_only": True,
        "strategy_accepted": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "replay_allowed": replay_allowed,
        "manifest_path": str(manifest_path),
        "snapshots_path": str(snapshots_path),
        "cycles_path": str(cycles_path),
        "config": asdict(config),
        "reasons": reasons,
        "metrics": {
            "rows": rows,
            "manifest_rows": int(manifest.get("rows_total") or 0),
            "cycles": len(cycles_seen),
            "manifest_cycles": cycle_count,
            "cycle_journal_rows": cycle_rows,
            "exchanges": sorted({exchange for values in exchanges_by_cycle.values() for exchange in values}),
            "invalid_json_rows": invalid_json_rows,
            "invalid_cycle_rows": invalid_cycle_rows,
            "missing_required_fields": dict(missing_required_fields),
            "duplicate_snapshot_keys": duplicate_snapshot_keys,
            "state_invariant_errors": state_invariant_errors,
            "binance_membership_invariant_errors": binance_invariant_errors,
            "tombstones": tombstones,
            "error_cycles": error_cycles,
            "error_cycle_ratio": error_cycle_ratio,
            "thin_exchange_cycles": thin_exchange_cycles,
            "dual_venue_bbo_markets": len(dual_venue_bbo_groups),
            "dual_venue_bbo_complete_markets": dual_venue_bbo_complete,
            "dual_venue_bbo_size_coverage": dual_venue_bbo_size_coverage,
        },
        "next_valid_move": (
            "Build a separate replay-validation PlanOnly packet; grid/live/API keys remain blocked."
            if replay_allowed
            else "Reject or repair/recollect the dataset; do not run replay/grid/live/API-key steps."
        ),
    }
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output"] = str(target)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="PIT universe snapshot data-quality gate")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out")
    parser.add_argument("--min-cycles", type=int, default=12)
    parser.add_argument("--min-exchanges-per-cycle", type=int, default=2)
    parser.add_argument("--max-error-cycle-ratio", type=float, default=0.05)
    parser.add_argument("--min-dual-venue-bbo-size-coverage", type=float, default=0.95)
    args = parser.parse_args()
    report = evaluate_pit_snapshot_quality(
        args.manifest,
        PitQualityConfig(
            min_cycles=args.min_cycles,
            min_exchanges_per_cycle=args.min_exchanges_per_cycle,
            max_error_cycle_ratio=args.max_error_cycle_ratio,
            min_dual_venue_bbo_size_coverage=args.min_dual_venue_bbo_size_coverage,
        ),
        args.out,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
