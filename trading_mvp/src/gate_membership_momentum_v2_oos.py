from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_historical_membership_v3_history_quality as v3_quality
import gate_membership_momentum_v2_train as v2_train
from gate_membership_momentum import (
    DAY_SEC,
    FrozenMomentumConfig,
    MarketSeries,
    RebalanceEvent,
    evaluate_rebalance,
    portfolio_metrics,
)


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_v2_oos_plan_v2"
RESULT_SCHEMA = "trading_mvp_gate_membership_momentum_v2_oos_evaluation_v2"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_OOS_PLAN_READY"
HISTORICAL_ACCEPT_DECISION = (
    "GATE_MEMBERSHIP_MOMENTUM_V2_HISTORICAL_ACCEPT_FOR_EXECUTION_PROBE"
)
OOS_REJECTED_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_OOS_REJECTED_NO_RETUNE"
OOS_INSUFFICIENT_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_OOS_INSUFFICIENT_DATA"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_OOS_STOPPED_INCOMPLETE"
MAX_RUNTIME_SEC = 1_800
MINIMUM_REBALANCE_COVERAGE = 0.80
MINIMUM_UNIQUE_ASSETS = 10
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 20_260_717


def oos_plan_hash(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_contract")
    if isinstance(frozen, Mapping):
        return v3_history_plan.sha256_json(frozen)
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "plan_hash"}
        }
    )


def _validate_train_result(
    path: str | Path,
    *,
    expected_hash: str,
    expected_train_plan_hash: str,
) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    result = v2_train._read_json_object(resolved)
    expected = v2_train._validate_hash(expected_hash, label="train result hash")
    stored = str(result.get("deterministic_result_hash") or "")
    if (
        result.get("schema") != v2_train.RESULT_SCHEMA
        or result.get("final") is not True
        or result.get("decision") != v2_train.FEASIBLE_DECISION
        or result.get("oos_read") is not False
        or str(result.get("plan_hash") or "") != expected_train_plan_hash
        or result.get("next_allowed_command")
        != "create_hash_bound_gate_membership_momentum_v2_oos_planonly"
        or stored != v2_train._deterministic_result_hash(result)
        or stored != expected
        or v2_train._contains_oos_artifact_path(result)
    ):
        raise ValueError("train result is not a hash-valid momentum-v2 FEASIBLE artifact")
    audit = result.get("data_access_audit")
    if (
        not isinstance(audit, Mapping)
        or audit.get("oos_paths_available") is not False
        or audit.get("oos_files_opened") is not False
        or audit.get("grid_search") is not False
        or audit.get("retune") is not False
    ):
        raise ValueError("train result data-access audit violates the OOS embargo")
    return result, resolved


def _validate_oos_manifest(path: str | Path, *, expected_hash: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    manifest = v2_train._read_json_object(resolved)
    stored = str(manifest.get("artifact_hash") or "")
    if (
        manifest.get("schema") != v3_quality.SPLIT_MANIFEST_SCHEMA
        or manifest.get("stage") != "sealed_oos"
        or manifest.get("sealed") is not True
        or manifest.get("oos_paths_present") is not True
        or manifest.get("point_in_time_universe") is not True
        or manifest.get("historical_universe") is not True
        or manifest.get("lifecycle_mask_applied") is not True
        or manifest.get("no_interpolation") is not True
        or stored != v3_quality._normalized_manifest_hash(manifest)
        or stored != v2_train._validate_hash(expected_hash, label="OOS manifest hash")
    ):
        raise ValueError("unexpected or hash-invalid membership-v3 sealed OOS manifest")
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
        or end_sec - start_sec != v3_history_plan.OOS_DAYS * DAY_SEC
    ):
        raise ValueError("OOS manifest must contain exactly 100 UTC-aligned days")

    universe = manifest.get("universe")
    files = manifest.get("normalized_files")
    if not isinstance(universe, list) or len(universe) < 20 or not isinstance(files, list):
        raise ValueError("OOS manifest executable universe is below 20 canonical assets")
    symbols: set[str] = set()
    canonical_ids: set[str] = set()
    for raw in universe:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid OOS universe row")
        symbol = str(raw.get("symbol") or "")
        canonical_id = str(raw.get("canonical_asset_id") or "")
        if not symbol or symbol in symbols or not canonical_id or canonical_id in canonical_ids:
            raise ValueError("OOS universe identity is missing or duplicated")
        listed_from = int(raw.get("listed_from_ts") or 0)
        listed_to_raw = raw.get("listed_to_ts")
        listed_to = int(listed_to_raw) if listed_to_raw is not None else None
        if listed_from <= 0 or listed_from >= end_sec or (listed_to is not None and listed_to <= listed_from):
            raise ValueError("OOS lifecycle interval is invalid")
        symbols.add(symbol)
        canonical_ids.add(canonical_id)

    root = resolved.parent.resolve()
    file_symbols: set[str] = set()
    for raw in files:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid OOS normalized file record")
        symbol = str(raw.get("symbol") or "")
        if not symbol or symbol in file_symbols:
            raise ValueError("OOS normalized file symbol is missing or duplicated")
        file_symbols.add(symbol)
        for path_key, hash_key in (
            ("kline_path", "kline_sha256"),
            ("funding_path", "funding_sha256"),
        ):
            target = Path(str(raw.get(path_key) or "")).expanduser().resolve()
            if not target.is_file() or not target.is_relative_to(root):
                raise ValueError(f"OOS artifact escapes sealed root: {path_key}")
            if v3_history_plan.sha256_file(target) != v2_train._validate_hash(
                raw.get(hash_key), label=hash_key
            ):
                raise ValueError(f"OOS artifact hash mismatch: {path_key}")
    if symbols != file_symbols:
        raise ValueError("OOS universe and normalized file inventories differ")
    return manifest


def _fold_contract(start_sec: int, end_sec: int) -> list[dict[str, int]]:
    if end_sec - start_sec != v3_history_plan.OOS_DAYS * DAY_SEC:
        raise ValueError("OOS range does not match frozen v3 fold contract")
    folds = []
    for index in range(v3_history_plan.OOS_FOLDS):
        fold_start = start_sec + index * v3_history_plan.OOS_FOLD_DAYS * DAY_SEC
        fold_end = fold_start + v3_history_plan.OOS_FOLD_DAYS * DAY_SEC
        folds.append(
            {
                "fold": index + 1,
                "start_sec": fold_start,
                "end_sec": fold_end,
                "days": v3_history_plan.OOS_FOLD_DAYS,
            }
        )
    if folds[-1]["end_sec"] != end_sec:
        raise ValueError("OOS folds do not cover the sealed range")
    return folds


def _build_oos_rebalance_schedule(
    folds: list[Mapping[str, int]],
    *,
    anchor_day: int,
    config: FrozenMomentumConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not folds:
        raise ValueError("OOS fold contract is empty")
    enriched_folds: list[dict[str, Any]] = []
    eligible_all: list[int] = []
    excluded_all: list[int] = []
    for fold in folds:
        start_day = int(fold["start_sec"]) // DAY_SEC
        end_day = int(fold["end_sec"]) // DAY_SEC
        scheduled = v2_train._scheduled_signal_days(
            anchor_day=int(anchor_day),
            start_day=start_day,
            end_day=end_day,
            cadence_days=config.rebalance_every_days,
        )
        eligible = [
            signal_day
            for signal_day in scheduled
            if signal_day + 1 + config.hold_days < end_day
        ]
        eligible_set = set(eligible)
        excluded = [signal_day for signal_day in scheduled if signal_day not in eligible_set]
        eligible_all.extend(eligible)
        excluded_all.extend(excluded)
        enriched_folds.append(
            {
                **dict(fold),
                "scheduled_signal_days": scheduled,
                "eligible_signal_days": eligible,
                "boundary_excluded_signal_days": excluded,
            }
        )

    oos_start_day = int(folds[0]["start_sec"]) // DAY_SEC
    oos_end_day = int(folds[-1]["end_sec"]) // DAY_SEC
    all_scheduled = v2_train._scheduled_signal_days(
        anchor_day=int(anchor_day),
        start_day=oos_start_day,
        end_day=oos_end_day,
        cadence_days=config.rebalance_every_days,
    )
    if sorted(eligible_all + excluded_all) != all_scheduled:
        raise ValueError("OOS fold schedule does not partition the global cadence")
    schedule = {
        "semantics": v2_train.REBALANCE_SCHEDULE_SEMANTICS,
        "anchor_source": "inherited_from_hash_valid_train_plan",
        "anchor_day": int(anchor_day),
        "anchor_ts": int(anchor_day) * DAY_SEC,
        "cadence_days": config.rebalance_every_days,
        "oos_scheduled_signal_days": all_scheduled,
        "eligible_signal_days": eligible_all,
        "boundary_excluded_signal_days": excluded_all,
        "next_scheduled_signal_day_at_or_after_oos_end": (
            v2_train._first_scheduled_day_at_or_after(
                anchor_day=int(anchor_day),
                lower_bound_day=oos_end_day,
                cadence_days=config.rebalance_every_days,
            )
        ),
    }
    return enriched_folds, schedule


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

    quality, quality_path = v2_train._validate_quality_report(
        quality_report_path,
        expected_artifact_hash=expected_quality_hash,
    )
    resolved_train_plan = Path(train_plan_path).expanduser().resolve()
    train_plan_hash = v2_train._validate_hash(
        expected_train_plan_hash, label="train plan hash"
    )
    train_plan = v2_train.authorize_train_evaluation(
        resolved_train_plan,
        train_plan_hash,
    )
    train_result_hash = v2_train._validate_hash(
        expected_train_result_hash, label="train result hash"
    )
    _, resolved_train_result = _validate_train_result(
        train_result_path,
        expected_hash=train_result_hash,
        expected_train_plan_hash=train_plan_hash,
    )

    quality_hash = v2_train._validate_hash(
        expected_quality_hash, label="quality artifact hash"
    )
    train_input = train_plan.get("train_input")
    if not isinstance(train_input, Mapping):
        raise ValueError("momentum-v2 train input is missing")
    if (
        str(train_input.get("quality_artifact_hash") or "") != quality_hash
        or str(train_input.get("quality_report_sha256") or "")
        != v3_history_plan.sha256_file(quality_path)
        or str(train_input.get("normalized_manifest_hash") or "")
        != str(quality.get("normalized_manifest_hash") or "")
    ):
        raise ValueError("quality and train provenance do not match")
    oos_commitment = v2_train._validate_hash(
        quality.get("oos_commitment_hash"), label="OOS commitment hash"
    )
    if str(train_plan.get("oos_commitment_hash") or "") != oos_commitment:
        raise ValueError("quality and train OOS commitments do not match")

    # OOS metadata is intentionally opened only after train FEASIBLE validation.
    oos_manifest_path = Path(str(quality.get("oos_manifest_path") or "")).expanduser().resolve()
    oos_manifest = _validate_oos_manifest(
        oos_manifest_path,
        expected_hash=oos_commitment,
    )
    train_end_sec = int(train_input["range"]["end_sec"])
    oos_start_sec = int(oos_manifest["range"]["start_sec"])
    oos_end_sec = int(oos_manifest["range"]["end_sec"])
    if oos_start_sec != train_end_sec:
        raise ValueError("train and OOS ranges are not contiguous")
    base_folds = _fold_contract(oos_start_sec, oos_end_sec)
    config = FrozenMomentumConfig(
        lookback_days=int(train_plan["strategy"]["lookback_days"]),
        hold_days=int(train_plan["strategy"]["hold_days"]),
        rebalance_every_days=int(train_plan["strategy"]["rebalance_every_days"]),
        min_per_side=int(train_plan["strategy"]["min_per_side"]),
        minimum_scored_markets=int(train_plan["strategy"]["minimum_scored_markets"]),
        liquidity_lookback_days=int(train_plan["strategy"]["liquidity_lookback_days"]),
        minimum_median_quote_volume=float(
            train_plan["strategy"]["minimum_median_quote_volume"]
        ),
    )
    train_schedule = train_plan.get("rebalance_schedule_contract")
    expected_train_schedule = v2_train._build_rebalance_schedule_contract(
        start_sec=int(train_input["range"]["start_sec"]),
        end_sec=int(train_input["range"]["end_sec"]),
        config=config,
    )
    if train_schedule != expected_train_schedule:
        raise ValueError("train PlanOnly does not preserve the global rebalance anchor")
    folds, schedule = _build_oos_rebalance_schedule(
        base_folds,
        anchor_day=int(expected_train_schedule["anchor_day"]),
        config=config,
    )
    theoretical = len(schedule["eligible_signal_days"])
    minimum_rebalances = math.ceil(theoretical * MINIMUM_REBALANCE_COVERAGE)
    if theoretical < 1 or minimum_rebalances < 1:
        raise ValueError("frozen OOS folds cannot produce independent rebalances")

    module_paths = {
        "module": Path(__file__).resolve(),
        "core_module": Path(__import__("gate_membership_momentum").__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
        "quality_module": Path(v3_quality.__file__).resolve(),
        "history_plan_module": Path(v3_history_plan.__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    contract: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_v2_oos_planonly",
        "stage": "chronological_oos",
        "decision": PLAN_DECISION,
        "hypothesis_id": train_plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "oos_allowed_now": True,
        "oos_read": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "strategy": train_plan["strategy"],
        "strategy_provenance": train_plan["strategy_provenance"],
        "cost_contract": train_plan["cost_contract"],
        "rebalance_schedule_contract": schedule,
        "quality_input": {
            "report_path": str(quality_path),
            "report_sha256": v3_history_plan.sha256_file(quality_path),
            "artifact_hash": quality_hash,
            "normalized_manifest_hash": v2_train._validate_hash(
                quality.get("normalized_manifest_hash"),
                label="normalized manifest hash",
            ),
        },
        "train_authorization": {
            "plan_path": str(resolved_train_plan),
            "plan_sha256": v3_history_plan.sha256_file(resolved_train_plan),
            "plan_hash": train_plan_hash,
            "result_path": str(resolved_train_result),
            "result_sha256": v3_history_plan.sha256_file(resolved_train_result),
            "result_hash": train_result_hash,
            "decision": v2_train.FEASIBLE_DECISION,
            "manifest_path": str(train_input["manifest_path"]),
            "manifest_sha256": str(train_input["manifest_sha256"]),
            "manifest_hash": str(train_input["manifest_hash"]),
        },
        "oos_input": {
            "manifest_path": str(oos_manifest_path),
            "manifest_sha256": v3_history_plan.sha256_file(oos_manifest_path),
            "manifest_hash": oos_commitment,
            "range": {"start_sec": oos_start_sec, "end_sec": oos_end_sec},
        },
        "fold_contract": folds,
        "sample_capacity": {
            "oos_days": v3_history_plan.OOS_DAYS,
            "fold_count": v3_history_plan.OOS_FOLDS,
            "fold_days": v3_history_plan.OOS_FOLD_DAYS,
            "theoretical_max_independent_rebalances": theoretical,
            "minimum_rebalance_coverage": MINIMUM_REBALANCE_COVERAGE,
            "minimum_independent_rebalances": minimum_rebalances,
            "limited_statistical_power": theoretical < 20,
        },
        "bootstrap_contract": {
            "cluster": "rebalance_event",
            "samples": BOOTSTRAP_SAMPLES,
            "seed": BOOTSTRAP_SEED,
            "lower_quantile": 0.05,
        },
        "oos_gates": {
            "minimum_independent_rebalances": minimum_rebalances,
            "minimum_unique_assets_traded": MINIMUM_UNIQUE_ASSETS,
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
        "code_provenance": code_provenance,
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "visible_terminal_required": True,
            "local_immutable_inputs_only": True,
            "timeout_verdict": STOPPED_INCOMPLETE_DECISION,
        },
        "data_access_audit": {
            "quality_report_opened": True,
            "train_plan_and_result_opened": True,
            "train_feasible_verified_before_oos_manifest": True,
            "oos_manifest_opened_for_metadata": True,
            "oos_return_rows_read": False,
            "grid_search": False,
            "retune": False,
        },
        "next_allowed_command": "fast-edge-membership-momentum-v2-oos",
        "blocked_actions": [
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
        "limitations": [
            f"The frozen 100-day OOS has at most {theoretical} globally anchored, fold-contained weekly rebalances.",
            "A positive historical verdict requires a separate execution-capacity probe.",
            "Gate-only history does not establish MEXC portability or executable fills.",
        ],
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "quality_artifact_hash": quality_hash,
            "quality_report_sha256": contract["quality_input"]["report_sha256"],
            "train_plan_hash": train_plan_hash,
            "train_plan_sha256": contract["train_authorization"]["plan_sha256"],
            "train_result_hash": train_result_hash,
            "train_result_sha256": contract["train_authorization"]["result_sha256"],
            "train_manifest_hash": contract["train_authorization"]["manifest_hash"],
            "oos_manifest_hash": oos_commitment,
            "oos_manifest_sha256": contract["oos_input"]["manifest_sha256"],
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(contract)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan_hash,
        "frozen_contract": contract,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def authorize_oos_evaluation(
    plan_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    resolved = Path(plan_path).expanduser().resolve()
    plan = v2_train._read_json_object(resolved)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected momentum-v2 OOS PlanOnly artifact")
    if not isinstance(frozen, Mapping):
        raise ValueError("momentum-v2 OOS frozen contract is missing")
    computed = v3_history_plan.sha256_json(frozen)
    if (
        str(plan.get("plan_hash") or "") != computed
        or str(expected_plan_hash) != computed
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 OOS plan hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-momentum-v2-oos":
        raise ValueError("momentum-v2 OOS evaluation is not the next allowed command")
    if (
        plan.get("oos_allowed_now") is not True
        or plan.get("oos_read") is not False
        or plan.get("network_access") is not False
        or plan.get("grid_search") is not False
        or plan.get("retune") is not False
    ):
        raise ValueError("momentum-v2 OOS PlanOnly violates the frozen contract")
    code = plan.get("code_provenance")
    expected_paths = {
        "module": Path(__file__).resolve(),
        "core_module": Path(__import__("gate_membership_momentum").__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
        "quality_module": Path(v3_quality.__file__).resolve(),
        "history_plan_module": Path(v3_history_plan.__file__).resolve(),
    }
    if not isinstance(code, Mapping):
        raise ValueError("momentum-v2 OOS code provenance is missing")
    for name, expected_path in expected_paths.items():
        actual = Path(str(code.get(f"{name}_path") or "")).expanduser().resolve()
        if (
            actual != expected_path
            or not actual.is_file()
            or code.get(f"{name}_sha256") != v3_history_plan.sha256_file(actual)
        ):
            raise ValueError(f"momentum-v2 OOS module hash mismatch: {expected_path.name}")
    return plan


def _load_manifest_markets(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    *,
    label: str,
) -> list[MarketSeries]:
    markets = v2_train._load_markets(manifest, manifest_path)
    start_day = int(manifest["range"]["start_sec"]) // DAY_SEC
    end_day = int(manifest["range"]["end_sec"]) // DAY_SEC
    start_sec = start_day * DAY_SEC
    end_sec = end_day * DAY_SEC
    for market in markets:
        for values in (market.opens, market.closes, market.quote_volumes):
            if any(day < start_day or day >= end_day for day in values):
                raise ValueError(f"{label} daily row escapes manifest range: {market.symbol}")
        if any(timestamp < start_sec or timestamp >= end_sec for timestamp, _ in market.funding):
            raise ValueError(f"{label} funding row escapes manifest range: {market.symbol}")
    return markets


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
        train_funding = {timestamp for timestamp, _ in left.funding}
        if train_funding & {timestamp for timestamp, _ in right.funding}:
            raise ValueError(f"train/OOS funding overlap: {symbol}")
        merged.append(
            MarketSeries(
                exchange=left.exchange,
                symbol=symbol,
                base=left.base,
                canonical_asset_id=left.canonical_asset_id,
                opens={**left.opens, **right.opens},
                closes={**left.closes, **right.closes},
                quote_volumes={**left.quote_volumes, **right.quote_volumes},
                funding=sorted([*left.funding, *right.funding]),
            )
        )
    return merged


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
            "lower_quantile": lower_quantile,
            "expectancy_lower_95_bps": None,
        }
    generator = random.Random(seed)
    count = len(values)
    means = [
        sum(values[generator.randrange(count)] for _ in range(count)) / count
        for _ in range(samples)
    ]
    means.sort()
    index = max(0, min(samples - 1, math.ceil(lower_quantile * samples) - 1))
    return {
        "cluster": "rebalance_event",
        "samples": samples,
        "seed": seed,
        "lower_quantile": lower_quantile,
        "expectancy_lower_95_bps": round(means[index] * 10_000.0, 8),
    }


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
    plan = authorize_oos_evaluation(resolved_plan, expected_plan_hash)

    quality_input = plan["quality_input"]
    quality_path = Path(str(quality_input["report_path"])).expanduser().resolve()
    if v3_history_plan.sha256_file(quality_path) != str(quality_input["report_sha256"]):
        raise ValueError("quality report file hash mismatch")
    quality, _ = v2_train._validate_quality_report(
        quality_path,
        expected_artifact_hash=str(quality_input["artifact_hash"]),
    )

    authorization = plan["train_authorization"]
    train_plan_path = Path(str(authorization["plan_path"])).expanduser().resolve()
    if v3_history_plan.sha256_file(train_plan_path) != str(authorization["plan_sha256"]):
        raise ValueError("train plan file hash mismatch")
    train_plan = v2_train.authorize_train_evaluation(
        train_plan_path,
        str(authorization["plan_hash"]),
    )
    train_result_path = Path(str(authorization["result_path"])).expanduser().resolve()
    if v3_history_plan.sha256_file(train_result_path) != str(authorization["result_sha256"]):
        raise ValueError("train result file hash mismatch")
    _validate_train_result(
        train_result_path,
        expected_hash=str(authorization["result_hash"]),
        expected_train_plan_hash=str(authorization["plan_hash"]),
    )
    train_manifest_path = Path(str(authorization["manifest_path"])).expanduser().resolve()
    if v3_history_plan.sha256_file(train_manifest_path) != str(
        authorization["manifest_sha256"]
    ):
        raise ValueError("train manifest file hash mismatch")
    train_manifest = v2_train._validate_train_manifest(
        train_manifest_path,
        expected_hash=str(authorization["manifest_hash"]),
    )

    oos_input = plan["oos_input"]
    oos_manifest_path = Path(str(oos_input["manifest_path"])).expanduser().resolve()
    if v3_history_plan.sha256_file(oos_manifest_path) != str(oos_input["manifest_sha256"]):
        raise ValueError("OOS manifest file hash mismatch")
    if str(quality.get("oos_commitment_hash") or "") != str(oos_input["manifest_hash"]):
        raise ValueError("quality and OOS plan commitments do not match")
    oos_manifest = _validate_oos_manifest(
        oos_manifest_path,
        expected_hash=str(oos_input["manifest_hash"]),
    )
    train_markets = _load_manifest_markets(
        train_manifest,
        train_manifest_path,
        label="train",
    )
    oos_markets = _load_manifest_markets(
        oos_manifest,
        oos_manifest_path,
        label="OOS",
    )
    markets = _merge_markets(train_markets, oos_markets)
    config = FrozenMomentumConfig(
        lookback_days=int(plan["strategy"]["lookback_days"]),
        hold_days=int(plan["strategy"]["hold_days"]),
        rebalance_every_days=int(plan["strategy"]["rebalance_every_days"]),
        min_per_side=int(plan["strategy"]["min_per_side"]),
        minimum_scored_markets=int(plan["strategy"]["minimum_scored_markets"]),
        liquidity_lookback_days=int(plan["strategy"]["liquidity_lookback_days"]),
        minimum_median_quote_volume=float(
            plan["strategy"]["minimum_median_quote_volume"]
        ),
    )
    expected_train_schedule = v2_train._build_rebalance_schedule_contract(
        start_sec=int(train_manifest["range"]["start_sec"]),
        end_sec=int(train_manifest["range"]["end_sec"]),
        config=config,
    )
    base_folds = _fold_contract(
        int(oos_manifest["range"]["start_sec"]),
        int(oos_manifest["range"]["end_sec"]),
    )
    expected_folds, expected_schedule = _build_oos_rebalance_schedule(
        base_folds,
        anchor_day=int(expected_train_schedule["anchor_day"]),
        config=config,
    )
    if (
        plan.get("fold_contract") != expected_folds
        or plan.get("rebalance_schedule_contract") != expected_schedule
    ):
        raise ValueError("momentum-v2 OOS global rebalance schedule contract mismatch")
    normal_cost = float(plan["cost_contract"]["normal"]["total_bps"])
    stress_cost = float(plan["cost_contract"]["stress"]["total_bps"])
    events: list[RebalanceEvent] = []
    fold_metrics: list[dict[str, Any]] = []
    try:
        for fold in expected_folds:
            if time.monotonic() - started >= runtime:
                raise TimeoutError("membership momentum-v2 OOS runtime exhausted")
            fold_start_day = int(fold["start_sec"]) // DAY_SEC
            fold_end_day = int(fold["end_sec"]) // DAY_SEC
            fold_events: list[RebalanceEvent] = []
            for signal_day in fold["eligible_signal_days"]:
                event = evaluate_rebalance(markets, signal_day=signal_day, config=config)
                if event is not None:
                    if not (
                        fold_start_day <= event.signal_day
                        and event.exit_day < fold_end_day
                    ):
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
    except Exception as exc:
        stopped: dict[str, Any] = {
            "schema": RESULT_SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "run_id": plan["run_id"],
            "plan_hash": expected_plan_hash,
            "stage": "chronological_oos",
            "final": False,
            "decision": STOPPED_INCOMPLETE_DECISION,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "runtime_sec": time.monotonic() - started,
            "research_only": True,
            "oos_read": True,
            "live_orders": False,
            "private_api_keys": False,
            "next_allowed_command": "fast-edge-membership-momentum-v2-oos",
        }
        stopped["deterministic_result_hash"] = v2_train._deterministic_result_hash(stopped)
        v2_train._atomic_write_json(output_path, stopped)
        raise

    normal = portfolio_metrics(
        events,
        cost_bps=normal_cost,
        favorable_funding_multiplier=1.0,
    )
    stress = portfolio_metrics(
        events,
        cost_bps=stress_cost,
        favorable_funding_multiplier=0.0,
    )
    normal_returns = [
        v2_train._event_net_return(
            event,
            cost_bps=normal_cost,
            favorable_multiplier=1.0,
        )
        for event in events
    ]
    bootstrap = _bootstrap_expectancy(
        normal_returns,
        samples=int(plan["bootstrap_contract"]["samples"]),
        seed=int(plan["bootstrap_contract"]["seed"]),
        lower_quantile=float(plan["bootstrap_contract"]["lower_quantile"]),
    )
    positive_folds = sum(
        float(fold["normal_metrics"].get("total_net_expectancy_bps") or 0.0) > 0.0
        for fold in fold_metrics
    )
    top_rebalance_share = v2_train._top_positive_share(normal_returns)
    gates = plan["oos_gates"]
    sample_reasons: list[str] = []
    if int(normal.get("independent_rebalances") or 0) < int(
        gates["minimum_independent_rebalances"]
    ):
        sample_reasons.append("insufficient_independent_rebalances")
    if int(normal.get("unique_assets_traded") or 0) < int(
        gates["minimum_unique_assets_traded"]
    ):
        sample_reasons.append("insufficient_unique_assets_traded")
    if any(
        int(fold["normal_metrics"].get("independent_rebalances") or 0) == 0
        for fold in fold_metrics
    ):
        sample_reasons.append("one_or_more_empty_oos_folds")

    economic_reasons: list[str] = []
    if float(normal.get("price_only_net_expectancy_bps") or 0.0) <= float(
        gates["price_only_net_expectancy_bps_gt"]
    ):
        economic_reasons.append("price_only_net_expectancy_not_positive")
    if float(normal.get("total_net_expectancy_bps") or 0.0) <= float(
        gates["total_net_expectancy_bps_gt"]
    ):
        economic_reasons.append("total_net_expectancy_not_positive")
    if not v2_train._profit_factor_pass(normal, float(gates["profit_factor_gte"])):
        economic_reasons.append("profit_factor_below_minimum")
    if float(stress.get("total_net_expectancy_bps") or 0.0) < float(
        gates["stress_total_net_expectancy_bps_gte"]
    ):
        economic_reasons.append("stress_net_expectancy_negative")
    lower_bound = bootstrap.get("expectancy_lower_95_bps")
    if lower_bound is None or float(lower_bound) <= float(
        gates["bootstrap_expectancy_lower_95_bps_gt"]
    ):
        economic_reasons.append("bootstrap_expectancy_lower_bound_not_positive")
    if positive_folds < int(gates["minimum_positive_folds"]):
        economic_reasons.append("fewer_than_four_positive_oos_folds")
    if float(normal.get("max_drawdown_pct") or 0.0) > float(
        gates["maximum_drawdown_pct"]
    ):
        economic_reasons.append("max_drawdown_above_limit")
    if float(normal.get("top_base_positive_share") or 0.0) > float(
        gates["maximum_top_base_positive_share"]
    ):
        economic_reasons.append("top_base_concentration_above_limit")
    if top_rebalance_share > float(gates["maximum_top_rebalance_positive_share"]):
        economic_reasons.append("top_rebalance_concentration_above_limit")

    if sample_reasons:
        decision = OOS_INSUFFICIENT_DECISION
        reasons = sample_reasons
        next_command = "none_membership_momentum_v2_branch_closed_insufficient_data"
    elif economic_reasons:
        decision = OOS_REJECTED_DECISION
        reasons = economic_reasons
        next_command = "none_membership_momentum_v2_branch_closed_no_retune"
    else:
        decision = HISTORICAL_ACCEPT_DECISION
        reasons = []
        next_command = (
            "create_hash_bound_gate_membership_momentum_v2_execution_probe_planonly"
        )
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": plan["run_id"],
        "plan_hash": expected_plan_hash,
        "stage": "chronological_oos",
        "final": True,
        "decision": decision,
        "rejection_reasons": reasons,
        "normal_metrics": normal,
        "stress_metrics": stress,
        "rebalance_schedule_contract": expected_schedule,
        "fold_metrics": fold_metrics,
        "positive_folds": positive_folds,
        "bootstrap": bootstrap,
        "top_rebalance_positive_share": round(top_rebalance_share, 8),
        "sample_capacity": plan["sample_capacity"],
        "events": [
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
        ],
        "capacity_status": (
            "REQUIRES_EXECUTION_PROBE"
            if decision == HISTORICAL_ACCEPT_DECISION
            else "NOT_EVALUATED_BRANCH_CLOSED"
        ),
        "capacity_contract": plan["capacity_contract"],
        "maximum_historical_verdict": "ACCEPT_FOR_EXECUTION_PROBE",
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
        "limitations": plan["limitations"],
    }
    result["deterministic_result_hash"] = v2_train._deterministic_result_hash(result)
    v2_train._atomic_write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate membership-v3 momentum-v2 OOS PlanOnly/evaluator"
    )
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
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--expected-plan-hash", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
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
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
