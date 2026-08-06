from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import sys
import tempfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from cross_venue_dislocation import normalize_spot_symbol
from cross_venue_full_scan_audit import sample_file_fingerprint


PLAN_SCHEMA = "cross_venue_spot_lead_lag_plan_v1"
REPORT_SCHEMA = "cross_venue_spot_lead_lag_report_v1"
RECORD = struct.Struct("<5d")
TERMINAL_PHASES = {"closed", "missed_entry", "exit_liquidity_failure"}


@dataclass(frozen=True)
class Quote:
    exchange: str
    base: str
    ts: float
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid
        return ((self.ask - self.bid) / mid * 10000.0) if mid > 0 else math.inf

    @property
    def top_notional(self) -> float:
        return min(self.bid * self.bid_qty, self.ask * self.ask_qty)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _require_number(payload: dict[str, Any], name: str, *, positive: bool = False) -> float:
    if name not in payload:
        raise ValueError(f"missing plan field: {name}")
    value = float(payload[name])
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"invalid plan field {name}: {payload[name]!r}")
    return value


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"plan schema mismatch: {plan.get('schema')!r}")
    if plan.get("fixed_parameters_no_grid") is not True:
        raise ValueError("lead/lag plan must set fixed_parameters_no_grid=true")
    if plan.get("research_only") is not True or plan.get("strategy_accepted") is not False:
        raise ValueError("lead/lag plan must remain research-only and unaccepted")
    signal = plan.get("signal")
    execution = plan.get("execution")
    validation = plan.get("validation")
    if not all(isinstance(value, dict) for value in (signal, execution, validation)):
        raise ValueError("plan signal/execution/validation sections are required")
    if signal.get("direction") != "long_only_no_margin":
        raise ValueError("only long_only_no_margin is supported")
    if set(signal.get("supported_exchanges") or ()) != {"gateio", "mexc"}:
        raise ValueError("supported_exchanges must be exactly gateio and mexc")
    for name in (
        "lookback_sec",
        "leader_min_return_bps",
        "lagger_abs_max_return_bps",
        "min_return_gap_bps",
        "max_quote_age_sec",
        "max_spread_bps",
        "min_top_notional_quote",
        "cooldown_sec",
    ):
        _require_number(signal, name, positive=True)
    for name in (
        "baseline_latency_sec",
        "stress_latency_sec",
        "max_entry_wait_sec",
        "hold_sec",
        "exit_grace_sec",
        "round_trip_fee_bps",
        "slippage_bps",
        "operational_buffer_bps",
        "fixed_total_cost_bps",
        "stress_fee_multiplier",
        "stress_slippage_multiplier",
        "stress_total_cost_bps",
        "exit_liquidity_failure_penalty_bps",
    ):
        _require_number(execution, name, positive=True)
    fixed_cost = (
        float(execution["round_trip_fee_bps"])
        + float(execution["slippage_bps"])
        + float(execution["operational_buffer_bps"])
    )
    stress_cost = (
        float(execution["round_trip_fee_bps"]) * float(execution["stress_fee_multiplier"])
        + float(execution["slippage_bps"]) * float(execution["stress_slippage_multiplier"])
        + float(execution["operational_buffer_bps"])
    )
    if not math.isclose(fixed_cost, float(execution["fixed_total_cost_bps"]), abs_tol=1e-9):
        raise ValueError("fixed_total_cost_bps does not equal its components")
    if not math.isclose(stress_cost, float(execution["stress_total_cost_bps"]), abs_tol=1e-9):
        raise ValueError("stress_total_cost_bps does not equal its components")
    train_fraction = _require_number(validation, "train_fraction", positive=True)
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    for name in (
        "walk_forward_folds",
        "min_total_trades",
        "min_oos_trades",
        "min_distinct_bases",
        "min_trades_per_fold",
    ):
        if int(validation.get(name, 0)) <= 0:
            raise ValueError(f"invalid plan field validation.{name}")


def load_plan(path: str | Path, expected_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    plan_path = Path(path)
    plan_hash = _sha256(plan_path)
    if expected_sha256 and plan_hash.lower() != expected_sha256.lower():
        raise ValueError(f"plan sha256 mismatch: expected={expected_sha256}, observed={plan_hash}")
    plan = _load_json(plan_path)
    validate_plan(plan)
    return plan, plan_hash


def _quote_from_row(row: dict[str, Any], exchange: str, base: str) -> Quote | None:
    try:
        ts = float(row.get("recv_ts") if row.get("recv_ts") is not None else row["exchange_ts"])
        bid = float(row["bid_price"])
        bid_qty = float(row["bid_qty"])
        ask = float(row["ask_price"])
        ask_qty = float(row["ask_qty"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (ts, bid, bid_qty, ask, ask_qty)):
        return None
    if bid <= 0 or ask <= 0 or ask < bid or bid_qty < 0 or ask_qty < 0:
        return None
    return Quote(exchange, base, ts, bid, bid_qty, ask, ask_qty)


def _partition_bbo(
    source: Path,
    partition_dir: Path,
    *,
    quote_asset: str,
    supported_exchanges: set[str],
    max_rows: int,
    progress_every_rows: int,
) -> dict[str, Any]:
    handles: dict[tuple[str, str], BinaryIO] = {}
    paths: dict[tuple[str, str], Path] = {}
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    rows_read = 0
    bbo_rows = 0
    partitioned_rows = 0
    parse_errors = 0
    invalid_bbo_rows = 0
    non_spot_bbo_rows = 0
    global_out_of_order = 0
    max_global_backstep_sec = 0.0
    last_global_ts: float | None = None
    min_ts: float | None = None
    max_ts: float | None = None
    truncated_by_max_rows = False

    try:
        with source.open("r", encoding="utf-8") as input_handle:
            for line in input_handle:
                if max_rows and rows_read >= max_rows:
                    truncated_by_max_rows = True
                    break
                rows_read += 1
                if progress_every_rows and rows_read % progress_every_rows == 0:
                    print(
                        json.dumps(
                            {
                                "progress": "cross_venue_spot_lead_lag_partition",
                                "rows_read": rows_read,
                                "bbo_rows": bbo_rows,
                                "partitioned_rows": partitioned_rows,
                                "markets": len(stats),
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if row.get("event_kind") != "bbo":
                    continue
                bbo_rows += 1
                exchange = str(row.get("exchange") or "").strip().lower()
                if exchange not in supported_exchanges:
                    continue
                channel = str(row.get("channel") or "").lower()
                if "spot" not in channel:
                    non_spot_bbo_rows += 1
                    continue
                parsed = normalize_spot_symbol(str(row.get("symbol") or ""), quote_asset)
                if parsed is None:
                    continue
                base, _ = parsed
                quote = _quote_from_row(row, exchange, base)
                if quote is None:
                    invalid_bbo_rows += 1
                    continue

                if last_global_ts is not None and quote.ts < last_global_ts:
                    global_out_of_order += 1
                    max_global_backstep_sec = max(max_global_backstep_sec, last_global_ts - quote.ts)
                last_global_ts = quote.ts
                min_ts = quote.ts if min_ts is None else min(min_ts, quote.ts)
                max_ts = quote.ts if max_ts is None else max(max_ts, quote.ts)

                key = (exchange, base)
                if key not in handles:
                    path = partition_dir / f"{exchange}__{base}.bbo.bin"
                    handles[key] = path.open("wb", buffering=1024 * 1024)
                    paths[key] = path
                    stats[key] = {
                        "exchange": exchange,
                        "base": base,
                        "rows": 0,
                        "first_ts": None,
                        "last_ts": None,
                        "out_of_order": 0,
                        "max_backstep_sec": 0.0,
                    }
                market_stats = stats[key]
                previous_ts = market_stats["last_ts"]
                if previous_ts is not None and quote.ts < previous_ts:
                    market_stats["out_of_order"] += 1
                    market_stats["max_backstep_sec"] = max(
                        float(market_stats["max_backstep_sec"]), previous_ts - quote.ts
                    )
                market_stats["rows"] += 1
                market_stats["first_ts"] = quote.ts if market_stats["first_ts"] is None else market_stats["first_ts"]
                market_stats["last_ts"] = quote.ts
                handles[key].write(RECORD.pack(quote.ts, quote.bid, quote.bid_qty, quote.ask, quote.ask_qty))
                partitioned_rows += 1
    finally:
        for handle in handles.values():
            handle.close()

    markets = []
    for key, market_stats in sorted(stats.items()):
        path = paths[key]
        markets.append(dict(market_stats) | {"path": str(path), "bytes": path.stat().st_size})
    # Only an observed extra source row proves truncation. A file containing
    # exactly max_rows rows is still a complete scan.
    scan_complete = not truncated_by_max_rows
    return {
        "rows_read": rows_read,
        "bbo_rows": bbo_rows,
        "partitioned_rows": partitioned_rows,
        "parse_errors": parse_errors,
        "invalid_bbo_rows": invalid_bbo_rows,
        "non_spot_bbo_rows": non_spot_bbo_rows,
        "global_out_of_order": global_out_of_order,
        "max_global_backstep_sec": max_global_backstep_sec,
        "min_ts": min_ts,
        "max_ts": max_ts,
        "scan_complete": scan_complete,
        "truncated_by_max_rows": truncated_by_max_rows,
        "markets": markets,
    }


def _iter_quotes(path: Path, exchange: str, base: str) -> Iterator[Quote]:
    with path.open("rb") as handle:
        while True:
            data = handle.read(RECORD.size)
            if not data:
                return
            if len(data) != RECORD.size:
                raise ValueError(f"truncated BBO partition record: {path}")
            ts, bid, bid_qty, ask, ask_qty = RECORD.unpack(data)
            yield Quote(exchange, base, ts, bid, bid_qty, ask, ask_qty)


def _merge_pair(left: Iterator[Quote], right: Iterator[Quote]) -> Iterator[Quote]:
    left_value = next(left, None)
    right_value = next(right, None)
    while left_value is not None or right_value is not None:
        if right_value is None or (left_value is not None and left_value.ts <= right_value.ts):
            yield left_value  # type: ignore[misc]
            left_value = next(left, None)
        else:
            yield right_value
            right_value = next(right, None)


def _quality_ok(quote: Quote, signal: dict[str, Any]) -> bool:
    return (
        quote.spread_bps <= float(signal["max_spread_bps"])
        and quote.top_notional >= float(signal["min_top_notional_quote"])
    )


def _history_return(history: deque[Quote], now_ts: float, lookback_sec: float) -> float | None:
    target = now_ts - lookback_sec
    while len(history) >= 2 and history[1].ts <= target:
        history.popleft()
    if not history or history[0].ts > target or history[0].mid <= 0:
        return None
    return (history[-1].mid / history[0].mid - 1.0) * 10000.0


def _new_variant(name: str, latency_sec: float, signal_ts: float, max_wait_sec: float) -> dict[str, Any]:
    eligible_at = signal_ts + latency_sec
    return {
        "name": name,
        "phase": "pending",
        "eligible_at": eligible_at,
        "entry_deadline": eligible_at + max_wait_sec,
        "entry_ts": None,
        "entry_price": None,
        "entry_capacity_quote": None,
        "exit_ts": None,
        "exit_price": None,
        "exit_capacity_quote": None,
        "gross_pnl_bps": None,
        "net_pnl_bps": None,
        "reason": None,
    }


def _new_event(
    event_id: str,
    base: str,
    signal_ts: float,
    leader: Quote,
    lagger: Quote,
    leader_return_bps: float,
    lagger_return_bps: float,
    plan: dict[str, Any],
) -> dict[str, Any]:
    execution = plan["execution"]
    return {
        "event_id": event_id,
        "base": base,
        "signal_ts": signal_ts,
        "leader_exchange": leader.exchange,
        "lagger_exchange": lagger.exchange,
        "leader_return_bps": leader_return_bps,
        "lagger_return_bps": lagger_return_bps,
        "return_gap_bps": leader_return_bps - lagger_return_bps,
        "leader_mid": leader.mid,
        "lagger_mid": lagger.mid,
        "leader_spread_bps": leader.spread_bps,
        "lagger_spread_bps": lagger.spread_bps,
        "leader_top_notional": leader.top_notional,
        "lagger_top_notional": lagger.top_notional,
        "baseline": _new_variant(
            "baseline",
            float(execution["baseline_latency_sec"]),
            signal_ts,
            float(execution["max_entry_wait_sec"]),
        ),
        "stress": _new_variant(
            "stress",
            float(execution["stress_latency_sec"]),
            signal_ts,
            float(execution["max_entry_wait_sec"]),
        ),
    }


def _advance_variant(
    variant: dict[str, Any],
    quote: Quote,
    *,
    signal: dict[str, Any],
    execution: dict[str, Any],
) -> None:
    if variant["phase"] in TERMINAL_PHASES:
        return
    min_notional = float(signal["min_top_notional_quote"])
    if variant["phase"] == "pending":
        if quote.ts < float(variant["eligible_at"]):
            return
        if quote.ts > float(variant["entry_deadline"]):
            variant["phase"] = "missed_entry"
            variant["reason"] = "no_executable_quote_within_entry_window"
            return
        if not _quality_ok(quote, signal):
            return
        variant["phase"] = "entered"
        variant["entry_ts"] = quote.ts
        variant["entry_price"] = quote.ask
        variant["entry_capacity_quote"] = quote.ask * quote.ask_qty
        return

    due = float(variant["entry_ts"]) + float(execution["hold_sec"])
    if quote.ts < due:
        return
    deadline = due + float(execution["exit_grace_sec"])
    exit_capacity = quote.bid * quote.bid_qty
    if quote.ts <= deadline and exit_capacity >= min_notional:
        gross = (quote.bid / float(variant["entry_price"]) - 1.0) * 10000.0
        cost = (
            float(execution["fixed_total_cost_bps"])
            if variant["name"] == "baseline"
            else float(execution["stress_total_cost_bps"])
        )
        variant.update(
            {
                "phase": "closed",
                "exit_ts": quote.ts,
                "exit_price": quote.bid,
                "exit_capacity_quote": exit_capacity,
                "gross_pnl_bps": gross,
                "net_pnl_bps": gross - cost,
                "reason": "fixed_time_exit",
            }
        )
    elif quote.ts > deadline:
        penalty = float(execution["exit_liquidity_failure_penalty_bps"])
        cost = (
            float(execution["fixed_total_cost_bps"])
            if variant["name"] == "baseline"
            else float(execution["stress_total_cost_bps"])
        )
        variant.update(
            {
                "phase": "exit_liquidity_failure",
                "exit_ts": quote.ts,
                "exit_price": quote.bid,
                "exit_capacity_quote": exit_capacity,
                "gross_pnl_bps": -penalty,
                "net_pnl_bps": -penalty - cost,
                "reason": "insufficient_exit_liquidity_within_grace_penalty",
            }
        )


def _event_terminal(event: dict[str, Any]) -> bool:
    return all(event[name]["phase"] in TERMINAL_PHASES for name in ("baseline", "stress"))


def _trade_from_event(event: dict[str, Any], variant_name: str) -> dict[str, Any] | None:
    variant = event[variant_name]
    if variant["phase"] not in {"closed", "exit_liquidity_failure"}:
        return None
    return {
        "event_id": event["event_id"],
        "variant": variant_name,
        "base": event["base"],
        "signal_ts": event["signal_ts"],
        "leader_exchange": event["leader_exchange"],
        "lagger_exchange": event["lagger_exchange"],
        "leader_return_bps": event["leader_return_bps"],
        "lagger_return_bps": event["lagger_return_bps"],
        "return_gap_bps": event["return_gap_bps"],
        "entry_ts": variant["entry_ts"],
        "entry_price": variant["entry_price"],
        "entry_capacity_quote": variant["entry_capacity_quote"],
        "exit_ts": variant["exit_ts"],
        "exit_price": variant["exit_price"],
        "exit_capacity_quote": variant["exit_capacity_quote"],
        "gross_pnl_bps": variant["gross_pnl_bps"],
        "net_pnl_bps": variant["net_pnl_bps"],
        "exit_reason": variant["reason"],
    }


def _analyze_base(
    base: str,
    paths: dict[str, Path],
    plan: dict[str, Any],
) -> dict[str, Any]:
    signal = plan["signal"]
    execution = plan["execution"]
    exchanges = sorted(paths)
    histories = {exchange: deque() for exchange in exchanges}
    latest: dict[str, Quote] = {}
    active: dict[str, Any] | None = None
    last_signal_ts = -math.inf
    signal_count = 0
    incomplete_events = 0
    events: list[dict[str, Any]] = []
    baseline_trades: list[dict[str, Any]] = []
    stress_trades: list[dict[str, Any]] = []
    lookback = float(signal["lookback_sec"])

    left = _iter_quotes(paths[exchanges[0]], exchanges[0], base)
    right = _iter_quotes(paths[exchanges[1]], exchanges[1], base)
    for quote in _merge_pair(left, right):
        if active is not None and quote.exchange == active["lagger_exchange"]:
            _advance_variant(active["baseline"], quote, signal=signal, execution=execution)
            _advance_variant(active["stress"], quote, signal=signal, execution=execution)
            if _event_terminal(active):
                events.append(active)
                baseline = _trade_from_event(active, "baseline")
                stress = _trade_from_event(active, "stress")
                if baseline is not None:
                    baseline_trades.append(baseline)
                if stress is not None:
                    stress_trades.append(stress)
                active = None

        history = histories[quote.exchange]
        history.append(quote)
        latest[quote.exchange] = quote
        target = quote.ts - lookback
        while len(history) >= 2 and history[1].ts <= target:
            history.popleft()

        if active is not None or quote.ts - last_signal_ts < float(signal["cooldown_sec"]):
            continue
        if len(latest) != 2:
            continue
        now_ts = quote.ts
        if any(now_ts - latest[venue].ts > float(signal["max_quote_age_sec"]) for venue in exchanges):
            continue
        returns = {
            venue: _history_return(histories[venue], now_ts, lookback)
            for venue in exchanges
        }
        if any(value is None for value in returns.values()):
            continue
        selected: tuple[str, str] | None = None
        for leader_exchange in exchanges:
            lagger_exchange = exchanges[1] if leader_exchange == exchanges[0] else exchanges[0]
            leader_return = float(returns[leader_exchange])  # type: ignore[arg-type]
            lagger_return = float(returns[lagger_exchange])  # type: ignore[arg-type]
            if (
                leader_return >= float(signal["leader_min_return_bps"])
                and abs(lagger_return) <= float(signal["lagger_abs_max_return_bps"])
                and leader_return - lagger_return >= float(signal["min_return_gap_bps"])
            ):
                selected = (leader_exchange, lagger_exchange)
                break
        if selected is None:
            continue
        leader_exchange, lagger_exchange = selected
        leader = latest[leader_exchange]
        lagger = latest[lagger_exchange]
        if not _quality_ok(leader, signal) or not _quality_ok(lagger, signal):
            continue
        signal_count += 1
        last_signal_ts = now_ts
        active = _new_event(
            f"{base}-{signal_count:06d}",
            base,
            now_ts,
            leader,
            lagger,
            float(returns[leader_exchange]),  # type: ignore[arg-type]
            float(returns[lagger_exchange]),  # type: ignore[arg-type]
            plan,
        )

    if active is not None:
        incomplete_events += 1
    return {
        "base": base,
        "signals": signal_count,
        "completed_events": len(events),
        "incomplete_events": incomplete_events,
        "baseline_missed_entries": sum(1 for event in events if event["baseline"]["phase"] == "missed_entry"),
        "stress_missed_entries": sum(1 for event in events if event["stress"]["phase"] == "missed_entry"),
        "baseline_trades": baseline_trades,
        "stress_trades": stress_trades,
    }


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda item: (float(item["signal_ts"]), str(item["event_id"])))
    net_values = [float(item["net_pnl_bps"]) for item in ordered]
    gross_values = [float(item["gross_pnl_bps"]) for item in ordered]
    positives = [value for value in net_values if value > 0]
    negatives = [value for value in net_values if value < 0]
    gross_profit = sum(positives)
    gross_loss = abs(sum(negatives))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    per_base: dict[str, float] = {}
    positive_by_base: dict[str, float] = {}
    for trade in ordered:
        base = str(trade["base"])
        value = float(trade["net_pnl_bps"])
        per_base[base] = per_base.get(base, 0.0) + value
        if value > 0:
            positive_by_base[base] = positive_by_base.get(base, 0.0) + value
    total_positive = sum(positive_by_base.values())
    top_base_positive_contribution = (
        max(positive_by_base.values()) / total_positive if total_positive > 0 else 1.0
    )
    return {
        "trades": len(ordered),
        "wins": len(positives),
        "losses": len(negatives),
        "breakeven": len(net_values) - len(positives) - len(negatives),
        "win_rate": (len(positives) / len(ordered)) if ordered else 0.0,
        "gross_pnl_bps": sum(gross_values),
        "net_pnl_bps": sum(net_values),
        "expectancy_bps": (sum(net_values) / len(net_values)) if net_values else None,
        "profit_factor": profit_factor,
        "profit_factor_infinite": bool(gross_loss == 0 and gross_profit > 0),
        "max_drawdown_bps": max_drawdown,
        "distinct_bases": len(per_base),
        "top_base_positive_contribution": top_base_positive_contribution,
        "per_base_net_pnl_bps": dict(sorted(per_base.items())),
    }


def _profit_factor_value(metrics: dict[str, Any]) -> float:
    if metrics["profit_factor_infinite"]:
        return math.inf
    if metrics["profit_factor"] is None:
        return 0.0
    return float(metrics["profit_factor"])


def _validation_report(
    baseline_trades: list[dict[str, Any]],
    stress_trades: list[dict[str, Any]],
    min_ts: float,
    max_ts: float,
    plan: dict[str, Any],
) -> dict[str, Any]:
    validation = plan["validation"]
    boundary = min_ts + (max_ts - min_ts) * float(validation["train_fraction"])
    train = [trade for trade in baseline_trades if float(trade["signal_ts"]) < boundary]
    oos = [trade for trade in baseline_trades if float(trade["signal_ts"]) >= boundary]
    train_metrics = _metrics(train)
    oos_metrics = _metrics(oos)

    folds = int(validation["walk_forward_folds"])
    span = max(max_ts - min_ts, 1e-9)
    fold_rows = []
    eligible_folds = 0
    positive_folds = 0
    for index in range(folds):
        start = min_ts + span * index / folds
        end = min_ts + span * (index + 1) / folds
        fold_trades = [
            trade
            for trade in baseline_trades
            if float(trade["signal_ts"]) >= start
            and (float(trade["signal_ts"]) < end or index == folds - 1)
        ]
        metrics = _metrics(fold_trades)
        eligible = metrics["trades"] >= int(validation["min_trades_per_fold"])
        positive = eligible and metrics["expectancy_bps"] is not None and float(metrics["expectancy_bps"]) > 0
        eligible_folds += int(eligible)
        positive_folds += int(positive)
        fold_rows.append(
            {
                "fold": index + 1,
                "start_ts": start,
                "end_ts": end,
                "eligible": eligible,
                "positive": positive,
                "metrics": metrics,
            }
        )
    positive_fold_ratio = positive_folds / eligible_folds if eligible_folds else 0.0

    oos_ids = {str(trade["event_id"]) for trade in oos}
    stress_oos = [trade for trade in stress_trades if str(trade["event_id"]) in oos_ids]
    stress_metrics = _metrics(stress_oos)
    stress_coverage = len(stress_oos) / len(oos) if oos else 0.0

    gates = {
        "sample_size": len(baseline_trades) >= int(validation["min_total_trades"]),
        "oos_sample_size": len(oos) >= int(validation["min_oos_trades"]),
        "oos_expectancy": oos_metrics["expectancy_bps"] is not None
        and float(oos_metrics["expectancy_bps"]) > float(validation["min_oos_expectancy_bps"]),
        "oos_profit_factor": _profit_factor_value(oos_metrics) >= float(validation["min_oos_profit_factor"]),
        "market_diversity": oos_metrics["distinct_bases"] >= int(validation["min_distinct_bases"]),
        "concentration": float(oos_metrics["top_base_positive_contribution"])
        <= float(validation["max_top_base_positive_contribution"]),
        "walk_forward_coverage": eligible_folds >= math.ceil(folds * float(validation["min_positive_fold_ratio"])),
        "walk_forward": positive_fold_ratio >= float(validation["min_positive_fold_ratio"]),
        "stress_execution_coverage": stress_coverage >= float(validation["min_stress_execution_coverage"]),
        "stress_expectancy": stress_metrics["expectancy_bps"] is not None
        and float(stress_metrics["expectancy_bps"]) >= float(validation["min_stress_expectancy_bps"]),
    }
    return {
        "split_boundary_ts": boundary,
        "train": train_metrics,
        "oos": oos_metrics,
        "walk_forward": {
            "folds": fold_rows,
            "eligible_folds": eligible_folds,
            "positive_folds": positive_folds,
            "positive_fold_ratio": positive_fold_ratio,
        },
        "stress_oos": stress_metrics,
        "stress_execution_coverage": stress_coverage,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
    }


def _decision(scan_complete: bool, signals: int, validation: dict[str, Any]) -> tuple[str, list[str]]:
    if not scan_complete:
        return "CROSS_VENUE_SPOT_LEAD_LAG_SMOKE_TRUNCATED", ["scan_truncated_by_max_rows"]
    gates = validation["gates"]
    if signals == 0:
        return "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_NO_FIXED_SIGNALS", ["no_fixed_lead_lag_signals"]
    if not gates["sample_size"] or not gates["oos_sample_size"]:
        return "CROSS_VENUE_SPOT_LEAD_LAG_INCONCLUSIVE_INSUFFICIENT_SAMPLE", [
            name for name in ("sample_size", "oos_sample_size") if not gates[name]
        ]
    if not gates["oos_expectancy"] or not gates["oos_profit_factor"]:
        return "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_OOS_ECONOMICS", [
            name for name in ("oos_expectancy", "oos_profit_factor") if not gates[name]
        ]
    if not gates["market_diversity"] or not gates["concentration"]:
        return "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_CONCENTRATION", [
            name for name in ("market_diversity", "concentration") if not gates[name]
        ]
    if not gates["walk_forward_coverage"] or not gates["walk_forward"]:
        return "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_WALK_FORWARD", [
            name for name in ("walk_forward_coverage", "walk_forward") if not gates[name]
        ]
    if not gates["stress_execution_coverage"] or not gates["stress_expectancy"]:
        return "CROSS_VENUE_SPOT_LEAD_LAG_REJECTED_STRESS", [
            name for name in ("stress_execution_coverage", "stress_expectancy") if not gates[name]
        ]
    return "CROSS_VENUE_SPOT_LEAD_LAG_CANDIDATE_READY_FOR_INDEPENDENT_FORWARD_PLANONLY", [
        "research_candidate_not_strategy_acceptance"
    ]


def build_cross_venue_lead_lag_report(
    input_path: str | Path,
    plan_path: str | Path,
    *,
    expected_plan_sha256: str | None = None,
    max_rows: int = 0,
    progress_every_rows: int = 1_000_000,
    temp_parent: str | Path | None = None,
    keep_partitions: bool = False,
) -> dict[str, Any]:
    source = Path(input_path)
    if not source.is_file():
        raise FileNotFoundError(f"lead/lag source not found: {source}")
    plan_file = Path(plan_path)
    plan, plan_hash = load_plan(plan_file, expected_plan_sha256)
    planned_source = Path(str(plan["input_path"]))
    if source.resolve() != planned_source.resolve():
        raise ValueError(f"source path differs from sealed plan: plan={planned_source}, actual={source}")

    parent = Path(temp_parent) if temp_parent else source.parent
    parent.mkdir(parents=True, exist_ok=True)
    partition_dir = Path(tempfile.mkdtemp(prefix="lead_lag_partitions_", dir=parent))
    try:
        partition = _partition_bbo(
            source,
            partition_dir,
            quote_asset=str(plan["signal"]["quote"]),
            supported_exchanges=set(plan["signal"]["supported_exchanges"]),
            max_rows=max_rows,
            progress_every_rows=progress_every_rows,
        )
        market_stats = partition["markets"]
        if any(int(row["out_of_order"]) > 0 for row in market_stats):
            raise ValueError("per-market BBO partitions are out of order; lead/lag replay would be invalid")
        paths_by_base: dict[str, dict[str, Path]] = {}
        for row in market_stats:
            paths_by_base.setdefault(str(row["base"]), {})[str(row["exchange"])] = Path(str(row["path"]))
        matched = {base: paths for base, paths in paths_by_base.items() if set(paths) == {"gateio", "mexc"}}

        base_reports = []
        baseline_trades: list[dict[str, Any]] = []
        stress_trades: list[dict[str, Any]] = []
        for index, (base, paths) in enumerate(sorted(matched.items()), 1):
            print(
                json.dumps(
                    {
                        "progress": "cross_venue_spot_lead_lag_analyze",
                        "base": base,
                        "base_index": index,
                        "matched_bases": len(matched),
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
            base_report = _analyze_base(base, paths, plan)
            baseline_trades.extend(base_report.pop("baseline_trades"))
            stress_trades.extend(base_report.pop("stress_trades"))
            base_reports.append(base_report)

        min_ts = float(partition["min_ts"] or 0.0)
        max_ts = float(partition["max_ts"] or min_ts)
        validation = _validation_report(baseline_trades, stress_trades, min_ts, max_ts, plan)
        signals = sum(int(row["signals"]) for row in base_reports)
        decision, reasons = _decision(bool(partition["scan_complete"]), signals, validation)
        candidate = decision.endswith("CANDIDATE_READY_FOR_INDEPENDENT_FORWARD_PLANONLY")
        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": _utc_now(),
            "mode": "cross_venue_spot_lead_lag_fixed_research",
            "decision": decision,
            "decision_reasons": reasons,
            "branch": plan["branch"],
            "research_only": True,
            "strategy_accepted": False,
            "research_candidate": candidate,
            "paper_forward_ready": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
            "grid_search": False,
            "collect": False,
            "input_path": str(source),
            "source_fingerprint": sample_file_fingerprint(source),
            "plan_path": str(plan_file),
            "plan_sha256": plan_hash,
            "sealed_plan": plan,
            "partition": partition,
            "matched_bases": sorted(matched),
            "base_reports": base_reports,
            "summary": {
                "signals": signals,
                "completed_events": sum(int(row["completed_events"]) for row in base_reports),
                "incomplete_events": sum(int(row["incomplete_events"]) for row in base_reports),
                "baseline_trades": len(baseline_trades),
                "stress_trades": len(stress_trades),
                "scan_complete": bool(partition["scan_complete"]),
                "span_hours": (max_ts - min_ts) / 3600.0 if max_ts >= min_ts else 0.0,
            },
            "validation": validation,
            "baseline_trades": sorted(baseline_trades, key=lambda item: float(item["signal_ts"])),
            "stress_trades": sorted(stress_trades, key=lambda item: float(item["signal_ts"])),
            "next_step": (
                "Freeze this candidate and design an independent forward paper-readiness packet; do not tune the current sample."
                if candidate
                else "Reject or mark the branch inconclusive according to decision_reasons; do not grid-tune the current sample."
            ),
        }
        if keep_partitions:
            report["partition_directory"] = str(partition_dir)
            report["partition"]["partition_files_retained"] = True
        else:
            # Do not publish dead paths after the temporary files are removed.
            for row in report["partition"]["markets"]:
                row.pop("path", None)
            report["partition"]["partition_files_retained"] = False
        return report
    finally:
        if not keep_partitions and partition_dir.exists():
            shutil.rmtree(partition_dir)


def run_cross_venue_lead_lag(
    input_path: str | Path,
    plan_path: str | Path,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    report = build_cross_venue_lead_lag_report(input_path, plan_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(target)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fixed no-grid MEXC/Gate spot lead/lag replay on existing clean WS data.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--progress-every-rows", type=int, default=1_000_000)
    parser.add_argument("--temp-parent")
    parser.add_argument("--keep-partitions", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = run_cross_venue_lead_lag(
        args.input,
        args.plan,
        args.output,
        expected_plan_sha256=args.expected_plan_sha256,
        max_rows=args.max_rows,
        progress_every_rows=args.progress_every_rows,
        temp_parent=args.temp_parent,
        keep_partitions=args.keep_partitions,
    )
    print(
        json.dumps(
            {
                "output_path": report["output_path"],
                "decision": report["decision"],
                "summary": report["summary"],
                "gates": report["validation"]["gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
