from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import dense_ws_campaign_contract as campaign
    import dense_ws_signal_evaluator_contract as signal
except ModuleNotFoundError:  # pragma: no cover - package import path
    from . import dense_ws_campaign_contract as campaign
    from . import dense_ws_signal_evaluator_contract as signal


PROPOSAL_SCHEMA = "trading_mvp_dense_ws_acceptance_proposal_v1"
PROPOSAL_MODE = "PlanOnlyReviewProposal"
PROPOSAL_STATUS = "PROPOSAL_NOT_FROZEN_NOT_AUTHORIZED"
NEXT_ACTION = "USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT"


class ProposalIntegrityError(ValueError):
    """The proposal or its source review binding is inconsistent."""


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
        raise ProposalIntegrityError(f"invalid JSON object: {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProposalIntegrityError(f"expected JSON object: {target}")
    return value


def _expect(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise ProposalIntegrityError(
            f"{label} mismatch: expected {expected!r}, observed {actual!r}"
        )


def _expect_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProposalIntegrityError(f"{label} must be an object")
    return value


def _expect_sha256(value: Any, *, label: str) -> str:
    normalized = str(value or "").lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ProposalIntegrityError(f"{label} must be a lowercase SHA-256 value")
    return normalized


def canonical_proposal_hash(proposal: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in proposal.items() if key != "proposal_hash"}
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


def _gap_audit() -> dict[str, Any]:
    return {
        "status": "GAPS_RESOLVED_IN_PROPOSAL_REQUIRES_USER_REVIEW",
        "source_draft_gaps": [
            "trade trigger threshold was not explicit",
            "execution latency and outcome quote selection were not explicit",
            "unfillable events had no denominator treatment",
            "day-compatible sample thresholds were unset",
            "maximum historical verdict was unset",
        ],
        "why_it_matters": (
            "Without these fields, displayed crossed quotes could be mistaken for "
            "executable profit and acceptance could be chosen after results are seen."
        ),
    }


def _signal_trigger_proposal() -> dict[str, Any]:
    return {
        "eligible_regime": "DENSE_BOTH",
        "directions": ["buy_mexc_sell_gateio", "buy_gateio_sell_mexc"],
        "displayed_gross_edge_bps_formula": "(sell_bid / buy_ask - 1) * 10000",
        "displayed_normal_net_edge_bps_formula": "displayed_gross_edge_bps - 69",
        "trigger_when_displayed_normal_net_edge_bps_gt": 0.0,
        "minimum_displayed_capacity_quote": 50.0,
        "cooldown_sec_per_base_and_direction": 60,
        "one_event_per_base_direction_per_cooldown": True,
        "event_selected_before_outcome_quotes": True,
        "threshold_learned_from_returns_pnl_or_oos": False,
        "parameter_combinations": 1,
    }


def _execution_realization_proposal() -> dict[str, Any]:
    return {
        "source": "same immutable campaign raw BBO stream and causal materialization",
        "normal_latency_ms": 250,
        "stress_latency_ms": 1000,
        "execution_ts_formula": "signal_sample_ts + latency_ms / 1000",
        "outcome_quote_selection": (
            "latest raw BBO with recv_ts <= execution_ts; no future quote"
        ),
        "future_rows_allowed_for_signal": False,
        "future_rows_allowed_only_for_outcome_measurement": True,
        "max_quote_age_ms": {"mexc": 6000, "gateio": 5000},
        "max_cross_venue_recv_ts_skew_ms": 2000,
        "minimum_execution_capacity_quote_each_leg": 50.0,
        "both_legs_required": True,
        "unfillable_events_remain_in_fill_rate_denominator": True,
        "paired_fill_gross_edge_bps_formula": (
            "(execution_sell_bid / execution_buy_ask - 1) * 10000"
        ),
        "normal_total_cost_bps": 69.0,
        "stress_total_cost_bps": 89.0,
        "normal_net_edge_bps_formula": "paired_fill_gross_edge_bps - 69",
        "stress_net_edge_bps_formula": "paired_fill_gross_edge_bps - 89",
        "maker_fill_or_queue_assumption": False,
        "one_leg_fill_profit_credited": False,
    }


def _acceptance_thresholds() -> dict[str, Any]:
    return {
        "sample": {
            "minimum_total_independent_events": 60,
            "minimum_train_events": 40,
            "minimum_oos_events": 20,
            "minimum_events_per_walk_forward_fold": 8,
            "minimum_distinct_utc_hours": 8,
            "minimum_distinct_bases": 8,
            "minimum_events_per_direction": 10,
            "independence_rule": "60-second cooldown per base and direction",
            "below_minimum_action": "INSUFFICIENT_DATA_NOT_REJECTED",
        },
        "economics": {
            "oos_normal_net_expectancy_bps_gt": 0.0,
            "oos_normal_net_pnl_quote_gt": 0.0,
            "oos_normal_profit_factor_gte": 1.2,
            "oos_cluster_block_bootstrap_95pct_expectancy_lower_bound_gt": 0.0,
            "oos_stress_net_expectancy_bps_gte": 0.0,
            "oos_stress_net_pnl_quote_gte": 0.0,
            "oos_stress_profit_factor_gte": 1.0,
            "each_direction_oos_normal_expectancy_bps_gte": 0.0,
        },
        "robustness": {
            "walk_forward_folds": 5,
            "minimum_positive_walk_forward_folds": 4,
            "minimum_normal_paired_fill_rate": 0.95,
            "minimum_stress_paired_fill_rate": 0.90,
            "maximum_drawdown_fraction_allocated_capital": 0.10,
            "allocated_capital_quote": 150.0,
            "maximum_drawdown_quote": 15.0,
            "maximum_single_event_positive_pnl_share": 0.25,
            "maximum_single_base_positive_pnl_share": 0.25,
            "maximum_single_utc_hour_positive_pnl_share": 0.25,
            "maximum_single_direction_positive_pnl_share": 0.75,
            "deterministic_repeats": 2,
            "matching_result_hash_required": True,
        },
        "capacity": {
            "minimum_displayed_capacity_quote_each_leg": 50.0,
            "minimum_execution_capacity_quote_each_leg": 50.0,
            "capacity_shortfall_counts_as_unfillable": True,
        },
    }


def _paper_forward_proposal() -> dict[str, Any]:
    return {
        "public_readonly_only": True,
        "duration_days": 7,
        "minimum_independent_decisions": 100,
        "minimum_distinct_utc_dates": 5,
        "normal_net_expectancy_bps_gt": 0.0,
        "normal_profit_factor_gte": 1.2,
        "stress_net_expectancy_bps_gte": 0.0,
        "minimum_normal_paired_fill_rate": 0.95,
        "maximum_drawdown_fraction_allocated_capital": 0.10,
        "terminal_result_requires_user_review": True,
        "live_or_private_api_allowed": False,
    }


def _decision_contract() -> dict[str, Any]:
    return {
        "ordered_verdicts": [
            "REJECT_DATA_QUALITY",
            "INSUFFICIENT_DATA_NOT_REJECTED",
            "REJECT_HISTORICAL_ECONOMICS_OR_EXECUTION",
            "ACCEPT_FOR_PUBLIC_READONLY_PAPER_FORWARD",
            "REJECT_PAPER_FORWARD",
            "RESEARCH_ACCEPTED_AWAIT_SEPARATE_LIVE_REVIEW",
        ],
        "insufficient_sample_verdict": "INSUFFICIENT_DATA_NOT_REJECTED",
        "maximum_historical_verdict": "ACCEPT_FOR_PUBLIC_READONLY_PAPER_FORWARD",
        "historical_result_can_accept_strategy": False,
        "stop_on_first_failed_gate": True,
        "no_grid_or_retune_after_failure": True,
        "terminal_accept_or_reject_requires_user_review": True,
    }


def _validate_source_review(review: Mapping[str, Any]) -> None:
    observed_hash = _expect_sha256(review.get("draft_hash"), label="draft_hash")
    _expect(
        signal.canonical_draft_hash(review),
        observed_hash,
        label="review draft canonical hash",
    )
    _expect(review.get("schema"), signal.DRAFT_SCHEMA, label="review schema")
    _expect(review.get("status"), signal.DRAFT_STATUS, label="review status")
    _expect(review.get("research_only"), True, label="review research_only")

    source = _expect_mapping(review.get("source_campaign"), label="source_campaign")
    _expect(source.get("campaign_id"), campaign.AEF_CAMPAIGN_ID, label="campaign_id")
    _expect(source.get("hypothesis_id"), campaign.HYPOTHESIS_ID, label="hypothesis_id")
    _expect(source.get("data_type"), campaign.DATA_TYPE, label="data_type")
    _expect_sha256(
        _expect_mapping(source.get("plan"), label="source plan").get("plan_hash"),
        label="source plan_hash",
    )
    _expect_sha256(
        _expect_mapping(source.get("contract"), label="source contract").get(
            "contract_hash"
        ),
        label="source contract_hash",
    )

    signal_contract = _expect_mapping(
        review.get("signal_contract"), label="signal_contract"
    )
    expected_signal_fields = {
        "source_snapshot_schema": "trading_mvp_dense_ws_execution_snapshot_v1",
        "eligible_regime": "DENSE_BOTH",
        "directions": ["buy_mexc_sell_gateio", "buy_gateio_sell_mexc"],
        "gross_edge_bps_formula": "(sell_bid / buy_ask - 1) * 10000",
        "capacity_quote_formula": (
            "min(buy_ask * buy_ask_qty, sell_bid * sell_bid_qty)"
        ),
        "minimum_capacity_quote": 50.0,
        "normal_total_cost_bps": 69.0,
        "stress_total_cost_bps": 89.0,
        "cooldown_sec_per_base_and_direction": 60,
        "parameter_combinations": 1,
    }
    for key, expected in expected_signal_fields.items():
        _expect(signal_contract.get(key), expected, label=f"signal_contract.{key}")

    design = _expect_mapping(review.get("evaluation_design"), label="evaluation_design")
    split = _expect_mapping(design.get("primary_split"), label="primary_split")
    for key, expected in {
        "train_fraction": 0.7,
        "oos_fraction": 0.3,
        "split_type": "single contiguous chronological split",
        "embargo_sec": 300,
    }.items():
        _expect(split.get(key), expected, label=f"primary_split.{key}")
    walk = _expect_mapping(design.get("walk_forward"), label="walk_forward")
    for key, expected in {
        "folds": 5,
        "ordering": "chronological",
        "formula_refit_between_folds": False,
        "regime_parameters_refit_on_oos": False,
    }.items():
        _expect(walk.get(key), expected, label=f"walk_forward.{key}")

    authorization = _expect_mapping(
        review.get("evaluation_authorization"), label="evaluation_authorization"
    )
    _expect(authorization.get("authorized"), False, label="review authorization")
    _expect(
        authorization.get("returns_pnl_oos_allowed"),
        False,
        label="review returns_pnl_oos_allowed",
    )
    _expect(
        dict(_expect_mapping(review.get("safety"), label="safety")),
        _safety_contract(),
        label="review safety",
    )


def build_acceptance_proposal(
    *,
    review_draft: Mapping[str, Any],
    review_draft_path: str | Path,
    review_draft_file_sha256: str,
) -> dict[str, Any]:
    _validate_source_review(review_draft)
    review_sha = _expect_sha256(
        review_draft_file_sha256, label="review_draft_file_sha256"
    )
    source_campaign = _expect_mapping(
        review_draft.get("source_campaign"), label="source_campaign"
    )
    proposal: dict[str, Any] = {
        "schema": PROPOSAL_SCHEMA,
        "mode": PROPOSAL_MODE,
        "status": PROPOSAL_STATUS,
        "research_only": True,
        "source_review_draft": {
            "path": str(Path(review_draft_path).expanduser().resolve()),
            "file_sha256": review_sha,
            "draft_hash": review_draft["draft_hash"],
        },
        "source_campaign": {
            "campaign_id": source_campaign["campaign_id"],
            "hypothesis_id": source_campaign["hypothesis_id"],
            "data_type": source_campaign["data_type"],
            "plan_hash": source_campaign["plan"]["plan_hash"],
            "contract_hash": source_campaign["contract"]["contract_hash"],
        },
        "contract_gap_audit": _gap_audit(),
        "signal_trigger_proposal": _signal_trigger_proposal(),
        "execution_realization_proposal": _execution_realization_proposal(),
        "acceptance_threshold_proposal": _acceptance_thresholds(),
        "paper_forward_proposal": _paper_forward_proposal(),
        "decision_contract_proposal": _decision_contract(),
        "authorization": {
            "authorized": False,
            "status": "USER_REVIEW_REQUIRED",
            "materialization_binding_present": False,
            "returns_pnl_oos_allowed": False,
            "reason": (
                "This is a pre-result proposal. It is not an evaluator contract or "
                "an evaluation PlanOnly."
            ),
        },
        "safety": _safety_contract(),
        "next_allowed_action": NEXT_ACTION,
    }
    proposal["proposal_hash"] = canonical_proposal_hash(proposal)
    validate_acceptance_proposal(proposal)
    return proposal


def validate_acceptance_proposal(
    proposal: Mapping[str, Any],
    *,
    verify_source_file: bool = False,
) -> None:
    observed_hash = _expect_sha256(proposal.get("proposal_hash"), label="proposal_hash")
    _expect(
        canonical_proposal_hash(proposal),
        observed_hash,
        label="proposal canonical hash",
    )
    expected_top_level = {
        "schema",
        "mode",
        "status",
        "research_only",
        "source_review_draft",
        "source_campaign",
        "contract_gap_audit",
        "signal_trigger_proposal",
        "execution_realization_proposal",
        "acceptance_threshold_proposal",
        "paper_forward_proposal",
        "decision_contract_proposal",
        "authorization",
        "safety",
        "next_allowed_action",
        "proposal_hash",
    }
    _expect(set(proposal), expected_top_level, label="proposal top-level fields")
    _expect(proposal.get("schema"), PROPOSAL_SCHEMA, label="proposal schema")
    _expect(proposal.get("mode"), PROPOSAL_MODE, label="proposal mode")
    _expect(proposal.get("status"), PROPOSAL_STATUS, label="proposal status")
    _expect(proposal.get("research_only"), True, label="proposal research_only")
    _expect(proposal.get("next_allowed_action"), NEXT_ACTION, label="next action")

    _expect(proposal.get("contract_gap_audit"), _gap_audit(), label="gap audit")
    _expect(
        proposal.get("signal_trigger_proposal"),
        _signal_trigger_proposal(),
        label="signal trigger",
    )
    _expect(
        proposal.get("execution_realization_proposal"),
        _execution_realization_proposal(),
        label="execution realization",
    )
    _expect(
        proposal.get("acceptance_threshold_proposal"),
        _acceptance_thresholds(),
        label="acceptance thresholds",
    )
    _expect(
        proposal.get("paper_forward_proposal"),
        _paper_forward_proposal(),
        label="paper forward proposal",
    )
    _expect(
        proposal.get("decision_contract_proposal"),
        _decision_contract(),
        label="decision contract",
    )

    authorization = _expect_mapping(
        proposal.get("authorization"), label="authorization"
    )
    _expect(authorization.get("authorized"), False, label="authorization")
    _expect(
        authorization.get("status"),
        "USER_REVIEW_REQUIRED",
        label="authorization status",
    )
    _expect(
        authorization.get("materialization_binding_present"),
        False,
        label="authorization materialization binding",
    )
    _expect(
        authorization.get("returns_pnl_oos_allowed"),
        False,
        label="authorization returns_pnl_oos_allowed",
    )
    _expect(
        dict(_expect_mapping(proposal.get("safety"), label="safety")),
        _safety_contract(),
        label="safety",
    )

    source_review = _expect_mapping(
        proposal.get("source_review_draft"), label="source_review_draft"
    )
    source_path = str(source_review.get("path") or "")
    if not source_path:
        raise ProposalIntegrityError("source review path is empty")
    _expect_sha256(source_review.get("file_sha256"), label="source review file SHA-256")
    _expect_sha256(source_review.get("draft_hash"), label="source review draft_hash")

    source_campaign = _expect_mapping(
        proposal.get("source_campaign"), label="source_campaign"
    )
    _expect(
        source_campaign.get("campaign_id"),
        campaign.AEF_CAMPAIGN_ID,
        label="source campaign_id",
    )
    _expect(
        source_campaign.get("hypothesis_id"),
        campaign.HYPOTHESIS_ID,
        label="source hypothesis_id",
    )
    _expect(source_campaign.get("data_type"), campaign.DATA_TYPE, label="source data_type")
    _expect_sha256(source_campaign.get("plan_hash"), label="source plan_hash")
    _expect_sha256(source_campaign.get("contract_hash"), label="source contract_hash")

    if verify_source_file:
        path = Path(source_path).expanduser().resolve()
        _expect(
            _sha256_file(path),
            source_review["file_sha256"],
            label="source review file SHA-256",
        )
        review = _read_json(path)
        _validate_source_review(review)
        _expect(
            review.get("draft_hash"),
            source_review["draft_hash"],
            label="source review draft_hash",
        )


def build_acceptance_proposal_from_review(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    review = _read_json(source)
    return build_acceptance_proposal(
        review_draft=review,
        review_draft_path=source,
        review_draft_file_sha256=_sha256_file(source),
    )


def write_new_proposal(path: str | Path, proposal: Mapping[str, Any]) -> Path:
    validate_acceptance_proposal(proposal)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(proposal, ensure_ascii=False, indent=2) + "\n"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise ProposalIntegrityError(f"refusing to overwrite proposal: {target}") from exc
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate the non-authoritative dense WS acceptance proposal."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--review-draft", required=True)
    build.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--proposal", required=True)
    validate.add_argument("--verify-source-file", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        proposal = build_acceptance_proposal_from_review(args.review_draft)
        target = write_new_proposal(args.output, proposal)
        result = {
            "status": "PROPOSAL_WRITTEN_NOT_AUTHORIZED",
            "output": str(target),
            "proposal_hash": proposal["proposal_hash"],
            "next_allowed_action": proposal["next_allowed_action"],
        }
    else:
        proposal = _read_json(args.proposal)
        validate_acceptance_proposal(
            proposal,
            verify_source_file=bool(args.verify_source_file),
        )
        result = {
            "status": "VALID_PROPOSAL_NOT_AUTHORIZED",
            "proposal": str(Path(args.proposal).expanduser().resolve()),
            "proposal_hash": proposal["proposal_hash"],
            "next_allowed_action": proposal["next_allowed_action"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
