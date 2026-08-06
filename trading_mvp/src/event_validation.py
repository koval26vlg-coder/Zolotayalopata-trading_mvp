from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from event_slicer import EventSliceConfig, build_event_slice_report
from trading import utc_stamp


@dataclass(frozen=True)
class EventValidationConfig:
    train_fraction: float = 0.70
    walk_forward_windows: int = 4
    walk_forward_min_pass_ratio: float = 0.75
    min_events: int = 20
    min_reclaimed: int = 10
    min_target_before_stop_rate: float = 0.60
    min_target_rate_all: float = 0.20
    max_false_sweep_rate: float = 0.50
    max_avg_adverse_bps: float = 0.0
    min_favorable_to_adverse: float = 1.0
    min_sweep_intensity_bps: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0)
    max_time_to_reclaim_sec: tuple[float, ...] = (0.0, 30.0, 60.0, 120.0, 300.0)
    max_pre_spread_bps: tuple[float, ...] = (0.0, 1.0, 3.0, 6.0)
    max_abs_basis_bps: tuple[float, ...] = (0.0, 5.0, 10.0, 25.0, 100.0)
    min_trade_notional_quote: tuple[float, ...] = (0.0, 2500.0, 5000.0, 10000.0)
    stress_favorable_haircut_bps: float = 1.0
    stress_adverse_widen_bps: float = 1.0
    stress_target_bps: float = 6.0
    stress_stop_bps: float = 3.0
    top_n: int = 50


def default_event_validation_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"event_validation_report_{utc_stamp()}.json"


def run_event_validation_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    cfg: EventValidationConfig | None = None,
) -> dict[str, Any]:
    src = Path(input_path)
    payload = json.loads(src.read_text(encoding="utf-8"))
    report = build_event_validation_report(payload, cfg or EventValidationConfig())
    report["input"] = str(src)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        report["output"] = str(out)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_event_validation_report(event_quality_report: dict[str, Any], cfg: EventValidationConfig) -> dict[str, Any]:
    if event_quality_report.get("mode") != "event_quality_report":
        raise ValueError("event-validation expects an event_quality_report JSON input")

    events = sorted(
        [event for event in event_quality_report.get("events", []) if isinstance(event, dict)],
        key=lambda item: (_as_float(item.get("sweep_ts")) or 0.0, str(item.get("market") or "")),
    )
    train_events, oos_events = _train_oos_split(events, cfg.train_fraction)
    selected_slice, train_slice_report = _select_train_slice(event_quality_report, train_events, cfg)

    if selected_slice is None:
        empty = _empty_phase()
        return {
            "mode": "event_validation_report",
            "config": asdict(cfg),
            "source_event_report": event_quality_report.get("input"),
            "events_analyzed": len(events),
            "train_fraction": cfg.train_fraction,
            "split": {"train_events": len(train_events), "oos_events": len(oos_events)},
            "selected_slice": None,
            "train_slice_report": train_slice_report,
            "train": empty,
            "oos": empty,
            "walk_forward": {"accepted": False, "windows": [], "accepted_windows": 0, "accepted_ratio": 0.0},
            "stress": {"accepted": False, "summary": _summarize_validation([], cfg), "events_analyzed": 0},
            "accepted": False,
            "decision": "REJECTED_NO_TRAIN_SLICE",
            "rejection_reasons": ["no_train_slice"],
        }

    selected_train = _filter_by_slice(train_events, selected_slice)
    selected_oos = _filter_by_slice(oos_events, selected_slice)
    selected_all = _filter_by_slice(events, selected_slice)
    train_selected_summary = _summarize_validation(selected_train, cfg)
    oos_summary = _summarize_validation(selected_oos, cfg)
    walk_forward = _walk_forward_report(events, selected_slice, cfg)
    stress = _stress_report(selected_oos or selected_all, cfg)

    train_phase = {
        "raw": _summarize_validation(train_events, cfg),
        "selected": train_selected_summary,
    }
    oos_phase = {
        "raw": _summarize_validation(oos_events, cfg),
        "selected_events": len(selected_oos),
        "summary": oos_summary,
        "accepted": bool(oos_summary["accepted"]),
        "rejection_reasons": oos_summary["eligibility_reasons"],
    }
    rejection_reasons = _overall_rejection_reasons(
        selected_slice=selected_slice,
        train_selected=train_selected_summary,
        oos=oos_phase,
        walk_forward=walk_forward,
        stress=stress,
    )
    accepted = not rejection_reasons

    return {
        "mode": "event_validation_report",
        "config": asdict(cfg),
        "source_event_report": event_quality_report.get("input"),
        "events_analyzed": len(events),
        "train_fraction": cfg.train_fraction,
        "split": {"train_events": len(train_events), "oos_events": len(oos_events)},
        "selected_slice": selected_slice,
        "train_slice_report": train_slice_report,
        "train": train_phase,
        "oos": oos_phase,
        "walk_forward": walk_forward,
        "stress": stress,
        "all_selected": _summarize_validation(selected_all, cfg),
        "accepted": accepted,
        "decision": "ACCEPTED_RESEARCH_VALIDATION" if accepted else "REJECTED_VALIDATION_GATE",
        "rejection_reasons": rejection_reasons,
    }


def _select_train_slice(
    source_report: dict[str, Any],
    train_events: list[dict[str, Any]],
    cfg: EventValidationConfig,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    slice_cfg = EventSliceConfig(
        min_events=cfg.min_events,
        min_reclaimed=cfg.min_reclaimed,
        min_target_before_stop_rate=cfg.min_target_before_stop_rate,
        min_target_rate_all=cfg.min_target_rate_all,
        max_false_sweep_rate=cfg.max_false_sweep_rate,
        max_avg_adverse_bps=cfg.max_avg_adverse_bps,
        min_favorable_to_adverse=cfg.min_favorable_to_adverse,
        min_sweep_intensity_bps=cfg.min_sweep_intensity_bps,
        max_time_to_reclaim_sec=cfg.max_time_to_reclaim_sec,
        max_pre_spread_bps=cfg.max_pre_spread_bps,
        max_abs_basis_bps=cfg.max_abs_basis_bps,
        min_trade_notional_quote=cfg.min_trade_notional_quote,
        top_n=cfg.top_n,
    )
    train_report = {
        "mode": "event_quality_report",
        "input": source_report.get("input"),
        "events": train_events,
        "summary": _summarize_validation(train_events, cfg),
    }
    slice_report = build_event_slice_report(train_report, slice_cfg)
    eligible = [item for item in slice_report.get("top_slices", []) if item.get("eligible")]
    candidates = eligible or list(slice_report.get("top_slices", []))
    if not candidates:
        return None, _compact_slice_report(slice_report)
    selected = dict(candidates[0])
    selected["selection_basis"] = "train_eligible" if eligible else "train_top_ineligible"
    return selected, _compact_slice_report(slice_report)


def _compact_slice_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": report.get("mode"),
        "events_analyzed": report.get("events_analyzed"),
        "generated_slices": report.get("generated_slices"),
        "eligible_slices": report.get("eligible_slices"),
        "top_slices": report.get("top_slices", [])[:10],
    }


def _train_oos_split(events: list[dict[str, Any]], train_fraction: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not events:
        return [], []
    if len(events) == 1:
        return events, []
    bounded = min(max(train_fraction, 0.05), 0.95)
    split = int(len(events) * bounded)
    split = min(max(split, 1), len(events) - 1)
    return events[:split], events[split:]


def _filter_by_slice(events: list[dict[str, Any]], selected_slice: dict[str, Any]) -> list[dict[str, Any]]:
    market = _wildcard_to_none(selected_slice.get("market"))
    side = _wildcard_to_none(selected_slice.get("expected_side"))
    return [
        event
        for event in events
        if _event_matches(
            event,
            market=market,
            side=side,
            min_sweep=_as_float(selected_slice.get("min_sweep_intensity_bps")) or 0.0,
            max_reclaim=_as_float(selected_slice.get("max_time_to_reclaim_sec")) or 0.0,
            max_spread=_as_float(selected_slice.get("max_pre_spread_bps")) or 0.0,
            max_basis=_as_float(selected_slice.get("max_abs_basis_bps")) or 0.0,
            min_notional=_as_float(selected_slice.get("min_trade_notional_quote")) or 0.0,
        )
    ]


def _event_matches(
    event: dict[str, Any],
    *,
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


def _walk_forward_report(events: list[dict[str, Any]], selected_slice: dict[str, Any], cfg: EventValidationConfig) -> dict[str, Any]:
    windows = _split_windows(events, cfg.walk_forward_windows)
    reports: list[dict[str, Any]] = []
    for idx, window in enumerate(windows):
        selected = _filter_by_slice(window, selected_slice)
        summary = _summarize_validation(selected, cfg)
        reports.append(
            {
                "window": idx + 1,
                "raw_events": len(window),
                "selected_events": len(selected),
                "accepted": bool(summary["accepted"]),
                "summary": summary,
            }
        )
    accepted_windows = sum(1 for item in reports if item["accepted"])
    accepted_ratio = accepted_windows / len(reports) if reports else 0.0
    return {
        "accepted": bool(reports) and accepted_ratio >= cfg.walk_forward_min_pass_ratio,
        "windows": reports,
        "accepted_windows": accepted_windows,
        "accepted_ratio": accepted_ratio,
        "min_pass_ratio": cfg.walk_forward_min_pass_ratio,
    }


def _stress_report(events: list[dict[str, Any]], cfg: EventValidationConfig) -> dict[str, Any]:
    stressed = [_stress_event(event, cfg) for event in events]
    summary = _summarize_validation(stressed, cfg)
    return {
        "accepted": bool(summary["accepted"]),
        "summary": summary,
        "events_analyzed": len(stressed),
        "favorable_haircut_bps": cfg.stress_favorable_haircut_bps,
        "adverse_widen_bps": cfg.stress_adverse_widen_bps,
        "target_bps": cfg.stress_target_bps,
        "stop_bps": cfg.stress_stop_bps,
    }


def _stress_event(event: dict[str, Any], cfg: EventValidationConfig) -> dict[str, Any]:
    stressed = dict(event)
    if not event.get("reclaimed"):
        stressed["outcome"] = "no_reclaim"
        return stressed
    favorable = (_as_float(event.get("favorable_excursion_bps")) or 0.0) - abs(cfg.stress_favorable_haircut_bps)
    adverse = (_as_float(event.get("adverse_excursion_bps")) or 0.0) - abs(cfg.stress_adverse_widen_bps)
    stressed["favorable_excursion_bps"] = favorable
    stressed["adverse_excursion_bps"] = adverse
    stressed["target_hit"] = favorable >= cfg.stress_target_bps
    stressed["stop_hit"] = adverse <= -abs(cfg.stress_stop_bps)
    if str(event.get("outcome")) == "target_before_stop" and stressed["target_hit"] and not stressed["stop_hit"]:
        stressed["first_hit"] = "target"
        stressed["outcome"] = "target_before_stop"
    elif stressed["stop_hit"]:
        stressed["first_hit"] = "stop"
        stressed["outcome"] = "stop_before_target"
    elif stressed["target_hit"]:
        stressed["first_hit"] = "target"
        stressed["outcome"] = "target_before_stop"
    else:
        stressed["first_hit"] = None
        stressed["outcome"] = "reclaimed_no_hit"
    return stressed


def _split_windows(events: list[dict[str, Any]], window_count: int) -> list[list[dict[str, Any]]]:
    if not events:
        return []
    count = min(max(window_count, 1), len(events))
    base = len(events) // count
    remainder = len(events) % count
    windows: list[list[dict[str, Any]]] = []
    start = 0
    for idx in range(count):
        size = base + (1 if idx < remainder else 0)
        windows.append(events[start : start + size])
        start += size
    return windows


def _summarize_validation(events: list[dict[str, Any]], cfg: EventValidationConfig) -> dict[str, Any]:
    total = len(events)
    outcomes = Counter(str(event.get("outcome")) for event in events)
    reclaimed = sum(1 for event in events if event.get("reclaimed"))
    target_first = outcomes.get("target_before_stop", 0)
    stop_first = outcomes.get("stop_before_target", 0)
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
        "accepted": not reasons,
        "eligibility_reasons": reasons,
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
        "avg_time_to_reclaim_sec": _avg(event.get("time_to_reclaim_sec") for event in events if event.get("reclaimed")),
        "avg_trade_notional_quote": _avg(event.get("trade_notional_quote") for event in events),
        "avg_pre_spread_bps": _avg(event.get("pre_spread_bps") for event in events),
        "avg_abs_basis_bps": _avg(abs(value) for value in _float_values(event.get("mark_index_basis_bps") for event in events)),
        "avg_favorable_excursion_bps": avg_favorable,
        "avg_adverse_excursion_bps": avg_adverse,
        "favorable_to_adverse": favorable_to_adverse,
        "outcomes": dict(outcomes),
    }


def _eligibility_reasons(
    cfg: EventValidationConfig,
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


def _overall_rejection_reasons(
    *,
    selected_slice: dict[str, Any],
    train_selected: dict[str, Any],
    oos: dict[str, Any],
    walk_forward: dict[str, Any],
    stress: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if selected_slice.get("selection_basis") != "train_eligible":
        reasons.append("no_train_eligible_slice")
    if not train_selected.get("accepted"):
        reasons.append("train_selected_rejected")
    if not oos.get("accepted"):
        reasons.append("oos_rejected")
    if not walk_forward.get("accepted"):
        reasons.append("walk_forward_rejected")
    if not stress.get("accepted"):
        reasons.append("stress_rejected")
    return reasons


def _empty_phase() -> dict[str, Any]:
    return {"raw": {}, "selected": {}, "accepted": False, "rejection_reasons": ["no_events"]}


def _wildcard_to_none(value: Any) -> str | None:
    text = str(value or "*")
    return None if text == "*" else text


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


def _ratio(avg_favorable: float | None, avg_adverse: float | None) -> float | None:
    if avg_favorable is None or avg_adverse is None or avg_adverse == 0:
        return None
    return avg_favorable / abs(avg_adverse)
