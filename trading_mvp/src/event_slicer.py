from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from trading import utc_stamp


@dataclass(frozen=True)
class EventSliceConfig:
    min_events: int = 20
    min_reclaimed: int = 10
    min_target_before_stop_rate: float = 0.60
    min_target_rate_all: float = 0.20
    max_false_sweep_rate: float = 1.0
    max_avg_adverse_bps: float = 0.0
    min_favorable_to_adverse: float = 0.0
    min_sweep_intensity_bps: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0)
    max_time_to_reclaim_sec: tuple[float, ...] = (0.0, 30.0, 60.0, 120.0, 300.0)
    max_pre_spread_bps: tuple[float, ...] = (0.0, 1.0, 3.0, 6.0)
    max_abs_basis_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 25.0, 100.0)
    min_trade_notional_quote: tuple[float, ...] = (0.0, 2500.0, 5000.0, 10000.0)
    top_n: int = 50


def default_event_slice_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"event_slice_optimizer_{utc_stamp()}.json"


def run_event_slice_optimizer_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    cfg: EventSliceConfig | None = None,
) -> dict[str, Any]:
    src = Path(input_path)
    payload = json.loads(src.read_text(encoding="utf-8"))
    report = build_event_slice_report(payload, cfg or EventSliceConfig())
    report["input"] = str(src)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        report["output"] = str(out)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_event_slice_report(event_quality_report: dict[str, Any], cfg: EventSliceConfig) -> dict[str, Any]:
    if event_quality_report.get("mode") != "event_quality_report":
        raise ValueError("event-slice optimizer expects an event_quality_report JSON input")
    events = [event for event in event_quality_report.get("events", []) if isinstance(event, dict)]
    markets = sorted({str(event.get("market")) for event in events if event.get("market")})
    sides = sorted({str(event.get("expected_side")) for event in events if event.get("expected_side")})
    raw_slices = _generate_slices(events, markets, sides, cfg)
    slices = _dedupe_equivalent_slices(raw_slices)
    ranked = sorted(
        slices,
        key=lambda item: (
            bool(item["eligible"]),
            float(item["target_before_stop_rate"]),
            float(item["target_rate_all"]),
            float(item["quality_score"]),
            int(item["total_events"]),
        ),
        reverse=True,
    )
    top_slices = ranked[: cfg.top_n]
    eligible = [item for item in ranked if item["eligible"]]
    return {
        "mode": "event_slice_optimizer",
        "config": asdict(cfg),
        "source_event_report": event_quality_report.get("input"),
        "source_summary": event_quality_report.get("summary", {}),
        "events_analyzed": len(events),
        "markets": markets,
        "sides": sides,
        "generated_raw_slices": len(raw_slices),
        "generated_slices": len(slices),
        "eligible_slices": len(eligible),
        "top_slices": top_slices,
        "best_by_market": _best_by(top_slices, "market"),
        "best_by_side": _best_by(top_slices, "expected_side"),
    }


def _generate_slices(
    events: list[dict[str, Any]],
    markets: list[str],
    sides: list[str],
    cfg: EventSliceConfig,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    indexed_events = list(enumerate(events))
    seen: set[tuple[Any, ...]] = set()
    market_options: list[str | None] = [None, *markets]
    side_options: list[str | None] = [None, *sides]
    for market in market_options:
        for side in side_options:
            for min_sweep in _unique_floats(cfg.min_sweep_intensity_bps):
                for max_reclaim in _unique_floats(cfg.max_time_to_reclaim_sec):
                    for max_spread in _unique_floats(cfg.max_pre_spread_bps):
                        for max_basis in _unique_floats(cfg.max_abs_basis_bps):
                            for min_notional in _unique_floats(cfg.min_trade_notional_quote):
                                key = (market, side, min_sweep, max_reclaim, max_spread, max_basis, min_notional)
                                if key in seen:
                                    continue
                                seen.add(key)
                                filtered_pairs = [
                                    (idx, event)
                                    for idx, event in indexed_events
                                    if _event_matches(event, market, side, min_sweep, max_reclaim, max_spread, max_basis, min_notional)
                                ]
                                if not filtered_pairs:
                                    continue
                                filtered = [event for _, event in filtered_pairs]
                                event_signature = tuple(idx for idx, _ in filtered_pairs)
                                results.append(
                                    _summarize_slice(
                                        filtered,
                                        cfg,
                                        {
                                            "market": market or "*",
                                            "expected_side": side or "*",
                                            "min_sweep_intensity_bps": min_sweep,
                                            "max_time_to_reclaim_sec": max_reclaim,
                                            "max_pre_spread_bps": max_spread,
                                            "max_abs_basis_bps": max_basis,
                                            "min_trade_notional_quote": min_notional,
                                        },
                                        event_signature,
                                    )
                                )
    return results


def _event_matches(
    event: dict[str, Any],
    market: str | None,
    side: str | None,
    min_sweep: float,
    max_reclaim: float,
    max_spread: float,
    max_basis: float,
    min_notional: float,
) -> bool:
    if market is not None and event.get("market") != market:
        return False
    if side is not None and event.get("expected_side") != side:
        return False
    if (_as_float(event.get("sweep_intensity_bps")) or 0.0) < min_sweep:
        return False
    if max_reclaim > 0:
        time_to_reclaim = _as_float(event.get("time_to_reclaim_sec"))
        if time_to_reclaim is None or time_to_reclaim > max_reclaim:
            return False
    if max_spread > 0:
        pre_spread = _as_float(event.get("pre_spread_bps"))
        if pre_spread is None or pre_spread > max_spread:
            return False
    if max_basis > 0:
        basis = _as_float(event.get("mark_index_basis_bps"))
        if basis is None or abs(basis) > max_basis:
            return False
    if min_notional > 0 and (_as_float(event.get("trade_notional_quote")) or 0.0) < min_notional:
        return False
    return True


def _summarize_slice(
    events: list[dict[str, Any]],
    cfg: EventSliceConfig,
    filters: dict[str, Any],
    event_signature: tuple[int, ...],
) -> dict[str, Any]:
    total = len(events)
    outcomes = Counter(str(event.get("outcome")) for event in events)
    target_first = outcomes.get("target_before_stop", 0)
    stop_first = outcomes.get("stop_before_target", 0)
    reclaimed = sum(1 for event in events if event.get("reclaimed"))
    target_before_stop_rate = target_first / reclaimed if reclaimed else 0.0
    target_rate_all = target_first / total if total else 0.0
    false_sweep_rate = (total - target_first) / total if total else 0.0
    avg_favorable = _avg(event.get("favorable_excursion_bps") for event in events if event.get("reclaimed"))
    avg_adverse = _avg(event.get("adverse_excursion_bps") for event in events if event.get("reclaimed"))
    favorable_to_adverse = _ratio(avg_favorable, avg_adverse)
    reasons = _eligibility_reasons(
        cfg,
        total=total,
        reclaimed=reclaimed,
        target_before_stop_rate=target_before_stop_rate,
        target_rate_all=target_rate_all,
        false_sweep_rate=false_sweep_rate,
        avg_adverse=avg_adverse,
        favorable_to_adverse=favorable_to_adverse,
    )
    return {
        **filters,
        "_event_signature": event_signature,
        "_dedupe_preference": _dedupe_preference(filters),
        "eligible": not reasons,
        "eligibility_reasons": reasons,
        "quality_score": _quality_score(
            total=total,
            target_before_stop_rate=target_before_stop_rate,
            target_rate_all=target_rate_all,
            false_sweep_rate=false_sweep_rate,
            avg_favorable=avg_favorable,
            avg_adverse=avg_adverse,
            favorable_to_adverse=favorable_to_adverse,
        ),
        "total_events": total,
        "reclaimed": reclaimed,
        "reclaim_rate": reclaimed / total if total else 0.0,
        "target_before_stop": target_first,
        "stop_before_target": stop_first,
        "target_before_stop_rate": target_before_stop_rate,
        "target_rate_all": target_rate_all,
        "stop_before_target_rate": stop_first / reclaimed if reclaimed else 0.0,
        "false_sweep_rate": false_sweep_rate,
        "avg_sweep_intensity_bps": _avg(event.get("sweep_intensity_bps") for event in events),
        "median_sweep_intensity_bps": _median(event.get("sweep_intensity_bps") for event in events),
        "avg_time_to_reclaim_sec": _avg(event.get("time_to_reclaim_sec") for event in events if event.get("reclaimed")),
        "median_time_to_reclaim_sec": _median(event.get("time_to_reclaim_sec") for event in events if event.get("reclaimed")),
        "avg_trade_notional_quote": _avg(event.get("trade_notional_quote") for event in events),
        "avg_pre_spread_bps": _avg(event.get("pre_spread_bps") for event in events),
        "avg_abs_basis_bps": _avg(abs(value) for value in _float_values(event.get("mark_index_basis_bps") for event in events)),
        "avg_favorable_excursion_bps": avg_favorable,
        "avg_adverse_excursion_bps": avg_adverse,
        "favorable_to_adverse": favorable_to_adverse,
        "outcomes": dict(outcomes),
    }


def _dedupe_equivalent_slices(slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_events: dict[tuple[int, ...], dict[str, Any]] = {}
    for item in slices:
        signature = tuple(item.get("_event_signature") or ())
        current = best_by_events.get(signature)
        if current is None or int(item.get("_dedupe_preference") or 0) > int(current.get("_dedupe_preference") or 0):
            best_by_events[signature] = item
    compact: list[dict[str, Any]] = []
    for item in best_by_events.values():
        cleaned = dict(item)
        cleaned.pop("_event_signature", None)
        cleaned.pop("_dedupe_preference", None)
        compact.append(cleaned)
    return compact


def _dedupe_preference(filters: dict[str, Any]) -> int:
    category_specificity = int(filters.get("market") != "*") + int(filters.get("expected_side") != "*")
    numeric_active = sum(
        1
        for key in (
            "min_sweep_intensity_bps",
            "max_time_to_reclaim_sec",
            "max_pre_spread_bps",
            "max_abs_basis_bps",
            "min_trade_notional_quote",
        )
        if float(filters.get(key) or 0.0) > 0.0
    )
    return category_specificity * 10 - numeric_active


def _eligibility_reasons(
    cfg: EventSliceConfig,
    *,
    total: int,
    reclaimed: int,
    target_before_stop_rate: float,
    target_rate_all: float,
    false_sweep_rate: float,
    avg_adverse: float | None,
    favorable_to_adverse: float | None,
) -> list[str]:
    reasons: list[str] = []
    if total < cfg.min_events:
        reasons.append("min_events")
    if reclaimed < cfg.min_reclaimed:
        reasons.append("min_reclaimed")
    if target_before_stop_rate < cfg.min_target_before_stop_rate:
        reasons.append("min_target_before_stop_rate")
    if target_rate_all < cfg.min_target_rate_all:
        reasons.append("min_target_rate_all")
    if cfg.max_false_sweep_rate < 1.0 and false_sweep_rate > cfg.max_false_sweep_rate:
        reasons.append("max_false_sweep_rate")
    if cfg.max_avg_adverse_bps > 0 and (avg_adverse is None or abs(avg_adverse) > cfg.max_avg_adverse_bps):
        reasons.append("max_avg_adverse_bps")
    if cfg.min_favorable_to_adverse > 0 and (favorable_to_adverse is None or favorable_to_adverse < cfg.min_favorable_to_adverse):
        reasons.append("min_favorable_to_adverse")
    return reasons


def _quality_score(
    *,
    total: int,
    target_before_stop_rate: float,
    target_rate_all: float,
    false_sweep_rate: float,
    avg_favorable: float | None,
    avg_adverse: float | None,
    favorable_to_adverse: float | None,
) -> float:
    adverse_penalty = abs(avg_adverse or 0.0) * 0.5
    favorable_bonus = min(avg_favorable or 0.0, 50.0) * 0.2
    ratio_bonus = min(favorable_to_adverse or 0.0, 5.0) * 3.0
    sample_bonus = min(math.log(total + 1.0), 5.0) * 5.0
    return (
        target_before_stop_rate * 100.0
        + target_rate_all * 50.0
        + favorable_bonus
        + ratio_bonus
        + sample_bonus
        - false_sweep_rate * 25.0
        - adverse_penalty
    )


def _best_by(slices: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in slices:
        value = str(item.get(field) or "*")
        if value not in best:
            best[value] = item
    return best


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_values(values: Any) -> list[float]:
    output: list[float] = []
    for value in values:
        num = _as_float(value)
        if num is not None:
            output.append(num)
    return output


def _avg(values: Any) -> float | None:
    nums = _float_values(values)
    if not nums:
        return None
    return sum(nums) / len(nums)


def _median(values: Any) -> float | None:
    nums = sorted(_float_values(values))
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2.0


def _ratio(avg_favorable: float | None, avg_adverse: float | None) -> float | None:
    if avg_favorable is None or avg_adverse is None or avg_adverse == 0:
        return None
    return avg_favorable / abs(avg_adverse)


def _unique_floats(values: tuple[float, ...]) -> list[float]:
    return sorted({float(value) for value in values})
