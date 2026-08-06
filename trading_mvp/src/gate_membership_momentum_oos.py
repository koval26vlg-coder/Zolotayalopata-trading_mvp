from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from gate_historical_membership_history_plan import sha256_file, sha256_json
from gate_historical_membership_history_quality import (
    ACCEPTED_DECISION as QUALITY_ACCEPTED_DECISION,
    SCHEMA as QUALITY_SCHEMA,
    _quality_hash,
)
from gate_membership_momentum import (
    DAY_SEC,
    FrozenMomentumConfig,
    MarketSeries,
    RebalanceEvent,
    adjusted_event_funding,
    evaluate_rebalance,
    portfolio_metrics,
)
from gate_membership_momentum_train import (
    FEASIBLE_DECISION,
    PLAN_SCHEMA as TRAIN_PLAN_SCHEMA,
    RESULT_SCHEMA as TRAIN_RESULT_SCHEMA,
    TRAIN_MANIFEST_SCHEMA,
    _atomic_write_json,
    _deterministic_result_hash as train_result_hash,
    _load_markets,
    _manifest_hash,
    _read_json_object,
    _validate_hash,
    _validate_plan as validate_train_plan,
)


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_oos_plan_v1"
RESULT_SCHEMA = "trading_mvp_gate_membership_momentum_oos_evaluation_v1"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_OOS_PLAN_READY"
HISTORICAL_ACCEPT_DECISION = "GATE_MEMBERSHIP_MOMENTUM_HISTORICAL_ACCEPT_FOR_EXECUTION_PROBE"
OOS_REJECTED_DECISION = "GATE_MEMBERSHIP_MOMENTUM_OOS_REJECTED_NO_RETUNE"
OOS_INSUFFICIENT_DECISION = "GATE_MEMBERSHIP_MOMENTUM_OOS_INSUFFICIENT_DATA"
MAX_RUNTIME_SEC = 1_800
OOS_DAYS = 210
FOLD_COUNT = 5
FOLD_DAYS = 42
MIN_OOS_REBALANCES = 20
MIN_UNIQUE_ASSETS = 10
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 20_260_717


def oos_plan_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"schema", "generated_at_utc", "plan_hash"}
        }
    )


def _validate_oos_manifest(path: Path, expected_hash: str) -> dict[str, Any]:
    manifest = _read_json_object(path)
    stored_hash = str(manifest.get("artifact_hash") or "")
    if (
        manifest.get("schema") != TRAIN_MANIFEST_SCHEMA
        or manifest.get("stage") != "sealed_oos"
        or manifest.get("sealed") is not True
        or manifest.get("oos_paths_present") is not True
        or stored_hash != _manifest_hash(manifest)
        or stored_hash != expected_hash
    ):
        raise ValueError("OOS manifest is not a hash-valid sealed artifact")
    range_payload = manifest.get("range")
    if not isinstance(range_payload, Mapping):
        raise ValueError("OOS manifest range is missing")
    start_sec = int(range_payload.get("start_sec") or 0)
    end_sec = int(range_payload.get("end_sec") or 0)
    if (
        start_sec < 0
        or end_sec <= start_sec
        or start_sec % DAY_SEC
        or end_sec % DAY_SEC
        or end_sec - start_sec != OOS_DAYS * DAY_SEC
    ):
        raise ValueError("OOS manifest must contain exactly 210 UTC-aligned days")
    universe = manifest.get("universe")
    files = manifest.get("normalized_files")
    if not isinstance(universe, list) or len(universe) < 20:
        raise ValueError("OOS manifest executable universe is below 20 assets")
    if not isinstance(files, list) or not files:
        raise ValueError("OOS manifest normalized files are missing")
    root = path.parent.resolve()
    seen_symbols: set[str] = set()
    for raw in files:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid OOS file record")
        symbol = str(raw.get("symbol") or "")
        if not symbol or symbol in seen_symbols:
            raise ValueError("duplicate or missing OOS symbol")
        seen_symbols.add(symbol)
        for path_key, hash_key in (
            ("kline_path", "kline_sha256"),
            ("funding_path", "funding_sha256"),
        ):
            target = Path(str(raw.get(path_key) or "")).expanduser().resolve()
            if not target.is_file() or not target.is_relative_to(root):
                raise ValueError(f"OOS artifact escapes sealed root: {path_key}")
            if sha256_file(target) != _validate_hash(raw.get(hash_key), label=hash_key):
                raise ValueError(f"OOS artifact hash mismatch: {path_key}")
    return manifest


def _validate_train_result(
    path: Path,
    *,
    expected_hash: str,
    expected_train_plan_hash: str,
) -> dict[str, Any]:
    result = _read_json_object(path)
    stored_hash = str(result.get("deterministic_result_hash") or "")
    if (
        result.get("schema") != TRAIN_RESULT_SCHEMA
        or result.get("final") is not True
        or result.get("decision") != FEASIBLE_DECISION
        or result.get("oos_read") is not False
        or str(result.get("plan_hash") or "") != expected_train_plan_hash
        or stored_hash != train_result_hash(result)
        or stored_hash != expected_hash
    ):
        raise ValueError("train result is not a hash-valid FEASIBLE OOS authorization")
    audit = result.get("data_access_audit")
    if not isinstance(audit, Mapping) or audit.get("oos_files_opened") is not False:
        raise ValueError("train result data-access audit violates OOS embargo")
    return result


def _fold_contract(start_sec: int, end_sec: int) -> list[dict[str, int]]:
    if end_sec - start_sec != OOS_DAYS * DAY_SEC:
        raise ValueError("OOS range does not match frozen fold contract")
    folds = []
    for index in range(FOLD_COUNT):
        fold_start = start_sec + index * FOLD_DAYS * DAY_SEC
        fold_end = fold_start + FOLD_DAYS * DAY_SEC
        folds.append(
            {
                "fold": index + 1,
                "start_sec": fold_start,
                "end_sec": fold_end,
                "days": FOLD_DAYS,
            }
        )
    if folds[-1]["end_sec"] != end_sec:
        raise ValueError("OOS folds do not cover the sealed range")
    return folds


def build_oos_plan(
    *,
    quality_report_path: str | Path,
    expected_quality_hash: str,
    train_plan_path: str | Path,
    expected_train_plan_hash: str,
    train_result_path: str | Path,
    expected_train_result_hash: str,
    output_path: str | Path | None,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    quality_path = Path(quality_report_path).expanduser().resolve()
    quality = _read_json_object(quality_path)
    quality_hash = _validate_hash(expected_quality_hash, label="quality artifact hash")
    if (
        quality.get("schema") != QUALITY_SCHEMA
        or quality.get("final") is not True
        or quality.get("accepted") is not True
        or quality.get("decision") != QUALITY_ACCEPTED_DECISION
        or str(quality.get("artifact_hash") or "") != _quality_hash(quality)
        or str(quality.get("artifact_hash") or "") != quality_hash
    ):
        raise ValueError("history quality report is not a hash-valid accepted artifact")
    resolved_train_plan = Path(train_plan_path).expanduser().resolve()
    train_plan_hash_value = _validate_hash(expected_train_plan_hash, label="train plan hash")
    train_plan = validate_train_plan(resolved_train_plan, train_plan_hash_value)
    if train_plan.get("schema") != TRAIN_PLAN_SCHEMA:
        raise ValueError("unexpected train plan schema")
    resolved_train_result = Path(train_result_path).expanduser().resolve()
    train_result_hash_value = _validate_hash(expected_train_result_hash, label="train result hash")
    _validate_train_result(
        resolved_train_result,
        expected_hash=train_result_hash_value,
        expected_train_plan_hash=train_plan_hash_value,
    )
    oos_manifest_path = Path(str(quality.get("oos_manifest_path") or "")).expanduser().resolve()
    oos_manifest_hash = _validate_hash(quality.get("oos_commitment_hash"), label="OOS commitment hash")
    if oos_manifest_hash != str(train_plan.get("oos_commitment_hash") or ""):
        raise ValueError("quality/train OOS commitments do not match")
    oos_manifest = _validate_oos_manifest(oos_manifest_path, oos_manifest_hash)
    start_sec = int(oos_manifest["range"]["start_sec"])
    end_sec = int(oos_manifest["range"]["end_sec"])
    folds = _fold_contract(start_sec, end_sec)
    module_path = Path(__file__).resolve()
    core_path = Path(__import__("gate_membership_momentum").__file__).resolve()
    contract: dict[str, Any] = {
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_oos_planonly",
        "stage": "chronological_oos",
        "decision": PLAN_DECISION,
        "hypothesis_id": str(train_plan["hypothesis_id"]),
        "research_only": True,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "oos_allowed_now": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "strategy": train_plan["strategy"],
        "cost_contract": train_plan["cost_contract"],
        "train_authorization": {
            "plan_path": str(resolved_train_plan),
            "plan_sha256": sha256_file(resolved_train_plan),
            "plan_hash": train_plan_hash_value,
            "result_path": str(resolved_train_result),
            "result_sha256": sha256_file(resolved_train_result),
            "result_hash": train_result_hash_value,
            "decision": FEASIBLE_DECISION,
            "train_manifest_path": str(train_plan["train_input"]["manifest_path"]),
            "train_manifest_sha256": str(train_plan["train_input"]["manifest_sha256"]),
            "train_manifest_hash": str(train_plan["train_input"]["manifest_hash"]),
        },
        "oos_input": {
            "manifest_path": str(oos_manifest_path),
            "manifest_sha256": sha256_file(oos_manifest_path),
            "manifest_hash": oos_manifest_hash,
            "range": {"start_sec": start_sec, "end_sec": end_sec},
            "quality_report_sha256": sha256_file(quality_path),
            "quality_artifact_hash": quality_hash,
            "normalized_manifest_hash": _validate_hash(
                quality.get("normalized_manifest_hash"), label="normalized manifest hash"
            ),
        },
        "fold_contract": folds,
        "bootstrap_contract": {
            "cluster": "rebalance_event",
            "samples": BOOTSTRAP_SAMPLES,
            "seed": BOOTSTRAP_SEED,
            "lower_quantile": 0.05,
        },
        "oos_gates": {
            "minimum_independent_rebalances": MIN_OOS_REBALANCES,
            "minimum_unique_assets_traded": MIN_UNIQUE_ASSETS,
            "minimum_positive_folds": 4,
            "price_only_net_expectancy_bps_gt": 0.0,
            "total_net_expectancy_bps_gt": 0.0,
            "profit_factor_gte": 1.2,
            "stress_total_net_expectancy_bps_gte": 0.0,
            "bootstrap_expectancy_lower_95_bps_gt": 0.0,
            "maximum_drawdown_pct": 10.0,
            "maximum_top_base_positive_share": 0.25,
            "maximum_top_rebalance_positive_share": 0.25,
        },
        "capacity_contract": {
            "per_position_notional_quote": 500.0,
            "historical_ohlcv_proves_fill_or_impact": False,
            "required_next_stage": "execution_probe",
            "maximum_historical_verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
            "core_module_path": str(core_path),
            "core_module_sha256": sha256_file(core_path),
        },
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "visible_terminal_required": True,
            "local_immutable_inputs_only": True,
        },
        "next_allowed_command": "fast-edge-membership-momentum-oos",
        "blocked_actions": ["grid_search", "retune", "paper_forward", "live_orders", "private_api_keys"],
    }
    contract["input_merkle_sha256"] = sha256_json(
        {
            "quality_artifact_hash": quality_hash,
            "train_plan_hash": train_plan_hash_value,
            "train_result_hash": train_result_hash_value,
            "oos_manifest_hash": oos_manifest_hash,
            "module_sha256": contract["code_provenance"]["module_sha256"],
            "core_module_sha256": contract["code_provenance"]["core_module_sha256"],
        }
    )
    payload = {
        "schema": PLAN_SCHEMA,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        **contract,
    }
    payload["plan_hash"] = oos_plan_hash(payload)
    if output_path is not None:
        _atomic_write_json(output_path, payload)
    return payload


def _validate_oos_plan(path: Path, expected_plan_hash: str) -> dict[str, Any]:
    plan = _read_json_object(path)
    stored_hash = str(plan.get("plan_hash") or "")
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("decision") != PLAN_DECISION
        or stored_hash != oos_plan_hash(plan)
        or stored_hash != expected_plan_hash
        or plan.get("oos_allowed_now") is not True
        or plan.get("network_access") is not False
        or plan.get("grid_search") is not False
        or plan.get("retune") is not False
    ):
        raise ValueError("OOS plan is not hash-valid or violates the frozen contract")
    code = plan.get("code_provenance")
    if not isinstance(code, Mapping):
        raise ValueError("OOS plan code provenance is missing")
    if str(code.get("module_sha256") or "") != sha256_file(Path(__file__).resolve()):
        raise ValueError("OOS evaluator module hash mismatch")
    core_path = Path(str(code.get("core_module_path") or "")).expanduser().resolve()
    if str(code.get("core_module_sha256") or "") != sha256_file(core_path):
        raise ValueError("momentum core module hash mismatch")
    return plan


def _merge_markets(train: list[MarketSeries], oos: list[MarketSeries]) -> list[MarketSeries]:
    train_by_symbol = {market.symbol: market for market in train}
    oos_by_symbol = {market.symbol: market for market in oos}
    if set(train_by_symbol) != set(oos_by_symbol):
        raise ValueError("train/OOS symbol sets do not match")
    merged: list[MarketSeries] = []
    for symbol in sorted(train_by_symbol):
        left = train_by_symbol[symbol]
        right = oos_by_symbol[symbol]
        if left.canonical_asset_id != right.canonical_asset_id or left.base != right.base:
            raise ValueError(f"train/OOS identity mismatch: {symbol}")
        for label, left_values, right_values in (
            ("opens", left.opens, right.opens),
            ("closes", left.closes, right.closes),
            ("quote_volumes", left.quote_volumes, right.quote_volumes),
        ):
            if set(left_values) & set(right_values):
                raise ValueError(f"train/OOS {label} overlap: {symbol}")
        funding_timestamps = {timestamp for timestamp, _ in left.funding}
        if funding_timestamps & {timestamp for timestamp, _ in right.funding}:
            raise ValueError(f"train/OOS funding overlap: {symbol}")
        market = MarketSeries(
            exchange=left.exchange,
            symbol=symbol,
            base=left.base,
            canonical_asset_id=left.canonical_asset_id,
            opens={**left.opens, **right.opens},
            closes={**left.closes, **right.closes},
            quote_volumes={**left.quote_volumes, **right.quote_volumes},
            funding=sorted([*left.funding, *right.funding]),
        )
        merged.append(market)
    return merged


def _event_net_return(event: RebalanceEvent, *, cost_bps: float, favorable_multiplier: float) -> float:
    funding = adjusted_event_funding(event, favorable_multiplier)
    return event.price_return + funding - float(cost_bps) / 10_000.0


def _bootstrap_expectancy(
    values: list[float],
    *,
    samples: int,
    seed: int,
    lower_quantile: float,
) -> dict[str, Any]:
    if not values:
        return {
            "cluster": "rebalance_event",
            "samples": samples,
            "seed": seed,
            "expectancy_lower_95_bps": None,
        }
    generator = random.Random(seed)
    count = len(values)
    means = []
    for _ in range(samples):
        means.append(sum(values[generator.randrange(count)] for _ in range(count)) / count)
    means.sort()
    index = max(0, min(samples - 1, math.ceil(lower_quantile * samples) - 1))
    return {
        "cluster": "rebalance_event",
        "samples": samples,
        "seed": seed,
        "lower_quantile": lower_quantile,
        "expectancy_lower_95_bps": round(means[index] * 10_000.0, 8),
    }


def _top_positive_share(values: list[float]) -> float:
    positives = [value for value in values if value > 0.0]
    total = sum(positives)
    return max(positives) / total if total > 0.0 else 1.0


def _profit_factor_pass(metrics: Mapping[str, Any], minimum: float) -> bool:
    value = metrics.get("profit_factor")
    if value is None:
        return float(metrics.get("total_net_expectancy_bps") or 0.0) > 0.0
    return float(value) >= minimum


def evaluate_oos_plan(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    started = time.monotonic()
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = _validate_oos_plan(resolved_plan, expected_plan_hash)
    authorization = plan["train_authorization"]
    train_plan_path = Path(str(authorization["plan_path"])).expanduser().resolve()
    if sha256_file(train_plan_path) != str(authorization["plan_sha256"]):
        raise ValueError("train plan file hash mismatch")
    train_plan = validate_train_plan(train_plan_path, str(authorization["plan_hash"]))
    train_result_path = Path(str(authorization["result_path"])).expanduser().resolve()
    if sha256_file(train_result_path) != str(authorization["result_sha256"]):
        raise ValueError("train result file hash mismatch")
    _validate_train_result(
        train_result_path,
        expected_hash=str(authorization["result_hash"]),
        expected_train_plan_hash=str(authorization["plan_hash"]),
    )
    train_manifest_path = Path(str(authorization["train_manifest_path"])).expanduser().resolve()
    if sha256_file(train_manifest_path) != str(authorization["train_manifest_sha256"]):
        raise ValueError("train manifest file hash mismatch")
    from gate_membership_momentum_train import _validate_train_manifest

    train_manifest = _validate_train_manifest(train_manifest_path, str(authorization["train_manifest_hash"]))
    oos_input = plan["oos_input"]
    oos_manifest_path = Path(str(oos_input["manifest_path"])).expanduser().resolve()
    if sha256_file(oos_manifest_path) != str(oos_input["manifest_sha256"]):
        raise ValueError("OOS manifest file hash mismatch")
    oos_manifest = _validate_oos_manifest(oos_manifest_path, str(oos_input["manifest_hash"]))
    train_markets = _load_markets(train_manifest, train_manifest_path)
    oos_markets = _load_markets(oos_manifest, oos_manifest_path)
    markets = _merge_markets(train_markets, oos_markets)
    config = FrozenMomentumConfig(
        lookback_days=int(plan["strategy"]["lookback_days"]),
        hold_days=int(plan["strategy"]["hold_days"]),
        rebalance_every_days=int(plan["strategy"]["rebalance_every_days"]),
        min_per_side=int(plan["strategy"]["min_per_side"]),
        minimum_scored_markets=int(plan["strategy"]["minimum_scored_markets"]),
        liquidity_lookback_days=int(plan["strategy"]["liquidity_lookback_days"]),
        minimum_median_quote_volume=float(plan["strategy"]["minimum_median_quote_volume"]),
    )
    normal_cost = float(plan["cost_contract"]["normal"]["total_bps"])
    stress_cost = float(plan["cost_contract"]["stress"]["total_bps"])
    events: list[RebalanceEvent] = []
    fold_metrics: list[dict[str, Any]] = []
    for fold in plan["fold_contract"]:
        if time.monotonic() - started >= runtime:
            raise TimeoutError("membership momentum OOS runtime exhausted")
        fold_start_day = int(fold["start_sec"]) // DAY_SEC
        fold_end_day = int(fold["end_sec"]) // DAY_SEC
        last_signal_day = fold_end_day - config.hold_days - 2
        fold_events: list[RebalanceEvent] = []
        for signal_day in range(fold_start_day, last_signal_day + 1, config.rebalance_every_days):
            event = evaluate_rebalance(markets, signal_day=signal_day, config=config)
            if event is not None:
                if not (fold_start_day <= event.signal_day and event.exit_day < fold_end_day):
                    raise ValueError("OOS event escapes fold boundary")
                fold_events.append(event)
        events.extend(fold_events)
        fold_metrics.append(
            {
                **fold,
                "normal_metrics": portfolio_metrics(
                    fold_events,
                    cost_bps=normal_cost,
                    favorable_funding_multiplier=1.0,
                ),
                "stress_metrics": portfolio_metrics(
                    fold_events,
                    cost_bps=stress_cost,
                    favorable_funding_multiplier=0.0,
                ),
            }
        )
    normal = portfolio_metrics(events, cost_bps=normal_cost, favorable_funding_multiplier=1.0)
    stress = portfolio_metrics(events, cost_bps=stress_cost, favorable_funding_multiplier=0.0)
    normal_returns = [
        _event_net_return(event, cost_bps=normal_cost, favorable_multiplier=1.0)
        for event in events
    ]
    bootstrap_contract = plan["bootstrap_contract"]
    bootstrap = _bootstrap_expectancy(
        normal_returns,
        samples=int(bootstrap_contract["samples"]),
        seed=int(bootstrap_contract["seed"]),
        lower_quantile=float(bootstrap_contract["lower_quantile"]),
    )
    positive_folds = sum(
        float(fold["normal_metrics"].get("total_net_expectancy_bps") or 0.0) > 0.0
        for fold in fold_metrics
    )
    top_rebalance_share = _top_positive_share(normal_returns)
    gates = plan["oos_gates"]
    sample_reasons: list[str] = []
    if int(normal.get("independent_rebalances") or 0) < int(gates["minimum_independent_rebalances"]):
        sample_reasons.append("insufficient_independent_rebalances")
    if int(normal.get("unique_assets_traded") or 0) < int(gates["minimum_unique_assets_traded"]):
        sample_reasons.append("insufficient_unique_assets_traded")
    if any(int(fold["normal_metrics"].get("independent_rebalances") or 0) == 0 for fold in fold_metrics):
        sample_reasons.append("one_or_more_empty_oos_folds")
    economic_reasons: list[str] = []
    if float(normal.get("price_only_net_expectancy_bps") or 0.0) <= float(gates["price_only_net_expectancy_bps_gt"]):
        economic_reasons.append("price_only_net_expectancy_not_positive")
    if float(normal.get("total_net_expectancy_bps") or 0.0) <= float(gates["total_net_expectancy_bps_gt"]):
        economic_reasons.append("total_net_expectancy_not_positive")
    if not _profit_factor_pass(normal, float(gates["profit_factor_gte"])):
        economic_reasons.append("profit_factor_below_minimum")
    if float(stress.get("total_net_expectancy_bps") or 0.0) < float(gates["stress_total_net_expectancy_bps_gte"]):
        economic_reasons.append("stress_net_expectancy_negative")
    lower_bound = bootstrap.get("expectancy_lower_95_bps")
    if lower_bound is None or float(lower_bound) <= float(gates["bootstrap_expectancy_lower_95_bps_gt"]):
        economic_reasons.append("bootstrap_expectancy_lower_bound_not_positive")
    if positive_folds < int(gates["minimum_positive_folds"]):
        economic_reasons.append("fewer_than_four_positive_oos_folds")
    if float(normal.get("max_drawdown_pct") or 0.0) > float(gates["maximum_drawdown_pct"]):
        economic_reasons.append("max_drawdown_above_limit")
    if float(normal.get("top_base_positive_share") or 0.0) > float(gates["maximum_top_base_positive_share"]):
        economic_reasons.append("top_base_concentration_above_limit")
    if top_rebalance_share > float(gates["maximum_top_rebalance_positive_share"]):
        economic_reasons.append("top_rebalance_concentration_above_limit")
    if sample_reasons:
        decision = OOS_INSUFFICIENT_DECISION
        reasons = sample_reasons
        next_command = "none_membership_momentum_branch_closed_insufficient_data"
    elif economic_reasons:
        decision = OOS_REJECTED_DECISION
        reasons = economic_reasons
        next_command = "none_membership_momentum_branch_closed_no_retune"
    else:
        decision = HISTORICAL_ACCEPT_DECISION
        reasons = []
        next_command = "fast-edge-membership-momentum-execution-probe-plan"
    event_rows = [
        {
            "signal_day": event.signal_day,
            "entry_day": event.entry_day,
            "exit_day": event.exit_day,
            "long_bases": list(event.long_bases),
            "short_bases": list(event.short_bases),
            "price_return": event.price_return,
            "funding_return": event.funding_return,
        }
        for event in events
    ]
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": plan["run_id"],
        "plan_hash": expected_plan_hash,
        "stage": "chronological_oos",
        "final": True,
        "decision": decision,
        "rejection_reasons": reasons,
        "normal_metrics": normal,
        "stress_metrics": stress,
        "fold_metrics": fold_metrics,
        "positive_folds": positive_folds,
        "bootstrap": bootstrap,
        "top_rebalance_positive_share": round(top_rebalance_share, 8),
        "events": event_rows,
        "capacity_status": "REQUIRES_EXECUTION_PROBE",
        "capacity_contract": plan["capacity_contract"],
        "oos_read": True,
        "retune_allowed": False,
        "data_access_audit": {
            "network_access": False,
            "train_files_opened_for_past_warmup": True,
            "oos_manifest_opened": True,
            "oos_files_opened": True,
            "grid_search": False,
            "retune": False,
        },
        "code_provenance": plan["code_provenance"],
        "input_merkle_sha256": plan["input_merkle_sha256"],
        "runtime_sec": time.monotonic() - started,
        "research_only": True,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "next_allowed_command": next_command,
    }
    result["deterministic_result_hash"] = train_result_hash(result)
    _atomic_write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate membership momentum OOS PlanOnly/evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--quality-report", required=True)
    plan_parser.add_argument("--expected-quality-hash", required=True)
    plan_parser.add_argument("--train-plan", required=True)
    plan_parser.add_argument("--expected-train-plan-hash", required=True)
    plan_parser.add_argument("--train-result", required=True)
    plan_parser.add_argument("--expected-train-result-hash", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--plan", required=True)
    eval_parser.add_argument("--expected-plan-hash", required=True)
    eval_parser.add_argument("--output", required=True)
    eval_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    args = parser.parse_args()
    if args.command == "plan":
        result = build_oos_plan(
            quality_report_path=args.quality_report,
            expected_quality_hash=args.expected_quality_hash,
            train_plan_path=args.train_plan,
            expected_train_plan_hash=args.expected_train_plan_hash,
            train_result_path=args.train_result,
            expected_train_result_hash=args.expected_train_result_hash,
            output_path=args.output,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = evaluate_oos_plan(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
            max_runtime_sec=args.max_runtime_sec,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
