from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from costs import CostProfile, RouteLeg, base_api_cost_profile


PLAN_SCHEMA = "fast_first_funding_regime_persistence_plan_v2"
HYPOTHESIS_ID = "funding_regime_persistence_carry_v2"
MAX_PLAN_RUNTIME_SEC = 600
MIN_SURVIVING_ASSETS = 4
MAX_CANDIDATE_ASSETS = 5
MIN_TRAIN_LIQUIDITY_QUOTE = 1_000_000.0
MAX_HOLDING_DAYS = 14
REGIME_CONFIRMATION_DAYS = 3
ADVERSE_EXIT_DAYS = 2
SAFETY_MARGIN_BPS = 20.0
DAY_SEC = 86_400


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def canonical_plan_hash(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return _sha256_json(payload)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _runtime(value: int | float) -> int:
    runtime = int(value)
    if runtime <= 0 or runtime > MAX_PLAN_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_PLAN_RUNTIME_SEC}]")
    return runtime


def _path(value: Any, *, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def _verify_hash(path: Path, expected: Any, *, label: str) -> str:
    expected_hash = str(expected or "").lower()
    if len(expected_hash) != 64:
        raise ValueError(f"{label} expected SHA256 is missing")
    observed = _sha256_file(path)
    if observed != expected_hash:
        raise ValueError(f"{label} hash mismatch: expected {expected_hash}, observed {observed}")
    return observed


def _find_hypothesis(bank: Mapping[str, Any]) -> dict[str, Any]:
    rows = bank.get("hypotheses")
    if not isinstance(rows, list):
        raise ValueError("hypothesis bank does not contain a hypotheses list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == HYPOTHESIS_ID]
    if len(matches) != 1:
        raise ValueError(f"hypothesis bank must contain exactly one {HYPOTHESIS_ID} record")
    record = copy.deepcopy(matches[0])
    if record.get("status") != "BANKED_NEEDS_NEW_DATA":
        raise ValueError("hypothesis bank record must remain BANKED_NEEDS_NEW_DATA before PlanOnly freeze")
    minimum = record.get("minimum_data") or {}
    expected_minimum = {
        "days": 90,
        "settlements": 180,
        "dual_leg_coverage": 0.8,
        "execution_snapshots": 180,
    }
    for key, expected in expected_minimum.items():
        if minimum.get(key) != expected:
            raise ValueError(f"hypothesis bank minimum_data.{key} changed")
    return record


def _freeze_candidates(quality: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = quality.get("train_liquidity_ranking")
    if not isinstance(rows, list):
        raise ValueError("quality report train_liquidity_ranking is missing")
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_bases: set[str] = set()
    for raw in rows[:MAX_CANDIDATE_ASSETS]:
        if not isinstance(raw, Mapping):
            continue
        canonical_id = str(raw.get("canonical_asset_id") or "").strip()
        base = str(raw.get("base") or "").strip().upper()
        volume = float(raw.get("train_worse_leg_quote_volume") or 0.0)
        if not canonical_id or not base or not math.isfinite(volume):
            continue
        if volume < MIN_TRAIN_LIQUIDITY_QUOTE:
            continue
        if canonical_id in seen_ids or base in seen_bases:
            raise ValueError(f"canonical identity collision in train liquidity ranking: {canonical_id}/{base}")
        seen_ids.add(canonical_id)
        seen_bases.add(base)
        candidates.append(
            {
                "canonical_asset_id": canonical_id,
                "base": base,
                "quote": "USDT",
                "train_worse_leg_quote_volume": volume,
            }
        )
    primary_ids = [str(value) for value in quality.get("primary_asset_ids") or []]
    if primary_ids != [row["canonical_asset_id"] for row in candidates]:
        raise ValueError("train liquidity ranking and primary_asset_ids do not match")
    if int(quality.get("surviving_asset_count") or 0) != len(candidates):
        raise ValueError("quality report surviving_asset_count does not match train-only candidates")
    if len(candidates) < MIN_SURVIVING_ASSETS:
        raise ValueError(
            "INSUFFICIENT_EXECUTABLE_UNIVERSE: "
            f"need at least {MIN_SURVIVING_ASSETS} train-liquidity survivors, observed {len(candidates)}"
        )
    return candidates


def _taker_profile() -> CostProfile:
    return replace(base_api_cost_profile(), maker_fill_probability=0.0)


def _frozen_costs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    profile = _taker_profile()
    normal_legs = [
        RouteLeg("mexc", "perp", profile.default_spread_bps, profile.default_impact_bps),
        RouteLeg("gateio", "perp", profile.default_spread_bps, profile.default_impact_bps),
    ]
    stress_legs = [
        RouteLeg("mexc", "perp", profile.default_spread_bps * 2.0, profile.default_impact_bps * 2.0),
        RouteLeg("gateio", "perp", profile.default_spread_bps * 2.0, profile.default_impact_bps * 2.0),
    ]
    return (
        profile.as_dict(),
        profile.cycle_cost(normal_legs),
        profile.cycle_cost(stress_legs, stress=True),
    )


def _validate_split(split: Mapping[str, Any]) -> dict[str, int]:
    required = (
        "warmup_days",
        "train_days",
        "oos_days",
        "train_start_sec",
        "train_end_sec",
        "oos_start_sec",
        "oos_end_sec",
    )
    try:
        normalized = {key: int(split[key]) for key in required}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("quality report split is incomplete") from exc
    if normalized["train_end_sec"] != normalized["oos_start_sec"]:
        raise ValueError("train/OOS split is not contiguous")
    if normalized["train_end_sec"] - normalized["train_start_sec"] != normalized["train_days"] * DAY_SEC:
        raise ValueError("train split day count mismatch")
    if normalized["oos_end_sec"] - normalized["oos_start_sec"] != normalized["oos_days"] * DAY_SEC:
        raise ValueError("OOS split day count mismatch")
    total_days = normalized["warmup_days"] + normalized["train_days"] + normalized["oos_days"]
    if total_days < 90:
        raise ValueError("INSUFFICIENT_DATA: fewer than 90 closed days")
    if normalized["oos_days"] < 60:
        raise ValueError("INSUFFICIENT_DATA: fewer than 60 closed OOS days")
    return normalized


def _walk_forward(split: Mapping[str, int]) -> dict[str, Any]:
    oos_days = int(split["oos_days"])
    if oos_days % 5 != 0:
        raise ValueError("OOS days must divide into five fixed folds")
    fold_days = oos_days // 5
    start = int(split["oos_start_sec"])
    folds = []
    for index in range(5):
        fold_start = start + index * fold_days * DAY_SEC
        folds.append(
            {
                "fold": index + 1,
                "start_sec": fold_start,
                "end_sec": fold_start + fold_days * DAY_SEC,
                "closed_days": fold_days,
            }
        )
    return {
        "method": "fixed_non_overlapping_oos_no_refit",
        "fold_count": 5,
        "folds": folds,
    }


def _assert_quality_embargo(quality: Mapping[str, Any]) -> None:
    if quality.get("final") is not True:
        raise ValueError("quality report must be final")
    audit = quality.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("quality report data_access_audit is missing")
    forbidden_true = (
        "returns_read",
        "pnl_read",
        "pnl_computed",
        "signals_read",
        "oos_metrics_read",
        "oos_candle_values_used_for_liquidity",
        "funding_exact_joined_to_candles",
    )
    if any(audit.get(key) is not False for key in forbidden_true):
        raise ValueError("OOS embargo was not preserved by the source quality report")


def build_plan_from_basis_v2_cache(
    quality_report_path: str | Path,
    *,
    hypothesis_bank_path: str | Path,
    goal_path: str | Path,
    created_at_utc: str | None = None,
    max_runtime_sec: int = 300,
) -> dict[str, Any]:
    runtime = _runtime(max_runtime_sec)
    quality_path = _path(quality_report_path, label="quality report")
    bank_path = _path(hypothesis_bank_path, label="hypothesis bank")
    frozen_goal_path = _path(goal_path, label="goal document")
    quality = _load_json_object(quality_path, label="quality report")
    bank = _load_json_object(bank_path, label="hypothesis bank")
    _assert_quality_embargo(quality)
    hypothesis = _find_hypothesis(bank)
    candidates = _freeze_candidates(quality)
    split = _validate_split(quality.get("split") or {})

    source_plan_path = _path(quality.get("plan_path"), label="source basis-v2 plan")
    source_plan = _load_json_object(source_plan_path, label="source basis-v2 plan")
    source_plan_hash = str(quality.get("plan_hash") or "").lower()
    if len(source_plan_hash) != 64 or str(source_plan.get("plan_hash") or "").lower() != source_plan_hash:
        raise ValueError("source basis-v2 plan_hash mismatch")
    source_plan_file_hash = _verify_hash(
        source_plan_path,
        quality.get("plan_file_sha256"),
        label="source basis-v2 plan",
    )

    train_path = _path(quality.get("train_output"), label="train source")
    oos_path = _path(quality.get("oos_output"), label="OOS source")
    funding_path = _path(quality.get("funding_output"), label="funding source")
    train_hash = _verify_hash(train_path, quality.get("train_output_sha256"), label="train source")
    oos_hash = _verify_hash(oos_path, quality.get("oos_output_sha256"), label="OOS source")
    funding_hash = _verify_hash(funding_path, quality.get("funding_output_sha256"), label="funding source")
    if int(quality.get("funding_event_count") or 0) < int(hypothesis["minimum_data"]["settlements"]):
        raise ValueError("INSUFFICIENT_DATA: funding settlements below banked minimum")

    created_at = created_at_utc or datetime.now(timezone.utc).isoformat()
    datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    profile, normal_cost, stress_cost = _frozen_costs()
    minimum_hold_carry = float(stress_cost["total_bps"]) + SAFETY_MARGIN_BPS
    minimum_daily = minimum_hold_carry / MAX_HOLDING_DAYS
    quality_hash = _sha256_file(quality_path)
    bank_hash = _sha256_file(bank_path)
    candidate_hash = _sha256_json(candidates)
    module_path = Path(__file__).resolve()

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "created_at_utc": created_at,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "evaluation_allowed": False,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_metrics": {},
        "observed_performance": {},
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "family": "cross_venue_perp_funding_regime_persistence_carry",
            "bank_record": hypothesis,
            "bank_path": str(bank_path),
            "bank_file_sha256": bank_hash,
            "materially_new_vs_closed_branches": True,
            "not_same_venue_spot_perp_carry": True,
            "not_basis_convergence_retune": True,
        },
        "goal_document": {
            "path": str(frozen_goal_path),
            "sha256": _sha256_file(frozen_goal_path),
        },
        "source_quality_report": {
            "path": str(quality_path),
            "sha256": quality_hash,
            "source_verdict": str(quality.get("verdict") or quality.get("status") or ""),
            "reuse_scope": "train_liquidity_selection_and_hash_bound_cache_only",
        },
        "source_basis_v2_plan": {
            "path": str(source_plan_path),
            "artifact_sha256": source_plan_file_hash,
            "plan_hash": source_plan_hash,
            "reuse_does_not_reopen_closed_basis_branch": True,
        },
        "sealed_input": {
            "train_path": str(train_path),
            "train_sha256": train_hash,
            "oos_path": str(oos_path),
            "oos_sha256": oos_hash,
            "funding_path": str(funding_path),
            "funding_sha256": funding_hash,
            "candle_merkle_sha256": str(quality.get("candle_merkle_sha256") or ""),
            "funding_event_merkle_sha256": str(quality.get("funding_event_merkle_sha256") or ""),
            "input_file_merkle_sha256": str(quality.get("input_file_merkle_sha256") or ""),
            "split": split,
            "train_row_count": int(quality.get("train_row_count") or 0),
            "oos_row_count": int(quality.get("oos_row_count") or 0),
            "funding_event_count": int(quality.get("funding_event_count") or 0),
        },
        "data_access_audit": {
            "planonly_fields_read": [
                "quality hashes",
                "split timestamps",
                "train liquidity ranking",
                "row and settlement counts",
            ],
            "train_values_read": False,
            "funding_rates_read": False,
            "oos_values_read": False,
            "oos_file_hash_verified": True,
            "signals_computed": False,
            "pnl_computed": False,
        },
        "universe": {
            "venues": ["mexc", "gateio"],
            "market_type": "USDT linear perpetual",
            "binance_role": "identity_exclusion_reference_only",
            "selection_uses_train_liquidity_only": True,
            "minimum_train_worse_leg_quote_volume": MIN_TRAIN_LIQUIDITY_QUOTE,
            "minimum_surviving_assets": MIN_SURVIVING_ASSETS,
            "candidate_count": len(candidates),
            "candidate_hash": candidate_hash,
            "candidates": candidates,
        },
        "strategy": {
            "route": "cross_venue_perp_perp",
            "direction": "long_lower_funding_short_higher_funding",
            "signal_source": "closed funding settlements grouped into complete UTC days",
            "funding_rate_normalization": "actual settlement cashflow; no annualization for signal or PnL",
            "regime_confirmation_complete_utc_days": REGIME_CONFIRMATION_DAYS,
            "regime_direction_rule": "same non-zero MEXC-minus-Gate daily carry sign on all confirmation days",
            "minimum_expected_hold_carry_bps": minimum_hold_carry,
            "minimum_abs_daily_funding_differential_bps": minimum_daily,
            "threshold_formula": "(stress_cycle_cost_bps + safety_margin_bps) / maximum_holding_days",
            "entry": "next contiguous 1h trade open after the complete UTC signal day",
            "exit": "two complete UTC days with nonpositive carry in the entry direction or maximum hold",
            "adverse_exit_complete_utc_days": ADVERSE_EXIT_DAYS,
            "maximum_holding_days": MAX_HOLDING_DAYS,
            "one_position_per_canonical_asset": True,
            "overlapping_positions_per_asset": False,
            "parameter_selection_on_train": False,
            "parameter_selection_on_oos": False,
            "grid_search": False,
        },
        "economics": {
            "notional_quote_per_leg": 500.0,
            "fully_collateralized": True,
            "gross_leverage": 1.0,
            "historical_execution": "taker_only",
            "cost_profile": profile,
            "cost_profile_sha256": _sha256_json(profile),
            "normal_cycle_cost": normal_cost,
            "stress_cycle_cost": stress_cost,
            "safety_margin_bps": SAFETY_MARGIN_BPS,
            "normal_funding_treatment": "actual favorable and adverse funding cashflows",
            "stress_favorable_funding_haircut": 0.5,
            "stress_adverse_funding_haircut": 1.0,
            "price_only_basis_pnl_reported_separately": True,
            "primary_acceptance_metric": "price_plus_funding_net_after_all_costs",
            "rebates_or_vip_assumed": False,
        },
        "validation": {
            "split": split,
            "oos_embargo_until_train_feasible": True,
            "walk_forward": _walk_forward(split),
            "data_gates": {
                "minimum_closed_days": 90,
                "minimum_funding_settlements": 180,
                "minimum_dual_leg_coverage": 0.8,
                "minimum_surviving_assets": MIN_SURVIVING_ASSETS,
            },
            "train_feasibility_gates": {
                "minimum_independent_regime_episodes": 10,
                "minimum_unique_signal_dates": 5,
                "both_route_directions_required": True,
                "threshold_retune_allowed": False,
                "oos_read_on_failure": False,
            },
            "oos_acceptance_gates": {
                "minimum_independent_regime_episodes": 20,
                "minimum_unique_signal_dates": 10,
                "total_net_expectancy_after_costs_gt": 0.0,
                "profit_factor_gte": 1.2,
                "positive_event_rate_gte": 0.6,
                "minimum_positive_walk_forward_folds": 4,
                "stress_total_net_pnl_gte": 0.0,
                "cluster_bootstrap_95pct_expectancy_lower_bound_gt": 0.0,
                "maximum_single_event_positive_pnl_share": 0.25,
                "maximum_single_base_positive_pnl_share": 0.25,
                "maximum_single_date_positive_pnl_share": 0.25,
                "maximum_drawdown_fraction_of_collateral": 0.1,
                "maximum_holding_days": MAX_HOLDING_DAYS,
            },
            "historical_acceptance_ceiling": "ACCEPT_FOR_EXECUTION_PROBE",
            "execution_probe_snapshots_required": 180,
        },
        "runtime_policy": {
            "plan_max_runtime_sec": runtime,
            "train_feasibility_max_runtime_sec": 1_800,
            "oos_evaluation_max_runtime_sec": 1_800,
            "network_collection_required": False,
            "visible_terminal_required_for_evaluation": True,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": _sha256_file(module_path),
            "immutable_snapshot_expected_for_project_wrapper": True,
        },
        "safety": {
            "research_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
            "grid_search": False,
            "retune_closed_branches": False,
        },
        "setup_registry_state": "PLAN_FROZEN_TRAIN_FEASIBILITY_NOT_RUN_OOS_EMBARGOED",
        "next_allowed_action": "run_hash_bound_train_feasibility",
    }
    plan["plan_hash"] = canonical_plan_hash(plan)
    validate_plan(plan, verify_files=True)
    return plan


def _assert_exact(value: Any, expected: Any, *, label: str) -> None:
    if value != expected:
        raise ValueError(f"{label} must remain frozen at {expected!r}")


def validate_plan(plan: Mapping[str, Any], *, verify_files: bool = False) -> None:
    if not isinstance(plan, Mapping) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"Unsupported plan schema: {plan.get('schema')!r}")
    if canonical_plan_hash(plan) != str(plan.get("plan_hash") or "").lower():
        raise ValueError("Plan hash mismatch; frozen configuration was modified")
    _assert_exact(plan.get("mode"), "PlanOnly", label="mode")
    for key in (
        "evaluation_allowed",
        "strategy_accepted",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        _assert_exact(plan.get(key), False, label=key)
    _assert_exact(plan.get("oos_metrics"), {}, label="oos_metrics")
    _assert_exact(plan.get("observed_performance"), {}, label="observed_performance")
    _assert_exact((plan.get("hypothesis") or {}).get("id"), HYPOTHESIS_ID, label="hypothesis.id")

    audit = plan.get("data_access_audit") or {}
    for key in ("train_values_read", "funding_rates_read", "oos_values_read", "signals_computed", "pnl_computed"):
        _assert_exact(audit.get(key), False, label=f"data_access_audit.{key}")
    _assert_exact(audit.get("oos_file_hash_verified"), True, label="data_access_audit.oos_file_hash_verified")

    strategy = plan.get("strategy") or {}
    exact_strategy = {
        "route": "cross_venue_perp_perp",
        "direction": "long_lower_funding_short_higher_funding",
        "regime_confirmation_complete_utc_days": REGIME_CONFIRMATION_DAYS,
        "adverse_exit_complete_utc_days": ADVERSE_EXIT_DAYS,
        "maximum_holding_days": MAX_HOLDING_DAYS,
        "one_position_per_canonical_asset": True,
        "overlapping_positions_per_asset": False,
        "parameter_selection_on_train": False,
        "parameter_selection_on_oos": False,
        "grid_search": False,
    }
    for key, expected in exact_strategy.items():
        _assert_exact(strategy.get(key), expected, label=f"strategy.{key}")

    profile, normal_cost, stress_cost = _frozen_costs()
    economics = plan.get("economics") or {}
    _assert_exact(economics.get("cost_profile"), profile, label="economics.cost_profile")
    _assert_exact(economics.get("cost_profile_sha256"), _sha256_json(profile), label="economics.cost_profile_sha256")
    _assert_exact(economics.get("normal_cycle_cost"), normal_cost, label="economics.normal_cycle_cost")
    _assert_exact(economics.get("stress_cycle_cost"), stress_cost, label="economics.stress_cycle_cost")
    minimum_hold = float(stress_cost["total_bps"]) + SAFETY_MARGIN_BPS
    if not math.isclose(float(strategy.get("minimum_expected_hold_carry_bps") or 0.0), minimum_hold):
        raise ValueError("strategy.minimum_expected_hold_carry_bps cost seal mismatch")
    if not math.isclose(
        float(strategy.get("minimum_abs_daily_funding_differential_bps") or 0.0),
        minimum_hold / MAX_HOLDING_DAYS,
    ):
        raise ValueError("strategy.minimum_abs_daily_funding_differential_bps cost seal mismatch")

    universe = plan.get("universe") or {}
    candidates = universe.get("candidates") or []
    if not MIN_SURVIVING_ASSETS <= len(candidates) <= MAX_CANDIDATE_ASSETS:
        raise ValueError("universe candidate count is outside frozen bounds")
    _assert_exact(universe.get("candidate_count"), len(candidates), label="universe.candidate_count")
    _assert_exact(universe.get("candidate_hash"), _sha256_json(candidates), label="universe.candidate_hash")
    _assert_exact(universe.get("selection_uses_train_liquidity_only"), True, label="universe.selection_uses_train_liquidity_only")

    sealed = plan.get("sealed_input") or {}
    split = _validate_split(sealed.get("split") or {})
    _assert_exact((plan.get("validation") or {}).get("split"), split, label="validation.split")
    _assert_exact((plan.get("validation") or {}).get("walk_forward"), _walk_forward(split), label="validation.walk_forward")
    _assert_exact((plan.get("validation") or {}).get("oos_embargo_until_train_feasible"), True, label="validation.oos_embargo_until_train_feasible")
    _assert_exact(plan.get("setup_registry_state"), "PLAN_FROZEN_TRAIN_FEASIBILITY_NOT_RUN_OOS_EMBARGOED", label="setup_registry_state")
    _assert_exact(plan.get("next_allowed_action"), "run_hash_bound_train_feasibility", label="next_allowed_action")
    runtime = int((plan.get("runtime_policy") or {}).get("plan_max_runtime_sec") or 0)
    _runtime(runtime)

    code = plan.get("code_provenance") or {}
    if len(str(code.get("module_sha256") or "")) != 64:
        raise ValueError("code_provenance.module_sha256 is missing")
    _assert_exact(
        code.get("immutable_snapshot_expected_for_project_wrapper"),
        True,
        label="code_provenance.immutable_snapshot_expected_for_project_wrapper",
    )

    if verify_files:
        checks: Sequence[tuple[str, str, str]] = (
            ("train_path", "train_sha256", "train source"),
            ("oos_path", "oos_sha256", "OOS source"),
            ("funding_path", "funding_sha256", "funding source"),
        )
        for path_key, hash_key, label in checks:
            source_path = _path(sealed.get(path_key), label=label)
            _verify_hash(source_path, sealed.get(hash_key), label=label)
        for container_key, label in (
            ("source_quality_report", "source quality report"),
            ("goal_document", "goal document"),
        ):
            container = plan.get(container_key) or {}
            source_path = _path(container.get("path"), label=label)
            _verify_hash(source_path, container.get("sha256"), label=label)
        source_plan = plan.get("source_basis_v2_plan") or {}
        source_plan_path = _path(source_plan.get("path"), label="source basis-v2 plan")
        _verify_hash(source_plan_path, source_plan.get("artifact_sha256"), label="source basis-v2 plan")
        bank_info = plan.get("hypothesis") or {}
        bank_path = _path(bank_info.get("bank_path"), label="hypothesis bank")
        _verify_hash(bank_path, bank_info.get("bank_file_sha256"), label="hypothesis bank")
        module_path = _path(code.get("module_path"), label="frozen strategy module")
        _verify_hash(module_path, code.get("module_sha256"), label="frozen strategy module")


def write_plan_from_basis_v2_cache(
    quality_report_path: str | Path,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    plan = build_plan_from_basis_v2_cache(quality_report_path, **kwargs)
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical_json(plan) + "\n").encode("utf-8")
    destination.write_bytes(encoded)
    return {
        "status": "PLAN_FROZEN_TRAIN_FEASIBILITY_NOT_RUN_OOS_EMBARGOED",
        "output_path": str(destination),
        "output_sha256": _sha256_bytes(encoded),
        "plan_hash": plan["plan_hash"],
        "next_allowed_action": plan["next_allowed_action"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Funding regime persistence v2 PlanOnly contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--quality-report", required=True)
    plan_parser.add_argument("--hypothesis-bank", required=True)
    plan_parser.add_argument("--goal", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--created-at-utc")
    plan_parser.add_argument("--max-runtime-sec", type=int, default=300)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash", required=True)
    validate_parser.add_argument("--verify-files", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "plan":
        result = write_plan_from_basis_v2_cache(
            args.quality_report,
            args.output,
            hypothesis_bank_path=args.hypothesis_bank,
            goal_path=args.goal,
            created_at_utc=args.created_at_utc,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        plan_path = _path(args.plan, label="frozen plan")
        plan = _load_json_object(plan_path, label="frozen plan")
        expected = str(args.expected_plan_hash).lower()
        if str(plan.get("plan_hash") or "").lower() != expected:
            raise ValueError("Expected plan hash does not match artifact")
        validate_plan(plan, verify_files=args.verify_files)
        result = {
            "status": "PLAN_VALID_TRAIN_FEASIBILITY_NOT_RUN_OOS_EMBARGOED",
            "plan_path": str(plan_path),
            "plan_hash": expected,
            "oos_values_read": False,
            "next_allowed_action": plan["next_allowed_action"],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
