from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import dense_ws_acceptance_proposal as acceptance
    import dense_ws_campaign_contract as campaign
except ModuleNotFoundError:  # pragma: no cover - package import path
    from . import dense_ws_acceptance_proposal as acceptance
    from . import dense_ws_campaign_contract as campaign


APPROVAL_SCHEMA = "trading_mvp_dense_ws_contract_freeze_approval_v1"
APPROVAL_TYPE = "EXACT_HASH_BOUND_SIGNAL_EVALUATOR_CONTRACT_FREEZE_ONLY"
CONTRACT_SCHEMA = "trading_mvp_dense_ws_signal_evaluator_contract_v1"
PLAN_SCHEMA = "trading_mvp_dense_ws_signal_evaluator_planonly_v1"
CONTRACT_MODE = "FrozenSignalEvaluatorContract"
PLAN_MODE = "NonExecutablePlanOnly"
CONTRACT_STATUS = "FROZEN_NOT_AUTHORIZED"
PLAN_STATUS = "FROZEN_NOT_AUTHORIZED"
NEXT_ACTION = (
    "WAIT_FOR_CAMPAIGN_AND_CAUSAL_MATERIALIZATION_THEN_REQUEST_EXACT_"
    "EVALUATOR_APPROVAL"
)

ALLOWED_ACTIONS = [
    "freeze_signal_evaluator_contract",
    "build_immutable_non_executable_planonly",
]
FORBIDDEN_ACTIONS = [
    "run_evaluator",
    "read_returns_or_pnl",
    "read_oos",
    "grid_or_retune",
    "paper_forward",
    "live_orders",
    "private_api_keys",
    "real_capital",
    "leverage_or_margin",
]


class FreezeIntegrityError(ValueError):
    """A proposal, approval, frozen contract, or PlanOnly binding changed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _serialized_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def serialized_file_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_serialized_json(value).encode("utf-8")).hexdigest()


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
        raise FreezeIntegrityError(f"invalid JSON object: {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreezeIntegrityError(f"expected JSON object: {target}")
    return value


def _expect(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise FreezeIntegrityError(
            f"{label} mismatch: expected {expected!r}, observed {actual!r}"
        )


def _expect_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FreezeIntegrityError(f"{label} must be an object")
    return value


def _expect_sha256(value: Any, *, label: str) -> str:
    normalized = str(value or "").lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise FreezeIntegrityError(f"{label} must be a lowercase SHA-256 value")
    return normalized


def _resolved(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


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


def _evaluation_design_contract() -> dict[str, Any]:
    return {
        "input_ordering": "valid observations sorted by causal sample_ts",
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
        "parameter_combinations": 1,
        "grid_search": False,
        "retune": False,
        "threshold_selection_from_returns_or_pnl": False,
        "threshold_selection_from_oos": False,
    }


def _materialization_binding_contract() -> dict[str, Any]:
    return {
        "status": "FUTURE_OUTPUT_HASH_BINDING_REQUIRED",
        "required_before_evaluator": True,
        "required_manifest_schema": (
            "trading_mvp_dense_ws_causal_materialization_v1"
        ),
        "required_snapshot_schema": (
            "trading_mvp_dense_ws_execution_snapshot_v1"
        ),
        "required_materialization_decision": (
            "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW"
        ),
        "required_materialization_accepted": True,
        "required_future_bindings": [
            "campaign_manifest_sha256",
            "campaign_quality_report_sha256",
            "causal_materialization_manifest_sha256",
            "causal_materialization_deterministic_result_hash",
            "regime_labels_sha256",
            "execution_snapshots_sha256",
            "raw_bbo_segment_chain_and_file_hashes",
        ],
        "raw_bbo_binding_source": (
            "same accepted immutable campaign segments referenced by the "
            "hash-bound quality report"
        ),
        "unbound_input_action": "REFUSE_EVALUATOR",
    }


def canonical_contract_hash(contract: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in contract.items() if key != "contract_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_plan_hash(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def validate_approval_receipt(
    receipt: Mapping[str, Any],
    *,
    proposal: Mapping[str, Any],
    proposal_path: str | Path,
    proposal_file_sha256: str,
) -> None:
    proposal_hash = _expect_sha256(
        proposal.get("proposal_hash"), label="proposal.proposal_hash"
    )
    proposal_sha = _expect_sha256(
        proposal_file_sha256, label="proposal_file_sha256"
    )
    _expect(receipt.get("schema"), APPROVAL_SCHEMA, label="approval.schema")
    _expect(receipt.get("status"), "APPROVED", label="approval.status")
    _expect(
        receipt.get("approval_type"),
        APPROVAL_TYPE,
        label="approval.approval_type",
    )
    _expect(
        _resolved(str(receipt.get("proposal_path") or "")),
        _resolved(proposal_path),
        label="approval.proposal_path",
    )
    _expect(
        _expect_sha256(
            receipt.get("proposal_file_sha256"),
            label="approval.proposal_file_sha256",
        ),
        proposal_sha,
        label="approval.proposal_file_sha256",
    )
    _expect(
        _expect_sha256(receipt.get("proposal_hash"), label="approval.proposal_hash"),
        proposal_hash,
        label="approval.proposal_hash",
    )
    _expect(receipt.get("allowed_actions"), ALLOWED_ACTIONS, label="allowed_actions")
    _expect(
        receipt.get("forbidden_actions"),
        FORBIDDEN_ACTIONS,
        label="forbidden_actions",
    )
    _expect(
        receipt.get("evaluation_authorized"),
        False,
        label="evaluation_authorized",
    )
    _expect(receipt.get("single_use"), True, label="approval.single_use")
    if not str(receipt.get("thread_id") or "").strip():
        raise FreezeIntegrityError("approval.thread_id is empty")
    if not str(receipt.get("approved_at_utc") or "").strip():
        raise FreezeIntegrityError("approval.approved_at_utc is empty")
    approval_text = str(receipt.get("approval_text") or "")
    if proposal_hash not in approval_text or "contract-freeze" not in approval_text:
        raise FreezeIntegrityError(
            "approval_text must bind contract-freeze to the exact proposal_hash"
        )


def _build_contract_payload(
    *,
    proposal: Mapping[str, Any],
    proposal_path: str | Path,
    proposal_file_sha256: str,
    approval_receipt: Mapping[str, Any],
    approval_receipt_path: str | Path,
    approval_receipt_file_sha256: str,
) -> dict[str, Any]:
    proposal_sha = _expect_sha256(
        proposal_file_sha256, label="proposal_file_sha256"
    )
    receipt_sha = _expect_sha256(
        approval_receipt_file_sha256,
        label="approval_receipt_file_sha256",
    )
    source_review = _expect_mapping(
        proposal.get("source_review_draft"), label="source_review_draft"
    )
    source_campaign = _expect_mapping(
        proposal.get("source_campaign"), label="source_campaign"
    )
    return {
        "schema": CONTRACT_SCHEMA,
        "mode": CONTRACT_MODE,
        "status": CONTRACT_STATUS,
        "research_only": True,
        "identity": {
            "campaign_id": source_campaign["campaign_id"],
            "hypothesis_id": source_campaign["hypothesis_id"],
            "data_type": source_campaign["data_type"],
        },
        "source_proposal": {
            "path": _resolved(proposal_path),
            "file_sha256": proposal_sha,
            "proposal_hash": proposal["proposal_hash"],
        },
        "source_review_draft": copy.deepcopy(dict(source_review)),
        "source_campaign": copy.deepcopy(dict(source_campaign)),
        "approval_binding": {
            "path": _resolved(approval_receipt_path),
            "file_sha256": receipt_sha,
            "schema": APPROVAL_SCHEMA,
            "approval_type": APPROVAL_TYPE,
            "status": "APPROVED",
            "thread_id": approval_receipt["thread_id"],
            "approved_at_utc": approval_receipt["approved_at_utc"],
            "proposal_hash": proposal["proposal_hash"],
            "scope": "CONTRACT_FREEZE_ONLY",
        },
        "signal_contract": copy.deepcopy(
            proposal["signal_trigger_proposal"]
        ),
        "execution_realization_contract": copy.deepcopy(
            proposal["execution_realization_proposal"]
        ),
        "evaluation_design_contract": _evaluation_design_contract(),
        "acceptance_contract": copy.deepcopy(
            proposal["acceptance_threshold_proposal"]
        ),
        "paper_forward_contract": copy.deepcopy(
            proposal["paper_forward_proposal"]
        ),
        "decision_contract": copy.deepcopy(
            proposal["decision_contract_proposal"]
        ),
        "materialization_binding_contract": _materialization_binding_contract(),
        "authorization": {
            "contract_freeze_authorized": True,
            "planonly_build_authorized": True,
            "evaluation_authorized": False,
            "materialization_output_bound": False,
            "returns_pnl_oos_allowed": False,
            "paper_forward_authorized": False,
            "live_or_private_api_authorized": False,
        },
        "safety": _safety_contract(),
        "next_allowed_action": NEXT_ACTION,
    }


def build_frozen_contract(
    *,
    proposal: Mapping[str, Any],
    proposal_path: str | Path,
    proposal_file_sha256: str,
    approval_receipt: Mapping[str, Any],
    approval_receipt_path: str | Path,
    approval_receipt_file_sha256: str,
) -> dict[str, Any]:
    try:
        acceptance.validate_acceptance_proposal(proposal)
    except (acceptance.ProposalIntegrityError, KeyError) as exc:
        raise FreezeIntegrityError(f"invalid acceptance proposal: {exc}") from exc
    validate_approval_receipt(
        approval_receipt,
        proposal=proposal,
        proposal_path=proposal_path,
        proposal_file_sha256=proposal_file_sha256,
    )
    contract = _build_contract_payload(
        proposal=proposal,
        proposal_path=proposal_path,
        proposal_file_sha256=proposal_file_sha256,
        approval_receipt=approval_receipt,
        approval_receipt_path=approval_receipt_path,
        approval_receipt_file_sha256=approval_receipt_file_sha256,
    )
    contract["contract_hash"] = canonical_contract_hash(contract)
    validate_frozen_contract(
        contract,
        proposal=proposal,
        approval_receipt=approval_receipt,
    )
    return contract


def validate_frozen_contract(
    contract: Mapping[str, Any],
    *,
    proposal: Mapping[str, Any],
    approval_receipt: Mapping[str, Any],
) -> None:
    observed_hash = _expect_sha256(
        contract.get("contract_hash"), label="contract_hash"
    )
    _expect(
        canonical_contract_hash(contract),
        observed_hash,
        label="contract canonical hash",
    )
    source = _expect_mapping(
        contract.get("source_proposal"), label="source_proposal"
    )
    approval = _expect_mapping(
        contract.get("approval_binding"), label="approval_binding"
    )
    validate_approval_receipt(
        approval_receipt,
        proposal=proposal,
        proposal_path=str(source.get("path") or ""),
        proposal_file_sha256=str(source.get("file_sha256") or ""),
    )
    expected = _build_contract_payload(
        proposal=proposal,
        proposal_path=str(source.get("path") or ""),
        proposal_file_sha256=str(source.get("file_sha256") or ""),
        approval_receipt=approval_receipt,
        approval_receipt_path=str(approval.get("path") or ""),
        approval_receipt_file_sha256=str(approval.get("file_sha256") or ""),
    )
    expected["contract_hash"] = canonical_contract_hash(expected)
    if dict(contract) != expected:
        raise FreezeIntegrityError(
            "contract content mismatch; frozen semantics were modified"
        )


def _build_plan_payload(
    *,
    contract: Mapping[str, Any],
    contract_path: str | Path,
    contract_file_sha256: str,
) -> dict[str, Any]:
    contract_sha = _expect_sha256(
        contract_file_sha256, label="contract_file_sha256"
    )
    identity = _expect_mapping(contract.get("identity"), label="contract.identity")
    return {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "status": PLAN_STATUS,
        "research_only": True,
        "executable": False,
        "identity": copy.deepcopy(dict(identity)),
        "source_proposal": copy.deepcopy(contract["source_proposal"]),
        "contract": {
            "path": _resolved(contract_path),
            "file_sha256": contract_sha,
            "contract_hash": contract["contract_hash"],
        },
        "materialization_input": {
            "status": "UNBOUND",
            "required_before_evaluator": True,
            "binding_contract": copy.deepcopy(
                contract["materialization_binding_contract"]
            ),
        },
        "allowed_actions": [
            "validate_frozen_contract_and_plan",
            "bind_future_same_campaign_materialization_in_a_new_hash_bound_run_plan",
            "request_exact_evaluator_approval_after_binding",
        ],
        "forbidden_actions": copy.deepcopy(FORBIDDEN_ACTIONS),
        "authorization": copy.deepcopy(contract["authorization"]),
        "safety": _safety_contract(),
        "next_allowed_action": NEXT_ACTION,
    }


def build_frozen_plan(
    *,
    contract: Mapping[str, Any],
    contract_path: str | Path,
    contract_file_sha256: str,
) -> dict[str, Any]:
    plan = _build_plan_payload(
        contract=contract,
        contract_path=contract_path,
        contract_file_sha256=contract_file_sha256,
    )
    plan["plan_hash"] = canonical_plan_hash(plan)
    validate_frozen_plan(plan, contract=contract)
    return plan


def validate_frozen_plan(
    plan: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> None:
    observed_hash = _expect_sha256(plan.get("plan_hash"), label="plan_hash")
    _expect(canonical_plan_hash(plan), observed_hash, label="plan canonical hash")
    binding = _expect_mapping(plan.get("contract"), label="plan.contract")
    expected = _build_plan_payload(
        contract=contract,
        contract_path=str(binding.get("path") or ""),
        contract_file_sha256=str(binding.get("file_sha256") or ""),
    )
    expected["plan_hash"] = canonical_plan_hash(expected)
    if dict(plan) != expected:
        raise FreezeIntegrityError(
            "plan content mismatch; non-executable PlanOnly semantics were modified"
        )


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_serialized_json(value))
        handle.flush()
        os.fsync(handle.fileno())


def write_frozen_pair(
    *,
    contract_path: str | Path,
    contract: Mapping[str, Any],
    plan_path: str | Path,
    plan: Mapping[str, Any],
) -> tuple[Path, Path]:
    contract_target = Path(contract_path).expanduser().resolve()
    plan_target = Path(plan_path).expanduser().resolve()
    if contract_target == plan_target:
        raise FreezeIntegrityError("contract and PlanOnly paths must differ")
    if contract_target.exists():
        raise FileExistsError(f"frozen contract already exists: {contract_target}")
    if plan_target.exists():
        raise FileExistsError(f"frozen PlanOnly already exists: {plan_target}")
    validate_frozen_plan(plan, contract=contract)
    binding = _expect_mapping(plan.get("contract"), label="plan.contract")
    _expect(
        _resolved(str(binding.get("path") or "")),
        str(contract_target),
        label="plan contract path",
    )
    _expect(
        binding.get("file_sha256"),
        serialized_file_sha256(contract),
        label="plan contract file SHA-256",
    )
    contract_target.parent.mkdir(parents=True, exist_ok=True)
    plan_target.parent.mkdir(parents=True, exist_ok=True)
    contract_written = False
    try:
        _write_new_json(contract_target, contract)
        contract_written = True
        _write_new_json(plan_target, plan)
    except BaseException:
        if contract_written and not plan_target.exists():
            contract_target.unlink(missing_ok=True)
        raise
    return contract_target, plan_target


def freeze_contract_and_plan_files(
    *,
    proposal_path: str | Path,
    approval_receipt_path: str | Path,
    contract_path: str | Path,
    plan_path: str | Path,
) -> dict[str, Any]:
    proposal_target = Path(proposal_path).expanduser().resolve()
    receipt_target = Path(approval_receipt_path).expanduser().resolve()
    proposal = _read_json(proposal_target)
    receipt = _read_json(receipt_target)
    proposal_sha = _sha256_file(proposal_target)
    receipt_sha = _sha256_file(receipt_target)
    try:
        acceptance.validate_acceptance_proposal(
            proposal,
            verify_source_file=True,
        )
    except (acceptance.ProposalIntegrityError, KeyError) as exc:
        raise FreezeIntegrityError(f"invalid acceptance proposal: {exc}") from exc
    contract = build_frozen_contract(
        proposal=proposal,
        proposal_path=proposal_target,
        proposal_file_sha256=proposal_sha,
        approval_receipt=receipt,
        approval_receipt_path=receipt_target,
        approval_receipt_file_sha256=receipt_sha,
    )
    contract_target = Path(contract_path).expanduser().resolve()
    plan = build_frozen_plan(
        contract=contract,
        contract_path=contract_target,
        contract_file_sha256=serialized_file_sha256(contract),
    )
    contract_target, plan_target = write_frozen_pair(
        contract_path=contract_target,
        contract=contract,
        plan_path=plan_path,
        plan=plan,
    )
    _expect(
        _sha256_file(contract_target),
        serialized_file_sha256(contract),
        label="persisted contract file SHA-256",
    )
    _expect(
        _sha256_file(plan_target),
        serialized_file_sha256(plan),
        label="persisted PlanOnly file SHA-256",
    )
    return {
        "status": "CONTRACT_AND_PLAN_FROZEN_EVALUATION_NOT_AUTHORIZED",
        "proposal_hash": proposal["proposal_hash"],
        "contract_path": str(contract_target),
        "contract_file_sha256": _sha256_file(contract_target),
        "contract_hash": contract["contract_hash"],
        "plan_path": str(plan_target),
        "plan_file_sha256": _sha256_file(plan_target),
        "plan_hash": plan["plan_hash"],
        "evaluation_authorized": False,
        "returns_pnl_oos_read": False,
        "next_allowed_action": NEXT_ACTION,
    }


def validate_frozen_files(
    *,
    proposal_path: str | Path,
    approval_receipt_path: str | Path,
    contract_path: str | Path,
    plan_path: str | Path,
) -> dict[str, Any]:
    proposal_target = Path(proposal_path).expanduser().resolve()
    receipt_target = Path(approval_receipt_path).expanduser().resolve()
    contract_target = Path(contract_path).expanduser().resolve()
    plan_target = Path(plan_path).expanduser().resolve()
    proposal = _read_json(proposal_target)
    receipt = _read_json(receipt_target)
    contract = _read_json(contract_target)
    plan = _read_json(plan_target)
    try:
        acceptance.validate_acceptance_proposal(
            proposal,
            verify_source_file=True,
        )
    except (acceptance.ProposalIntegrityError, KeyError) as exc:
        raise FreezeIntegrityError(f"invalid acceptance proposal: {exc}") from exc
    validate_approval_receipt(
        receipt,
        proposal=proposal,
        proposal_path=proposal_target,
        proposal_file_sha256=_sha256_file(proposal_target),
    )
    approval_binding = _expect_mapping(
        contract.get("approval_binding"), label="approval_binding"
    )
    _expect(
        approval_binding.get("file_sha256"),
        _sha256_file(receipt_target),
        label="approval receipt file SHA-256",
    )
    validate_frozen_contract(
        contract,
        proposal=proposal,
        approval_receipt=receipt,
    )
    validate_frozen_plan(plan, contract=contract)
    plan_contract = _expect_mapping(plan.get("contract"), label="plan.contract")
    _expect(
        _resolved(str(plan_contract.get("path") or "")),
        str(contract_target),
        label="plan contract path",
    )
    _expect(
        plan_contract.get("file_sha256"),
        _sha256_file(contract_target),
        label="plan contract file SHA-256",
    )
    return {
        "status": "VALID_FROZEN_CONTRACT_AND_NON_EXECUTABLE_PLANONLY",
        "proposal_hash": proposal["proposal_hash"],
        "contract_hash": contract["contract_hash"],
        "plan_hash": plan["plan_hash"],
        "evaluation_authorized": False,
        "next_allowed_action": NEXT_ACTION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the approved dense WS signal/evaluator rules without running "
            "an evaluator or reading returns, PnL, or OOS."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "validate"):
        command = subparsers.add_parser(name)
        command.add_argument("--proposal", required=True)
        command.add_argument("--approval-receipt", required=True)
        command.add_argument("--contract", required=True)
        command.add_argument("--plan", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    function = (
        freeze_contract_and_plan_files
        if args.command == "freeze"
        else validate_frozen_files
    )
    result = function(
        proposal_path=args.proposal,
        approval_receipt_path=args.approval_receipt,
        contract_path=args.contract,
        plan_path=args.plan,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
