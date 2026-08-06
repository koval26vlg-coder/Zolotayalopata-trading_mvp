from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import dense_ws_campaign_contract as campaign
except ModuleNotFoundError:  # pragma: no cover - package import path
    from . import dense_ws_campaign_contract as campaign


DRAFT_SCHEMA = "trading_mvp_dense_ws_signal_evaluator_review_draft_v1"
DRAFT_STATUS = "DRAFT_NOT_FROZEN_NOT_AUTHORIZED"
DRAFT_MODE = "PlanOnlyReviewDraft"
NEXT_ACTION = "USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT"


class DraftIntegrityError(ValueError):
    """The review draft or its immutable campaign binding was changed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DraftIntegrityError(f"invalid JSON object: {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise DraftIntegrityError(f"expected JSON object: {target}")
    return value


def _expect(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise DraftIntegrityError(
            f"{label} mismatch: expected {expected!r}, observed {actual!r}"
        )


def _expect_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DraftIntegrityError(f"{label} must be an object")
    return value


def _expect_sha256(value: Any, *, label: str) -> str:
    normalized = str(value or "").lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise DraftIntegrityError(f"{label} must be a lowercase SHA-256 value")
    return normalized


def canonical_draft_hash(draft: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in draft.items() if key != "draft_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _safety_contract() -> dict[str, bool]:
    return {
        "network_access": False,
        "returns_read": False,
        "pnl_computed": False,
        "oos_read": False,
        "grid_or_retune": False,
        "paper_forward": False,
        "live_orders": False,
        "private_api_keys": False,
        "real_capital": False,
        "leverage_or_margin": False,
    }


def _frozen_source_scope() -> dict[str, Any]:
    return {
        "execution_sampling_contract": {
            "sample_clock": (
                "UTC epoch boundaries where timestamp modulo 5 seconds is zero"
            ),
            "sample_interval_sec": 5,
            "quote_selection": (
                "latest BBO with recv_ts <= sample_ts; never nearest or "
                "forward-filled from a future row"
            ),
            "max_quote_age_ms": {"mexc": 6000, "gateio": 5000},
            "max_cross_venue_recv_ts_skew_ms": 2000,
            "max_spread_bps_each_venue": 3.0,
            "min_top_notional_quote_each_side": 25.0,
            "eligible_regime": "DENSE_BOTH",
            "one_snapshot_per_base_per_boundary": True,
            "stale_or_incomplete_snapshot_action": "exclude and count by reason",
            "minimum_eligible_snapshots": 180,
            "execution_mode_for_future_evaluation": "taker_at_opposite_top_of_book",
            "maker_fill_or_queue_assumption": False,
        },
        "cost_risk_no_grid_contract": {
            "cost": {
                "base_tier_only": True,
                "normal": {
                    "round_trip_fee_bps": 39.0,
                    "slippage_bps": 10.0,
                    "inventory_rebalance_buffer_bps": 20.0,
                    "total_cost_bps": 69.0,
                },
                "stress": {
                    "round_trip_fee_bps": 39.0,
                    "slippage_bps": 20.0,
                    "inventory_rebalance_buffer_bps": 30.0,
                    "total_cost_bps": 89.0,
                },
                "fee_tier_optimism": False,
                "maker_rebate_credit": False,
                "transfer_latency_benefit": False,
            },
            "risk": {
                "research_simulation_only": True,
                "direction": "long_only_spot_no_short",
                "notional_quote_per_synthetic_trade": 50.0,
                "max_concurrent_synthetic_positions": 3,
                "max_gross_synthetic_exposure_quote": 150.0,
                "max_holding_sec": 25,
                "cooldown_sec_per_base": 60,
                "one_position_per_base": True,
                "leverage": False,
                "margin": False,
                "real_capital": False,
            },
            "no_grid": {
                "parameter_combinations": 1,
                "grid_search": False,
                "retune": False,
                "threshold_selection_from_returns_or_pnl": False,
                "threshold_selection_from_oos": False,
            },
        },
        "future_split_if_separately_authorized": {
            "ordering": "valid observations sorted by causal sample_ts",
            "train_fraction": 0.7,
            "oos_fraction": 0.3,
            "split_type": "single contiguous chronological split",
            "embargo_sec": 300,
            "regime_parameters_refit_on_oos": False,
        },
    }


def _signal_contract(source_scope: Mapping[str, Any]) -> dict[str, Any]:
    _expect(dict(source_scope), _frozen_source_scope(), label="source_scope")
    execution = _expect_mapping(
        source_scope.get("execution_sampling_contract"),
        label="source_scope.execution_sampling_contract",
    )
    cost_risk = _expect_mapping(
        source_scope.get("cost_risk_no_grid_contract"),
        label="source_scope.cost_risk_no_grid_contract",
    )
    cost = _expect_mapping(cost_risk.get("cost"), label="cost")
    normal = _expect_mapping(cost.get("normal"), label="cost.normal")
    stress = _expect_mapping(cost.get("stress"), label="cost.stress")
    risk = _expect_mapping(cost_risk.get("risk"), label="risk")
    no_grid = _expect_mapping(cost_risk.get("no_grid"), label="no_grid")

    _expect(execution.get("eligible_regime"), "DENSE_BOTH", label="eligible_regime")
    _expect(
        execution.get("execution_mode_for_future_evaluation"),
        "taker_at_opposite_top_of_book",
        label="execution_mode_for_future_evaluation",
    )
    _expect(execution.get("maker_fill_or_queue_assumption"), False, label="maker_fill")
    _expect(normal.get("total_cost_bps"), 69.0, label="normal.total_cost_bps")
    _expect(stress.get("total_cost_bps"), 89.0, label="stress.total_cost_bps")
    _expect(
        risk.get("direction"),
        "long_only_spot_no_short",
        label="risk.direction",
    )
    _expect(
        risk.get("notional_quote_per_synthetic_trade"),
        50.0,
        label="risk.notional_quote_per_synthetic_trade",
    )
    _expect(risk.get("cooldown_sec_per_base"), 60, label="risk.cooldown_sec_per_base")
    _expect(no_grid.get("parameter_combinations"), 1, label="parameter_combinations")
    for key in (
        "grid_search",
        "retune",
        "threshold_selection_from_returns_or_pnl",
        "threshold_selection_from_oos",
    ):
        _expect(no_grid.get(key), False, label=f"no_grid.{key}")

    return {
        "source_snapshot_schema": "trading_mvp_dense_ws_execution_snapshot_v1",
        "eligible_regime": "DENSE_BOTH",
        "directions": ["buy_mexc_sell_gateio", "buy_gateio_sell_mexc"],
        "buy_price_field": "ask_price",
        "sell_price_field": "bid_price",
        "gross_edge_bps_formula": "(sell_bid / buy_ask - 1) * 10000",
        "capacity_quote_formula": (
            "min(buy_ask * buy_ask_qty, sell_bid * sell_bid_qty)"
        ),
        "minimum_capacity_quote": 50.0,
        "normal_total_cost_bps": 69.0,
        "stress_total_cost_bps": 89.0,
        "normal_net_edge_bps_formula": "gross_edge_bps - 69",
        "stress_net_edge_bps_formula": "gross_edge_bps - 89",
        "event_clock": "causal sample_ts",
        "cooldown_sec_per_base_and_direction": 60,
        "one_event_per_base_direction_per_cooldown": True,
        "inventory_model": (
            "pre_positioned_spot_inventory_research_simulation_only"
        ),
        "inventory_rebalance_buffer_credited": False,
        "maker_fill_assumption": False,
        "short_sale": False,
        "parameter_combinations": 1,
        "threshold_learned_from_returns_pnl_or_oos": False,
    }


def _evaluation_design(source_scope: Mapping[str, Any]) -> dict[str, Any]:
    split = _expect_mapping(
        source_scope.get("future_split_if_separately_authorized"),
        label="source_scope.future_split_if_separately_authorized",
    )
    expected_split = {
        "ordering": "valid observations sorted by causal sample_ts",
        "train_fraction": 0.7,
        "oos_fraction": 0.3,
        "split_type": "single contiguous chronological split",
        "embargo_sec": 300,
        "regime_parameters_refit_on_oos": False,
    }
    _expect(dict(split), expected_split, label="future chronological split")
    return {
        "input_ordering": expected_split["ordering"],
        "primary_split": {
            "train_fraction": 0.7,
            "oos_fraction": 0.3,
            "split_type": "single contiguous chronological split",
            "embargo_sec": 300,
        },
        "walk_forward": {
            "folds": 5,
            "ordering": "chronological",
            "formula_refit_between_folds": False,
            "regime_parameters_refit_on_oos": False,
        },
        "required_reports": [
            "train",
            "chronological_oos",
            "five_fold_walk_forward",
            "normal_cost_economics",
            "stress_cost_economics",
            "drawdown_sample_size_capacity_fill_risk",
        ],
        "downstream_stops_on_first_failed_gate": True,
    }


def _acceptance_review() -> dict[str, Any]:
    unset = "UNSET_REQUIRES_USER_REVIEW"
    return {
        "minimum_trade_events": unset,
        "minimum_net_expectancy_bps": unset,
        "minimum_profit_factor": unset,
        "maximum_drawdown_quote": unset,
        "minimum_oos_fold_passes": unset,
        "minimum_stress_expectancy_bps": unset,
        "minimum_capacity_quote": 50.0,
        "strategy_accepted": False,
        "terminal_verdict_allowed": False,
    }


def _validate_campaign_sources(
    campaign_plan: Mapping[str, Any],
    campaign_contract: Mapping[str, Any],
) -> None:
    _expect(campaign_plan.get("schema"), campaign.PLAN_SCHEMA, label="plan.schema")
    _expect(
        campaign_contract.get("schema"),
        campaign.CONTRACT_SCHEMA,
        label="contract.schema",
    )
    for label, source in (
        ("plan", campaign_plan),
        ("contract", campaign_contract),
    ):
        _expect(
            source.get("campaign_id"),
            campaign.AEF_CAMPAIGN_ID,
            label=f"{label}.campaign_id",
        )
        _expect(
            source.get("hypothesis_id"),
            campaign.HYPOTHESIS_ID,
            label=f"{label}.hypothesis_id",
        )
        _expect(
            source.get("data_type"),
            campaign.DATA_TYPE,
            label=f"{label}.data_type",
        )
    plan_hash = _expect_sha256(campaign_plan.get("plan_hash"), label="plan.plan_hash")
    contract_hash = _expect_sha256(
        campaign_contract.get("contract_hash"), label="contract.contract_hash"
    )
    _expect(
        campaign.canonical_plan_hash(campaign_plan),
        plan_hash,
        label="plan canonical hash",
    )
    _expect(
        campaign.canonical_contract_hash(campaign_contract),
        contract_hash,
        label="contract canonical hash",
    )
    plan_contract = _expect_mapping(campaign_plan.get("contract"), label="plan.contract")
    _expect(
        plan_contract.get("contract_hash"),
        contract_hash,
        label="plan.contract.contract_hash",
    )


def build_review_draft(
    *,
    campaign_plan: Mapping[str, Any],
    campaign_contract: Mapping[str, Any],
    plan_path: str | Path,
    plan_file_sha256: str,
    contract_path: str | Path,
    contract_file_sha256: str,
) -> dict[str, Any]:
    _validate_campaign_sources(campaign_plan, campaign_contract)
    plan_sha = _expect_sha256(plan_file_sha256, label="plan_file_sha256")
    contract_sha = _expect_sha256(
        contract_file_sha256, label="contract_file_sha256"
    )
    evidence = _expect_mapping(
        campaign_contract.get("evidence_and_acceptance_contract"),
        label="evidence_and_acceptance_contract",
    )
    split = _expect_mapping(
        evidence.get("future_split_if_separately_authorized"),
        label="future_split_if_separately_authorized",
    )
    source_scope = {
        "execution_sampling_contract": copy.deepcopy(
            campaign_contract["execution_sampling_contract"]
        ),
        "cost_risk_no_grid_contract": copy.deepcopy(
            campaign_contract["cost_risk_no_grid_contract"]
        ),
        "future_split_if_separately_authorized": copy.deepcopy(split),
    }
    _expect(source_scope, _frozen_source_scope(), label="campaign source_scope")
    draft: dict[str, Any] = {
        "schema": DRAFT_SCHEMA,
        "mode": DRAFT_MODE,
        "status": DRAFT_STATUS,
        "research_only": True,
        "source_campaign": {
            "campaign_id": campaign.AEF_CAMPAIGN_ID,
            "hypothesis_id": campaign.HYPOTHESIS_ID,
            "data_type": campaign.DATA_TYPE,
            "plan": {
                "path": str(Path(plan_path).expanduser().resolve()),
                "file_sha256": plan_sha,
                "plan_hash": campaign_plan["plan_hash"],
            },
            "contract": {
                "path": str(Path(contract_path).expanduser().resolve()),
                "file_sha256": contract_sha,
                "contract_hash": campaign_contract["contract_hash"],
            },
        },
        "source_scope": source_scope,
        "signal_contract": _signal_contract(source_scope),
        "evaluation_design": _evaluation_design(source_scope),
        "acceptance_review": _acceptance_review(),
        "evaluation_authorization": {
            "authorized": False,
            "status": "USER_REVIEW_REQUIRED",
            "materialization_binding_present": False,
            "returns_pnl_oos_allowed": False,
            "reason": (
                "acceptance thresholds and exact materialization output hashes are "
                "not frozen"
            ),
        },
        "safety": _safety_contract(),
        "next_allowed_action": NEXT_ACTION,
    }
    draft["draft_hash"] = canonical_draft_hash(draft)
    validate_review_draft(draft)
    return draft


def validate_review_draft(
    draft: Mapping[str, Any],
    *,
    verify_source_files: bool = False,
) -> None:
    observed_hash = _expect_sha256(draft.get("draft_hash"), label="draft_hash")
    if canonical_draft_hash(draft) != observed_hash:
        raise DraftIntegrityError("draft hash mismatch; review draft was modified")
    expected_top_level_fields = {
        "schema",
        "mode",
        "status",
        "research_only",
        "source_campaign",
        "source_scope",
        "signal_contract",
        "evaluation_design",
        "acceptance_review",
        "evaluation_authorization",
        "safety",
        "next_allowed_action",
        "draft_hash",
    }
    _expect(
        set(draft),
        expected_top_level_fields,
        label="draft top-level fields",
    )
    _expect(draft.get("schema"), DRAFT_SCHEMA, label="draft.schema")
    _expect(draft.get("mode"), DRAFT_MODE, label="draft.mode")
    _expect(draft.get("status"), DRAFT_STATUS, label="draft.status")
    _expect(draft.get("research_only"), True, label="draft.research_only")
    _expect(draft.get("next_allowed_action"), NEXT_ACTION, label="next_allowed_action")

    authorization = _expect_mapping(
        draft.get("evaluation_authorization"), label="evaluation_authorization"
    )
    _expect(authorization.get("authorized"), False, label="evaluation_authorization.authorized")
    _expect(
        authorization.get("status"),
        "USER_REVIEW_REQUIRED",
        label="evaluation_authorization.status",
    )
    _expect(
        authorization.get("materialization_binding_present"),
        False,
        label="evaluation_authorization.materialization_binding_present",
    )
    _expect(
        authorization.get("returns_pnl_oos_allowed"),
        False,
        label="evaluation_authorization.returns_pnl_oos_allowed",
    )
    safety = _expect_mapping(draft.get("safety"), label="safety")
    _expect(dict(safety), _safety_contract(), label="safety")

    source_campaign = _expect_mapping(
        draft.get("source_campaign"), label="source_campaign"
    )
    _expect(
        source_campaign.get("campaign_id"),
        campaign.AEF_CAMPAIGN_ID,
        label="source_campaign.campaign_id",
    )
    _expect(
        source_campaign.get("hypothesis_id"),
        campaign.HYPOTHESIS_ID,
        label="source_campaign.hypothesis_id",
    )
    plan_binding = _expect_mapping(source_campaign.get("plan"), label="source_campaign.plan")
    contract_binding = _expect_mapping(
        source_campaign.get("contract"), label="source_campaign.contract"
    )
    for label, binding, internal_key in (
        ("plan", plan_binding, "plan_hash"),
        ("contract", contract_binding, "contract_hash"),
    ):
        _expect_sha256(binding.get("file_sha256"), label=f"{label}.file_sha256")
        _expect_sha256(binding.get(internal_key), label=f"{label}.{internal_key}")
        if not str(binding.get("path") or ""):
            raise DraftIntegrityError(f"{label}.path is empty")

    source_scope = _expect_mapping(draft.get("source_scope"), label="source_scope")
    _expect(
        draft.get("signal_contract"),
        _signal_contract(source_scope),
        label="signal_contract",
    )
    _expect(
        draft.get("evaluation_design"),
        _evaluation_design(source_scope),
        label="evaluation_design",
    )
    _expect(
        draft.get("acceptance_review"),
        _acceptance_review(),
        label="acceptance_review",
    )

    if verify_source_files:
        plan_path = Path(str(plan_binding["path"])).expanduser().resolve()
        contract_path = Path(str(contract_binding["path"])).expanduser().resolve()
        _expect(
            _sha256_file(plan_path),
            plan_binding["file_sha256"],
            label="current plan file SHA-256",
        )
        _expect(
            _sha256_file(contract_path),
            contract_binding["file_sha256"],
            label="current contract file SHA-256",
        )
        plan = _read_json(plan_path)
        contract = _read_json(contract_path)
        campaign.validate_contract(contract, verify_files=True)
        campaign.validate_plan(
            plan,
            contract=contract,
            verify_files=True,
            allow_v3_timing=True,
        )
        _expect(plan.get("plan_hash"), plan_binding["plan_hash"], label="current plan_hash")
        _expect(
            contract.get("contract_hash"),
            contract_binding["contract_hash"],
            label="current contract_hash",
        )


def build_review_draft_from_policy(policy_path: str | Path) -> dict[str, Any]:
    policy = _read_json(policy_path)
    candidate = _expect_mapping(
        policy.get("next_long_campaign"), label="policy.next_long_campaign"
    )
    _expect(
        candidate.get("campaign_id"),
        campaign.AEF_CAMPAIGN_ID,
        label="policy campaign_id",
    )
    approval = _expect_mapping(
        candidate.get("user_launch_approval"), label="user_launch_approval"
    )
    _expect(approval.get("status"), "APPROVED", label="user_launch_approval.status")
    plan_path = Path(str(candidate.get("plan_path") or "")).expanduser().resolve()
    contract_path = Path(str(candidate.get("contract_path") or "")).expanduser().resolve()
    plan_sha = _expect_sha256(
        candidate.get("plan_file_sha256"), label="policy.plan_file_sha256"
    )
    contract_sha = _expect_sha256(
        candidate.get("contract_file_sha256"), label="policy.contract_file_sha256"
    )
    _expect(_sha256_file(plan_path), plan_sha, label="plan file SHA-256")
    _expect(_sha256_file(contract_path), contract_sha, label="contract file SHA-256")
    plan = _read_json(plan_path)
    contract = _read_json(contract_path)
    campaign.validate_contract(contract, verify_files=True)
    campaign.validate_plan(
        plan,
        contract=contract,
        verify_files=True,
        allow_v3_timing=True,
    )
    _expect(plan.get("plan_hash"), candidate.get("plan_hash"), label="policy plan_hash")
    _expect(
        contract.get("contract_hash"),
        candidate.get("contract_hash"),
        label="policy contract_hash",
    )
    return build_review_draft(
        campaign_plan=plan,
        campaign_contract=contract,
        plan_path=plan_path,
        plan_file_sha256=plan_sha,
        contract_path=contract_path,
        contract_file_sha256=contract_sha,
    )


def write_new_review_draft(path: str | Path, draft: Mapping[str, Any]) -> Path:
    validate_review_draft(draft)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(draft, ensure_ascii=False, indent=2) + "\n"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise DraftIntegrityError(f"refusing to overwrite review draft: {target}") from exc
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate the non-authoritative dense WS signal review draft."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--policy", required=True)
    build.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--draft", required=True)
    validate.add_argument("--verify-source-files", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        draft = build_review_draft_from_policy(args.policy)
        target = write_new_review_draft(args.output, draft)
        result = {
            "status": "DRAFT_WRITTEN_NOT_AUTHORIZED",
            "output": str(target),
            "draft_hash": draft["draft_hash"],
            "next_allowed_action": draft["next_allowed_action"],
        }
    else:
        draft = _read_json(args.draft)
        validate_review_draft(
            draft,
            verify_source_files=bool(args.verify_source_files),
        )
        result = {
            "status": "VALID_REVIEW_DRAFT_NOT_AUTHORIZED",
            "draft": str(Path(args.draft).expanduser().resolve()),
            "draft_hash": draft["draft_hash"],
            "next_allowed_action": draft["next_allowed_action"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
