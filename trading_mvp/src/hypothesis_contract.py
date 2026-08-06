from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from costs import base_api_cost_profile, route_legs
from feasibility_gate import (
    CANONICAL_MIN_CAPACITY_QUOTE,
    CANONICAL_MIN_DUAL_VENUE_COVERAGE,
    CANONICAL_MIN_PER_VENUE_EVENTS,
    CANONICAL_MIN_TOTAL_EVENTS,
    CANONICAL_MIN_UNIQUE_DATES,
    estimator_version_hash,
)


CONTRACT_SCHEMA = "trading_mvp_frozen_hypothesis_contract_v1"
CONTRACT_VERSION = "pit_universe_membership_drift_reversion_v1.3.0"
HYPOTHESIS_ID = "pit_universe_membership_drift_reversion_v1"
DATA_TYPE = "PIT_UNIVERSE_V2_FORWARD"
DEFAULT_FROZEN_AT_UTC = "2026-07-14T18:16:00+00:00"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hypothesis_contract_hash(contract: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in contract.items() if key != "contract_hash"})


def cost_profile_hash() -> str:
    return sha256_json(base_api_cost_profile().as_dict())


def _cycle_costs() -> tuple[dict[str, Any], dict[str, Any]]:
    taker_profile = replace(base_api_cost_profile(), maker_fill_probability=0.0)
    normal_legs = route_legs(
        "cross_venue_perp_perp",
        mexc_spread_bps=0.0,
        gate_spread_bps=0.0,
        mexc_impact_bps=2.0,
        gate_impact_bps=2.0,
        profile=taker_profile,
    )
    stress_profile = taker_profile.stress_profile()
    stress_legs = route_legs(
        "cross_venue_perp_perp",
        # Observed BBO already embeds up to 20 bps per leg. This is only the
        # additional widening needed to reach the frozen 30 bps stress spread.
        mexc_spread_bps=10.0,
        gate_spread_bps=10.0,
        mexc_impact_bps=10.0,
        gate_impact_bps=10.0,
        profile=stress_profile,
    )
    return taker_profile.cycle_cost(normal_legs), stress_profile.cycle_cost(stress_legs)


def build_pit_membership_drift_contract(
    *, frozen_at_utc: str = DEFAULT_FROZEN_AT_UTC
) -> dict[str, Any]:
    profile = base_api_cost_profile()
    normal_cost, stress_cost = _cycle_costs()
    contract: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_at_utc": frozen_at_utc,
        "id": HYPOTHESIS_ID,
        "status": "BANKED_NEEDS_NEW_DATA",
        "required_data_type": DATA_TYPE,
        "thesis": (
            "A newly reactivated venue-local linear perpetual that remains continuously tradable on the other "
            "venue can show a temporary cross-venue mid-price dislocation that mean-reverts after delayed entry."
        ),
        "frozen_parameters_no_grid": True,
        "grid_search": False,
        "retune": False,
        "universe": {
            "venues": ["mexc", "gateio"],
            "market_type": "linear_perp",
            "quote": "USDT",
            "binance_role": "reference_exclusion_only",
            "require_non_binance_spot_at_event": True,
            "require_matching_base_quote": True,
        },
        "observation_model": {
            "unit": "quality_certified_local_date",
            "source": "last_two_consistent_cycles_of_each_visible_night_segment",
            "daily_state_confirmation_cycles": 2,
            "require_consecutive_calendar_dates": True,
            "unobserved_date_gap": "break_event_and_position_sequence",
            "event_and_position_may_span_consecutive_quality_dates": True,
        },
        "event_definition": {
            "transition": "missing_to_observed_on_one_venue_while_other_remains_observed",
            "activation_confirmation_cycles": 2,
            "reference_continuity_prior_cycles": 2,
            "event_unit": "base_activation_venue_local_date",
            "dedup_cooldown_calendar_days": 30,
            "require_both_venues_successful_in_event_cycles": True,
            "tombstone_on_failed_exchange_is_not_an_event": True,
            "cycle_unit": "quality_certified_local_date",
        },
        "signal": {
            "route": "cross_venue_perp_perp",
            "side": "long_cheaper_perp_short_expensive_perp",
            "entry_delay_cycles": 1,
            "minimum_gross_dislocation_bps": 130.0,
            "max_leg_spread_bps": 20.0,
            "minimum_volume_24h_quote_per_leg": 100_000.0,
            "price_source": "next_cycle_executable_bbo",
            "one_position_per_event": True,
        },
        "position": {
            "notional_quote_per_leg": 500.0,
            "gross_leverage": 1.0,
            "margin_mode": "fully_collateralized_research_simulation",
            "simultaneous_entry_required": True,
            "partial_leg_entry": "reject_event",
            "capacity_model": {
                "source": "entry_and_exit_top_of_book_quantity",
                "required_on_entry_and_exit": True,
                "minimum_quote_per_leg": CANONICAL_MIN_CAPACITY_QUOTE,
                "missing_or_insufficient_quantity": "reject_event",
                "volume_24h_proxy_allowed": False,
            },
        },
        "exit": {
            "convergence_threshold_bps": 20.0,
            "maximum_holding_calendar_days": 3,
            "exit_price_source": "first_available_executable_bbo",
            "force_end": True,
            "take_profit_search": False,
            "stop_loss_search": False,
        },
        "robustness": {
            "scenario": "one_additional_entry_cycle_same_exit_rule",
            "entry_delay_cycles": 2,
            "cycle_cost_source": "economics.normal_cycle_cost",
            "parameter_refit": False,
        },
        "stress": {
            "scenario": "one_additional_entry_cycle_and_stress_cycle_cost",
            "entry_delay_cycles": 2,
            "cycle_cost_source": "economics.stress_cycle_cost",
            "favorable_funding": "zero",
            "adverse_funding": "retain",
            "parameter_refit": False,
        },
        "economics": {
            "cost_profile_name": profile.name,
            "cost_profile": profile.as_dict(),
            "cost_profile_sha256": cost_profile_hash(),
            "entry_order_type": "taker",
            "exit_order_type": "taker",
            "normal_cycle_cost": normal_cost,
            "stress_cycle_cost": stress_cost,
            "spread_accounting": "embedded_in_executable_bbo",
            "normal_bbo_spread_cap_bps_per_leg": 20.0,
            "stress_bbo_spread_target_bps_per_leg": 30.0,
            "normal_max_all_in_cycle_cost_bps": normal_cost["total_bps"] + 40.0,
            "stress_max_all_in_cycle_cost_bps": stress_cost["total_bps"] + 40.0,
            "funding_treatment": "reported_separately_and_cannot_rescue_negative_price_only_pnl",
            "vip_or_rebate_assumption": False,
        },
        "sample_plan": {
            "train_eligibility_days": 20,
            "train_usage": "event_frequency_and_fill_rate_only_no_return_or_threshold_optimization",
            "oos_closed_days": 100,
            "required_quality_dates": 120,
            "oos_order": "chronological_after_train_eligibility_window",
            "forward_rows_embargoed_until_contract_and_quality_seals": True,
        },
        "feasibility": {
            "must_run_before_oos": True,
            "estimator_version": "feasibility_gate_v1_wilson_lower_bound",
            "estimator_version_hash": estimator_version_hash(),
            "maximum_non_burning_infeasible_hypotheses_per_track": 2,
        },
        "validation_protocol": {
            "minimum_oos_closed_days": 60,
            "minimum_oos_portfolio_events_total": CANONICAL_MIN_TOTAL_EVENTS,
            "minimum_oos_portfolio_events_per_venue": CANONICAL_MIN_PER_VENUE_EVENTS,
            "minimum_unique_oos_signal_dates": CANONICAL_MIN_UNIQUE_DATES,
            "minimum_dual_venue_coverage": CANONICAL_MIN_DUAL_VENUE_COVERAGE,
            "price_only_expectancy_positive_each_venue": True,
            "minimum_combined_profit_factor": 1.2,
            "minimum_positive_event_rate": 0.60,
            "walk_forward": {
                "folds": 5,
                "test_days_per_fold": 20,
                "non_overlapping": True,
                "refit": False,
                "minimum_positive_combined_folds": 4,
                "minimum_positive_folds_per_venue": 3,
            },
            "normal_price_only_pnl_positive": True,
            "robustness_price_only_pnl_positive": True,
            "stress_price_only_pnl_nonnegative": True,
            "maximum_drawdown_fraction_allocated_collateral": 0.10,
            "maximum_single_event_positive_pnl_share": 0.25,
            "maximum_single_base_positive_pnl_share": 0.25,
            "maximum_single_venue_positive_pnl_share": 0.75,
            "maximum_break_even_holding_days": 3,
            "minimum_capacity_quote_per_leg": CANONICAL_MIN_CAPACITY_QUOTE,
            "maximum_historical_verdict": "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
            "deterministic_repeats": 2,
            "matching_result_hash_required": True,
        },
        "multiplicity": {
            "track_id": "pit_universe_v2_forward_track_v1",
            "hypothesis_slot": 1,
            "maximum_hypotheses_per_input_merkle": 3,
            "same_input_oos_evaluations_used_before_track": 0,
        },
        "data_access_audit": {
            "forward_market_rows_read": False,
            "returns_read": False,
            "pnl_computed": False,
            "signal_scores_computed": False,
            "network_access": False,
            "collector_started": False,
        },
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "next_allowed_action": "collect_quality_certified_pit_universe_v2_forward_under_explicit_schedule",
    }
    contract["contract_hash"] = hypothesis_contract_hash(contract)
    return contract


def _require_false(contract: dict[str, Any], key: str) -> None:
    if contract.get(key) is not False:
        raise ValueError(f"{key} must be false in frozen hypothesis contract")


def validate_hypothesis_contract(
    contract: dict[str, Any],
    *,
    expected_id: str = HYPOTHESIS_ID,
    expected_data_type: str = DATA_TYPE,
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("hypothesis contract must be a JSON object")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("mode") != "PlanOnly":
        raise ValueError(f"expected {CONTRACT_SCHEMA} PlanOnly contract")
    if contract.get("id") != expected_id:
        raise ValueError(f"hypothesis id mismatch: expected={expected_id}, observed={contract.get('id')}")
    if contract.get("required_data_type") != expected_data_type:
        raise ValueError(
            f"required_data_type mismatch: expected={expected_data_type}, observed={contract.get('required_data_type')}"
        )
    expected_hash = str(contract.get("contract_hash") or "")
    observed_hash = hypothesis_contract_hash(contract)
    if expected_hash != observed_hash:
        raise ValueError(f"contract hash mismatch: expected={expected_hash}, observed={observed_hash}")
    if contract.get("research_only") is not True or contract.get("frozen_parameters_no_grid") is not True:
        raise ValueError("research_only and frozen_parameters_no_grid must be true")
    for key in (
        "grid_search",
        "retune",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        _require_false(contract, key)

    audit = contract.get("data_access_audit")
    if not isinstance(audit, dict):
        raise ValueError("data_access_audit is required")
    for key in (
        "forward_market_rows_read",
        "returns_read",
        "pnl_computed",
        "signal_scores_computed",
        "network_access",
        "collector_started",
    ):
        if audit.get(key) is not False:
            raise ValueError(f"data_access_audit.{key} must be false")

    economics = contract.get("economics")
    if not isinstance(economics, dict):
        raise ValueError("economics is required")
    profile = base_api_cost_profile().as_dict()
    if economics.get("cost_profile") != profile or economics.get("cost_profile_sha256") != cost_profile_hash():
        raise ValueError("economics must seal the current base_api cost profile")
    normal_cost, stress_cost = _cycle_costs()
    if economics.get("normal_cycle_cost") != normal_cost or economics.get("stress_cycle_cost") != stress_cost:
        raise ValueError("economics cycle cost seal mismatch")
    if economics.get("spread_accounting") != "embedded_in_executable_bbo":
        raise ValueError("economics spread must be embedded in executable BBO prices")
    if float(normal_cost.get("spread_bps") or 0.0) != 0.0:
        raise ValueError("normal model cost must not double-count BBO spread")
    normal_spread_cap = float(economics.get("normal_bbo_spread_cap_bps_per_leg") or 0.0)
    stress_spread_target = float(economics.get("stress_bbo_spread_target_bps_per_leg") or 0.0)
    if normal_spread_cap != 20.0 or stress_spread_target < normal_spread_cap:
        raise ValueError("invalid frozen BBO spread caps")
    normal_all_in = float(normal_cost["total_bps"]) + normal_spread_cap * 2.0
    stress_all_in = float(stress_cost["total_bps"]) + normal_spread_cap * 2.0
    if float(economics.get("normal_max_all_in_cycle_cost_bps") or 0.0) != normal_all_in:
        raise ValueError("normal all-in cost seal mismatch")
    if float(economics.get("stress_max_all_in_cycle_cost_bps") or 0.0) != stress_all_in:
        raise ValueError("stress all-in cost seal mismatch")
    signal = contract.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("signal is required")
    if float(signal.get("minimum_gross_dislocation_bps") or 0.0) <= normal_all_in:
        raise ValueError("signal.minimum_gross_dislocation_bps must exceed normal all-in round-trip costs")

    observation = contract.get("observation_model")
    if not isinstance(observation, dict):
        raise ValueError("observation_model is required")
    if observation.get("unit") != "quality_certified_local_date":
        raise ValueError("observation_model.unit must be quality_certified_local_date")
    if int(observation.get("daily_state_confirmation_cycles") or 0) < 2:
        raise ValueError("observation_model requires at least two confirming cycles")
    if observation.get("require_consecutive_calendar_dates") is not True:
        raise ValueError("observation_model must require consecutive calendar dates")

    position = contract.get("position")
    if not isinstance(position, dict):
        raise ValueError("position is required")
    capacity_model = position.get("capacity_model")
    if not isinstance(capacity_model, dict):
        raise ValueError("position.capacity_model is required")
    if capacity_model.get("source") != "entry_and_exit_top_of_book_quantity":
        raise ValueError("position.capacity_model.source must use entry and exit top-of-book quantity")
    if capacity_model.get("required_on_entry_and_exit") is not True:
        raise ValueError("position.capacity_model.required_on_entry_and_exit must be true")
    if capacity_model.get("missing_or_insufficient_quantity") != "reject_event":
        raise ValueError("position.capacity_model.missing_or_insufficient_quantity must reject the event")
    if capacity_model.get("volume_24h_proxy_allowed") is not False:
        raise ValueError("position.capacity_model.volume_24h_proxy_allowed must be false")
    if float(capacity_model.get("minimum_quote_per_leg") or 0.0) < CANONICAL_MIN_CAPACITY_QUOTE:
        raise ValueError(
            f"position.capacity_model.minimum_quote_per_leg must be at least {CANONICAL_MIN_CAPACITY_QUOTE}"
        )

    sample = contract.get("sample_plan")
    if not isinstance(sample, dict):
        raise ValueError("sample_plan is required")
    if int(sample.get("train_eligibility_days") or 0) < 1:
        raise ValueError("sample_plan.train_eligibility_days must be positive")
    if int(sample.get("oos_closed_days") or 0) < 60:
        raise ValueError("sample_plan.oos_closed_days must be at least 60")
    if int(sample.get("required_quality_dates") or 0) < (
        int(sample["train_eligibility_days"]) + int(sample["oos_closed_days"])
    ):
        raise ValueError("sample_plan.required_quality_dates must cover train plus OOS days")

    feasibility = contract.get("feasibility")
    if not isinstance(feasibility, dict) or feasibility.get("must_run_before_oos") is not True:
        raise ValueError("feasibility must run before OOS")
    if feasibility.get("estimator_version_hash") != estimator_version_hash():
        raise ValueError("feasibility estimator version hash mismatch")

    protocol = contract.get("validation_protocol")
    if not isinstance(protocol, dict):
        raise ValueError("validation_protocol is required")
    minimum_rules = {
        "minimum_oos_closed_days": 60,
        "minimum_oos_portfolio_events_total": CANONICAL_MIN_TOTAL_EVENTS,
        "minimum_oos_portfolio_events_per_venue": CANONICAL_MIN_PER_VENUE_EVENTS,
        "minimum_unique_oos_signal_dates": CANONICAL_MIN_UNIQUE_DATES,
        "minimum_dual_venue_coverage": CANONICAL_MIN_DUAL_VENUE_COVERAGE,
        "minimum_combined_profit_factor": 1.2,
        "minimum_positive_event_rate": 0.60,
        "minimum_capacity_quote_per_leg": CANONICAL_MIN_CAPACITY_QUOTE,
    }
    for key, minimum in minimum_rules.items():
        if float(protocol.get(key) or 0.0) < float(minimum):
            raise ValueError(f"validation_protocol.{key} must be at least {minimum}")
    maximum_rules = {
        "maximum_drawdown_fraction_allocated_collateral": 0.10,
        "maximum_single_event_positive_pnl_share": 0.25,
        "maximum_single_base_positive_pnl_share": 0.25,
        "maximum_single_venue_positive_pnl_share": 0.75,
        "maximum_break_even_holding_days": 3.0,
    }
    for key, maximum in maximum_rules.items():
        if float(protocol.get(key) if protocol.get(key) is not None else maximum + 1.0) > maximum:
            raise ValueError(f"validation_protocol.{key} must be at most {maximum}")
    for key in (
        "price_only_expectancy_positive_each_venue",
        "normal_price_only_pnl_positive",
        "robustness_price_only_pnl_positive",
        "stress_price_only_pnl_nonnegative",
        "matching_result_hash_required",
    ):
        if protocol.get(key) is not True:
            raise ValueError(f"validation_protocol.{key} must be true")
    walk_forward = protocol.get("walk_forward")
    if not isinstance(walk_forward, dict):
        raise ValueError("validation_protocol.walk_forward is required")
    if int(walk_forward.get("folds") or 0) < 5 or int(walk_forward.get("test_days_per_fold") or 0) < 20:
        raise ValueError("walk_forward requires at least five 20-day folds")
    if walk_forward.get("refit") is not False:
        raise ValueError("walk_forward.refit must be false")
    if walk_forward.get("non_overlapping") is not True:
        raise ValueError("walk_forward.non_overlapping must be true")
    required_oos_days = int(walk_forward["folds"]) * int(walk_forward["test_days_per_fold"])
    if int(sample["oos_closed_days"]) < required_oos_days:
        raise ValueError("sample_plan.oos_closed_days must cover all non-overlapping walk-forward folds")
    if int(sample["required_quality_dates"]) != int(sample["train_eligibility_days"]) + int(
        sample["oos_closed_days"]
    ):
        raise ValueError("sample_plan.required_quality_dates must equal train plus OOS days")
    if int(walk_forward.get("minimum_positive_combined_folds") or 0) < 4:
        raise ValueError("walk_forward.minimum_positive_combined_folds must be at least four")
    if int(walk_forward.get("minimum_positive_folds_per_venue") or 0) < 3:
        raise ValueError("walk_forward.minimum_positive_folds_per_venue must be at least three")

    robustness = contract.get("robustness")
    stress = contract.get("stress")
    if not isinstance(robustness, dict) or int(robustness.get("entry_delay_cycles") or 0) != 2:
        raise ValueError("robustness must use exactly two entry-delay cycles")
    if robustness.get("parameter_refit") is not False:
        raise ValueError("robustness.parameter_refit must be false")
    if not isinstance(stress, dict) or int(stress.get("entry_delay_cycles") or 0) != 2:
        raise ValueError("stress must use exactly two entry-delay cycles")
    if stress.get("parameter_refit") is not False:
        raise ValueError("stress.parameter_refit must be false")

    multiplicity = contract.get("multiplicity")
    if not isinstance(multiplicity, dict):
        raise ValueError("multiplicity is required")
    slot = int(multiplicity.get("hypothesis_slot") or 0)
    if not 1 <= slot <= 3:
        raise ValueError("multiplicity.hypothesis_slot must be in [1, 3]")
    if int(multiplicity.get("maximum_hypotheses_per_input_merkle") or 0) > 3:
        raise ValueError("multiplicity.maximum_hypotheses_per_input_merkle must be <= 3")

    return {
        "schema": CONTRACT_SCHEMA,
        "verdict": "VALID",
        "hypothesis_id": expected_id,
        "required_data_type": expected_data_type,
        "contract_hash": expected_hash,
        "required_quality_dates": int(sample["required_quality_dates"]),
        "forward_data_read": False,
        "returns_read": False,
        "pnl_computed": False,
    }
