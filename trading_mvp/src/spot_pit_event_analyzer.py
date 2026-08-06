from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


REPORT_SCHEMA = "spot_pit_event_analysis_v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _segment_cycle_groups(segments_dir: Path, run_id: str) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    current_cycle: int | None = None
    current_rows: list[dict[str, Any]] = []
    for path in sorted(segments_dir.glob("segment_*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid segment JSONL at {path}:{line_number}: {exc}") from exc
                cycle = int(row.get("cycle") or 0)
                if cycle <= 0:
                    raise ValueError(f"invalid cycle at {path}:{line_number}")
                if str(row.get("run_id") or "") != run_id:
                    raise ValueError(f"segment run_id mismatch at {path}:{line_number}")
                if current_cycle is None:
                    current_cycle = cycle
                if cycle != current_cycle:
                    if cycle <= current_cycle:
                        raise ValueError(f"non-monotonic segment cycles: {current_cycle} -> {cycle}")
                    yield current_cycle, current_rows
                    current_cycle = cycle
                    current_rows = []
                current_rows.append(row)
    if current_cycle is not None:
        yield current_cycle, current_rows


def _journal_cycles(path: Path, run_id: str) -> Iterator[tuple[int, int]]:
    expected_cycle = 1
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid cycle journal at {path}:{line_number}: {exc}") from exc
            cycle = int(row.get("cycle") or 0)
            if str(row.get("run_id") or "") != run_id:
                raise ValueError(f"cycle journal run_id mismatch at {path}:{line_number}")
            if cycle != expected_cycle:
                raise ValueError(f"cycle journal is not contiguous: expected={expected_cycle}, observed={cycle}")
            rows = int(row.get("rows") or 0)
            if rows < 0:
                raise ValueError(f"negative cycle row count at {path}:{line_number}")
            yield cycle, rows
            expected_cycle += 1


def _cycle_groups(segments_dir: Path, cycles_path: Path, run_id: str) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    segment_groups = iter(_segment_cycle_groups(segments_dir, run_id))
    current_group = next(segment_groups, None)
    for cycle, expected_rows in _journal_cycles(cycles_path, run_id):
        if current_group is not None and current_group[0] < cycle:
            raise ValueError(f"segment cycle {current_group[0]} is absent from journal")
        if current_group is not None and current_group[0] == cycle:
            rows = current_group[1]
            current_group = next(segment_groups, None)
        else:
            rows = []
        if len(rows) != expected_rows:
            raise ValueError(f"cycle row count mismatch: cycle={cycle}, journal={expected_rows}, segments={len(rows)}")
        yield cycle, rows
    if current_group is not None:
        raise ValueError(f"segment cycle {current_group[0]} is beyond the cycle journal")


def _venue_observations(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    observations: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("tombstone") or row.get("listed_now") is not True or row.get("eligible_non_binance_spot") is not True:
            continue
        try:
            bid = float(row["bid"])
            ask = float(row["ask"])
            spread = float(row["spread_bps"])
            volume = float(row["quote_volume_24h"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (bid, ask, spread, volume)) or bid <= 0 or ask < bid or volume < 0:
            continue
        item = dict(row)
        item.update({"bid": bid, "ask": ask, "spread_bps": spread, "quote_volume_24h": volume, "mid": (bid + ask) / 2.0})
        base = str(row.get("base") or "").upper()
        exchange = str(row.get("exchange") or "")
        if base and exchange:
            observations[(base, exchange)] = item
    return observations


def _best_observations(observations: dict[tuple[str, str], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (base, _exchange), row in observations.items():
        candidates[base].append(row)
    return {
        base: min(values, key=lambda row: (float(row["spread_bps"]), str(row.get("exchange"))))
        for base, values in candidates.items()
        if base
    }


def _metrics(trades: list[dict[str, Any]], key: str) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda row: (int(row["exit_cycle"]), str(row["trade_id"])))
    values = [float(row[key]) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    notional = float(ordered[0]["notional_quote"]) if ordered else 100.0
    quote_values = [value / 10000.0 * notional for value in values]
    equity = peak = max_drawdown = 0.0
    per_base: dict[str, float] = defaultdict(float)
    for trade, quote in zip(ordered, quote_values):
        equity += quote
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        base = str(trade["base"])
        per_base[base] += quote
    positive_by_base = {base: value for base, value in per_base.items() if value > 0}
    total_positive = sum(positive_by_base.values())
    concentration = max(positive_by_base.values()) / total_positive if total_positive > 0 else 1.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(ordered),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(ordered) if ordered else 0.0,
        "net_pnl_bps": sum(values),
        "net_pnl_quote": sum(quote_values),
        "expectancy_bps": sum(values) / len(values) if values else None,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "profit_factor_infinite": bool(gross_loss == 0 and gross_profit > 0),
        "max_drawdown_quote": max_drawdown,
        "distinct_bases": len(per_base),
        "top_base_positive_contribution": concentration,
        "per_base_net_pnl_quote": dict(sorted(per_base.items())),
    }


def _pf(metrics: dict[str, Any]) -> float:
    if metrics["profit_factor_infinite"]:
        return math.inf
    return float(metrics["profit_factor"] or 0.0)


def _validate(trades: list[dict[str, Any]], plan: dict[str, Any], min_cycle: int, max_cycle: int) -> dict[str, Any]:
    config = plan["validation"]
    boundary = min_cycle + (max_cycle - min_cycle) * float(config["chronological_train_fraction"])
    train = [row for row in trades if int(row["signal_cycle"]) < boundary]
    oos = [row for row in trades if int(row["signal_cycle"]) >= boundary]
    all_metrics = _metrics(trades, "normal_net_pnl_bps")
    train_metrics = _metrics(train, "normal_net_pnl_bps")
    oos_metrics = _metrics(oos, "normal_net_pnl_bps")
    stress_oos = _metrics(oos, "stress_net_pnl_bps")
    folds = int(config["walk_forward_folds"])
    span = max(max_cycle - min_cycle, 1)
    fold_rows = []
    eligible_folds = positive_folds = 0
    for index in range(folds):
        start = min_cycle + span * index / folds
        end = min_cycle + span * (index + 1) / folds
        selected = [row for row in trades if int(row["signal_cycle"]) >= start and (int(row["signal_cycle"]) < end or index == folds - 1)]
        metrics = _metrics(selected, "normal_net_pnl_bps")
        eligible = metrics["trades"] >= 5
        positive = eligible and metrics["expectancy_bps"] is not None and float(metrics["expectancy_bps"]) > 0
        eligible_folds += int(eligible)
        positive_folds += int(positive)
        fold_rows.append({"fold": index + 1, "eligible": eligible, "positive": positive, "metrics": metrics})
    positive_ratio = positive_folds / eligible_folds if eligible_folds else 0.0
    gates = {
        "sample_size": len(trades) >= int(config["min_total_trades"]),
        "oos_sample_size": len(oos) >= int(config["min_oos_trades"]),
        "all_expectancy": all_metrics["expectancy_bps"] is not None and float(all_metrics["expectancy_bps"]) > 0,
        "oos_expectancy": oos_metrics["expectancy_bps"] is not None and float(oos_metrics["expectancy_bps"]) > float(config["min_oos_expectancy_bps"]),
        "oos_profit_factor": _pf(oos_metrics) >= float(config["min_oos_profit_factor"]),
        "oos_market_diversity": oos_metrics["distinct_bases"] >= int(config["min_distinct_oos_bases"]),
        "concentration": float(oos_metrics["top_base_positive_contribution"]) <= float(config["max_top_base_positive_contribution"]),
        "walk_forward": positive_ratio >= float(config["min_positive_fold_ratio"]),
        "stress_expectancy": stress_oos["expectancy_bps"] is not None and float(stress_oos["expectancy_bps"]) >= float(config["min_stress_expectancy_bps"]),
        "drawdown": float(all_metrics["max_drawdown_quote"]) <= float(config["max_drawdown_quote"]),
    }
    return {
        "split_boundary_cycle": boundary,
        "all": all_metrics,
        "train": train_metrics,
        "oos": oos_metrics,
        "stress_oos": stress_oos,
        "walk_forward": {"folds": fold_rows, "eligible_folds": eligible_folds, "positive_folds": positive_folds, "positive_fold_ratio": positive_ratio},
        "gates": gates,
        "all_gates_passed": all(gates.values()),
    }


def analyze(plan_path: str | Path, manifest_path: str | Path, *, expected_plan_sha256: str | None = None) -> dict[str, Any]:
    plan_file = Path(plan_path)
    manifest_file = Path(manifest_path)
    plan_hash = _sha(plan_file)
    if expected_plan_sha256 and plan_hash.lower() != expected_plan_sha256.lower():
        raise ValueError("plan sha256 mismatch")
    plan = _load(plan_file)
    manifest = _load(manifest_file)
    if plan.get("schema") != "spot_pit_event_forward_plan_v1" or manifest.get("schema") != "spot_pit_event_collector_manifest_v1":
        raise ValueError("plan/collector manifest schema mismatch")
    if str(manifest.get("plan_sha256", "")).lower() != plan_hash.lower():
        raise ValueError("collector manifest plan hash mismatch")
    segments_dir = Path(str(manifest["segments_dir"]))
    cycles_path = Path(str(manifest["cycles_path"]))
    run_id = str(manifest.get("run_id") or "")
    if not run_id or not cycles_path.is_file():
        raise ValueError("collector manifest requires an existing cycles_path and run_id")
    signal = plan["fixed_signal"]
    economics = plan["economics"]
    early = plan["early_gates"]
    interval_sec = int(manifest["interval_sec"])
    lookback_cycles = max(1, int(signal["shock_lookback_min"]) * 60 // interval_sec)
    hold_cycles = max(1, int(signal["hold_min"]) * 60 // interval_sec)
    cooldown_cycles = max(1, int(signal["cooldown_min"]) * 60 // interval_sec)
    exit_grace_cycles = max(1, 300 // interval_sec)
    histories: dict[tuple[str, str], deque[tuple[int, float]]] = defaultdict(lambda: deque(maxlen=lookback_cycles + 1))
    last_signal: dict[str, int] = {}
    pending: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    filter_counts: dict[str, int] = defaultdict(int)
    signals: list[dict[str, Any]] = []
    min_cycle = 0
    max_cycle = 0
    cycle_quality: list[dict[str, Any]] = []

    for cycle, rows in _cycle_groups(segments_dir, cycles_path, run_id):
        min_cycle = cycle if min_cycle == 0 else min(min_cycle, cycle)
        max_cycle = max(max_cycle, cycle)
        by_venue = _venue_observations(rows)
        mexc_bases = {base for (base, exchange) in by_venue if exchange == "mexc"}
        gate_bases = {base for (base, exchange) in by_venue if exchange == "gateio"}
        two_venue_bases = mexc_bases & gate_bases
        quality_valid = (
            len(mexc_bases) >= int(early["min_bases_per_venue"])
            and len(gate_bases) >= int(early["min_bases_per_venue"])
            and len(two_venue_bases) >= int(early["min_two_venue_bases"])
        )
        cycle_quality.append(
            {
                "cycle": cycle,
                "mexc_bases": len(mexc_bases),
                "gateio_bases": len(gate_bases),
                "two_venue_bases": len(two_venue_bases),
                "valid": quality_valid,
            }
        )

        still_open: list[dict[str, Any]] = []
        for position in positions:
            observation = by_venue.get((str(position["base"]), str(position["exchange"])))
            if cycle < int(position["exit_due_cycle"]):
                still_open.append(position)
                continue
            if observation and cycle <= int(position["exit_deadline_cycle"]):
                gross = (float(observation["bid"]) / float(position["entry_price"]) - 1.0) * 10000.0
                trades.append(dict(position) | {"exit_cycle": cycle, "exit_price": float(observation["bid"]), "exit_reason": "fixed_hold_bid", "gross_pnl_bps": gross, "normal_net_pnl_bps": gross - float(economics["normal_total_cost_bps"]), "stress_net_pnl_bps": gross - float(economics["stress_total_cost_bps"])})
            elif cycle > int(position["exit_deadline_cycle"]):
                gross = -10000.0
                trades.append(dict(position) | {"exit_cycle": cycle, "exit_price": None, "exit_reason": "no_exit_within_grace_total_loss_penalty", "gross_pnl_bps": gross, "normal_net_pnl_bps": gross - float(economics["normal_total_cost_bps"]), "stress_net_pnl_bps": gross - float(economics["stress_total_cost_bps"])})
            else:
                still_open.append(position)
        positions = still_open

        next_pending: list[dict[str, Any]] = []
        for item in pending:
            if cycle != int(item["entry_cycle"]):
                filter_counts["missed_entry_cycle"] += 1
                continue
            observation = by_venue.get((str(item["base"]), str(item["signal_exchange"])))
            if not observation or float(observation["spread_bps"]) > float(signal["max_spread_bps"]):
                filter_counts["missed_entry_quote"] += 1
                continue
            position = dict(item) | {
                "trade_id": f"{item['base']}-{item['signal_cycle']}",
                "exchange": item["signal_exchange"],
                "entry_price": float(observation["ask"]),
                "exit_due_cycle": cycle + hold_cycles,
                "exit_deadline_cycle": cycle + hold_cycles + exit_grace_cycles,
                "notional_quote": float(economics["notional_quote"]),
            }
            positions.append(position)
        pending = next_pending

        venue_returns: dict[tuple[str, str], float] = {}
        venue_rolling_lows: dict[tuple[str, str], float] = {}
        for key, observation in by_venue.items():
            history = histories[key]
            if history and history[-1][0] != cycle - 1:
                history.clear()
            history.append((cycle, float(observation["mid"])))
            if len(history) < lookback_cycles + 1 or history[0][0] != cycle - lookback_cycles:
                continue
            venue_returns[key] = (history[-1][1] / history[0][1] - 1.0) * 10000.0
            venue_rolling_lows[key] = min(value for _, value in history)

        # A base may trade on both venues, but its lookback must never splice
        # prices from different exchanges. Choose the execution venue only
        # after each venue-specific return is complete and contiguous.
        return_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for key, base_return in venue_returns.items():
            base, exchange = key
            observation = by_venue[key]
            return_candidates[base].append(
                {
                    "observation": observation,
                    "return_bps": base_return,
                    "rolling_low": venue_rolling_lows[key],
                    "exchange": exchange,
                }
            )
        selected_returns = {
            base: min(values, key=lambda row: (float(row["observation"]["spread_bps"]), str(row["exchange"])))
            for base, values in return_candidates.items()
        }
        returns = {base: float(item["return_bps"]) for base, item in selected_returns.items()}

        candidates: list[dict[str, Any]] = []
        if not quality_valid:
            filter_counts["invalid_quality_cycles"] += 1
        for base, base_return in returns.items():
            filter_counts["return_observations"] += 1
            if not quality_valid:
                continue
            peers = [value for peer, value in returns.items() if peer != base]
            if len(peers) < int(signal["min_peer_count"]):
                filter_counts["peer_count"] += 1
                continue
            peer_median = statistics.median(peers)
            residual = base_return - peer_median
            selected = selected_returns[base]
            observation = selected["observation"]
            reclaim = (float(observation["mid"]) / float(selected["rolling_low"]) - 1.0) * 10000.0
            if base_return > float(signal["base_return_max_bps"]):
                filter_counts["base_return"] += 1
                continue
            if residual > float(signal["residual_vs_cross_sectional_median_max_bps"]):
                filter_counts["residual"] += 1
                continue
            if reclaim < float(signal["reclaim_from_rolling_low_min_bps"]):
                filter_counts["reclaim"] += 1
                continue
            if float(observation["spread_bps"]) > float(signal["max_spread_bps"]):
                filter_counts["spread"] += 1
                continue
            if float(observation["quote_volume_24h"]) < float(signal["min_quote_volume_24h"]):
                filter_counts["quote_volume"] += 1
                continue
            if cycle - last_signal.get(base, -10**12) < cooldown_cycles:
                filter_counts["cooldown"] += 1
                continue
            candidates.append({"base": base, "signal_cycle": cycle, "entry_cycle": cycle + 1, "signal_exchange": observation["exchange"], "base_return_bps": base_return, "peer_median_return_bps": peer_median, "residual_bps": residual, "reclaim_bps": reclaim, "signal_spread_bps": float(observation["spread_bps"]), "quote_volume_24h": float(observation["quote_volume_24h"])})

        candidates.sort(key=lambda row: (float(row["residual_bps"]), str(row["base"])))
        occupied = len(positions) + len(pending)
        for candidate in candidates:
            if occupied >= int(signal["max_concurrent_positions"]):
                filter_counts["max_concurrent_positions"] += 1
                continue
            signals.append(candidate)
            pending.append(candidate)
            last_signal[str(candidate["base"])] = cycle
            occupied += 1
            filter_counts["fixed_signals"] += 1

    elapsed_hours = float(manifest.get("elapsed_active_sec") or 0.0) / 3600.0
    distinct_signal_bases = len({str(row["base"]) for row in signals})
    valid_cycle_count = sum(int(row["valid"]) for row in cycle_quality)
    valid_cycle_ratio = valid_cycle_count / len(cycle_quality) if cycle_quality else 0.0
    coverage_due = elapsed_hours >= float(early["coverage_gate_after_hours"])
    data_quality_pass = (
        bool(cycle_quality)
        and valid_cycle_ratio >= float(early["min_valid_cycle_ratio"])
    )
    futility_due = elapsed_hours >= float(early["futility_gate_after_hours"])
    futility_threshold_pass = len(signals) >= int(early["min_fixed_signals_by_48h"]) and distinct_signal_bases >= int(early["min_signal_bases_by_48h"])
    futility_pass = bool(data_quality_pass and futility_threshold_pass)
    validation = _validate(trades, plan, min_cycle, max_cycle) if min_cycle else _validate([], plan, 0, 1)
    if not bool(manifest.get("final")):
        if coverage_due and not data_quality_pass:
            decision = "SPOT_PIT_EVENT_CHECKPOINT_DATA_QUALITY_STOP_RECOMMENDED"
        elif futility_due and not futility_pass:
            decision = "SPOT_PIT_EVENT_CHECKPOINT_FUTILITY_STOP_RECOMMENDED"
        else:
            decision = "SPOT_PIT_EVENT_CHECKPOINT_CONTINUE"
    elif str(manifest.get("stop_reason") or "") == "futility_gate":
        decision = "SPOT_PIT_EVENT_FINAL_REJECTED_FUTILITY_GATE"
    elif not data_quality_pass:
        decision = "SPOT_PIT_EVENT_FINAL_REJECTED_DATA_QUALITY"
    elif not validation["all_gates_passed"]:
        decision = "SPOT_PIT_EVENT_FINAL_REJECTED_VALIDATION_GATES"
    else:
        decision = "SPOT_PIT_EVENT_FINAL_CANDIDATE_READY_FOR_INDEPENDENT_AUDIT_PLANONLY"
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "research_only": True,
        "strategy_accepted": False,
        "paper_forward_ready": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "plan_path": str(plan_file),
        "plan_sha256": plan_hash,
        "manifest_path": str(manifest_file),
        "manifest_final": bool(manifest.get("final")),
        "elapsed_hours": elapsed_hours,
        "cycle_range": {"min": min_cycle, "max": max_cycle},
        "summary": {"fixed_signals": len(signals), "distinct_signal_bases": distinct_signal_bases, "completed_trades": len(trades), "pending_entries": len(pending), "open_positions": len(positions)},
        "filters": dict(filter_counts),
        "data_quality": {
            "coverage_due": coverage_due,
            "passed": data_quality_pass,
            "valid_cycles": valid_cycle_count,
            "total_cycles": len(cycle_quality),
            "valid_cycle_ratio": valid_cycle_ratio,
            "min_valid_cycle_ratio": float(early["min_valid_cycle_ratio"]),
            "min_bases_per_venue": int(early["min_bases_per_venue"]),
            "min_two_venue_bases": int(early["min_two_venue_bases"]),
            "cycles": cycle_quality,
        },
        "futility_gate": {"due": futility_due, "passed": futility_pass, "threshold_passed": futility_threshold_pass, "eligible_data_quality": data_quality_pass, "min_signals": int(early["min_fixed_signals_by_48h"]), "min_bases": int(early["min_signal_bases_by_48h"]), "stop_recommended": bool(futility_due and data_quality_pass and not futility_threshold_pass)},
        "validation": validation,
        "signals": signals,
        "trades": trades,
        "next_step": (
            "Stop incomplete, fix data coverage, then visibly resume the same run_id."
            if decision.endswith("DATA_QUALITY_STOP_RECOMMENDED")
            else "Stop the collector cleanly and mark final=true with futility decision."
            if decision.endswith("FUTILITY_STOP_RECOMMENDED")
            else "Continue only under the sealed forward plan; do not tune thresholds."
        ),
    }


def run_analysis(plan_path: str | Path, manifest_path: str | Path, output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    report = analyze(plan_path, manifest_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(target)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Checkpoint/finality analyzer for spot PIT event forward data.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_analysis(args.plan, args.manifest, args.output, expected_plan_sha256=args.expected_plan_sha256)
    print(json.dumps({"output": args.output, "decision": report["decision"], "summary": report["summary"], "futility_gate": report["futility_gate"]}, ensure_ascii=False, indent=2))
    return 4 if report["decision"].endswith("FUTILITY_STOP_RECOMMENDED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
