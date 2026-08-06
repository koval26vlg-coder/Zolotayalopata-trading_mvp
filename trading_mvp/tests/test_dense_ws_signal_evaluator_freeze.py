from __future__ import annotations

import copy
import os
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_acceptance_proposal as acceptance  # noqa: E402
import dense_ws_campaign_contract as campaign  # noqa: E402
from dense_ws_signal_evaluator_freeze import (  # noqa: E402
    APPROVAL_SCHEMA,
    APPROVAL_TYPE,
    CONTRACT_SCHEMA,
    CONTRACT_STATUS,
    PLAN_SCHEMA,
    PLAN_STATUS,
    FreezeIntegrityError,
    build_frozen_contract,
    build_frozen_plan,
    canonical_contract_hash,
    canonical_plan_hash,
    serialized_file_sha256,
    validate_frozen_contract,
    validate_frozen_plan,
    write_frozen_pair,
)


def _proposal() -> dict:
    proposal = {
        "schema": acceptance.PROPOSAL_SCHEMA,
        "mode": acceptance.PROPOSAL_MODE,
        "status": acceptance.PROPOSAL_STATUS,
        "research_only": True,
        "source_review_draft": {
            "path": str((REPO_ROOT / "review.json").resolve()),
            "file_sha256": "1" * 64,
            "draft_hash": "2" * 64,
        },
        "source_campaign": {
            "campaign_id": campaign.AEF_CAMPAIGN_ID,
            "hypothesis_id": campaign.HYPOTHESIS_ID,
            "data_type": campaign.DATA_TYPE,
            "plan_hash": "3" * 64,
            "contract_hash": "4" * 64,
        },
        "contract_gap_audit": acceptance._gap_audit(),
        "signal_trigger_proposal": acceptance._signal_trigger_proposal(),
        "execution_realization_proposal": (
            acceptance._execution_realization_proposal()
        ),
        "acceptance_threshold_proposal": acceptance._acceptance_thresholds(),
        "paper_forward_proposal": acceptance._paper_forward_proposal(),
        "decision_contract_proposal": acceptance._decision_contract(),
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
        "safety": acceptance._safety_contract(),
        "next_allowed_action": acceptance.NEXT_ACTION,
    }
    proposal["proposal_hash"] = acceptance.canonical_proposal_hash(proposal)
    acceptance.validate_acceptance_proposal(proposal)
    return proposal


def _receipt(proposal: dict, proposal_path: Path) -> dict:
    return {
        "schema": APPROVAL_SCHEMA,
        "status": "APPROVED",
        "approval_type": APPROVAL_TYPE,
        "thread_id": "019e738a-b37c-7a33-ae04-6cc80739f184",
        "approved_at_utc": "2026-08-02T08:00:00Z",
        "approved_at_local": "2026-08-02T11:00:00+03:00",
        "proposal_path": str(proposal_path.resolve()),
        "proposal_file_sha256": "5" * 64,
        "proposal_hash": proposal["proposal_hash"],
        "allowed_actions": [
            "freeze_signal_evaluator_contract",
            "build_immutable_non_executable_planonly",
        ],
        "forbidden_actions": [
            "run_evaluator",
            "read_returns_or_pnl",
            "read_oos",
            "grid_or_retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "real_capital",
            "leverage_or_margin",
        ],
        "evaluation_authorized": False,
        "single_use": True,
        "approval_text": (
            f"contract-freeze only proposal_hash={proposal['proposal_hash']}"
        ),
    }


def _contract_and_plan() -> tuple[dict, dict, dict, dict]:
    proposal = _proposal()
    proposal_path = (REPO_ROOT / "proposal.json").resolve()
    receipt = _receipt(proposal, proposal_path)
    receipt_path = (REPO_ROOT / "approval.json").resolve()
    contract = build_frozen_contract(
        proposal=proposal,
        proposal_path=proposal_path,
        proposal_file_sha256=receipt["proposal_file_sha256"],
        approval_receipt=receipt,
        approval_receipt_path=receipt_path,
        approval_receipt_file_sha256="6" * 64,
    )
    contract_path = (REPO_ROOT / "frozen-contract.json").resolve()
    plan = build_frozen_plan(
        contract=contract,
        contract_path=contract_path,
        contract_file_sha256=serialized_file_sha256(contract),
    )
    return proposal, receipt, contract, plan


class DenseWsSignalEvaluatorFreezeTests(unittest.TestCase):
    def test_freezes_exact_proposal_without_authorizing_evaluation(self) -> None:
        proposal, receipt, contract, plan = _contract_and_plan()

        self.assertEqual(contract["schema"], CONTRACT_SCHEMA)
        self.assertEqual(contract["status"], CONTRACT_STATUS)
        self.assertEqual(contract["contract_hash"], canonical_contract_hash(contract))
        self.assertEqual(
            contract["source_proposal"]["proposal_hash"],
            proposal["proposal_hash"],
        )
        self.assertEqual(
            contract["signal_contract"], proposal["signal_trigger_proposal"]
        )
        self.assertEqual(
            contract["acceptance_contract"],
            proposal["acceptance_threshold_proposal"],
        )
        self.assertTrue(contract["authorization"]["contract_freeze_authorized"])
        self.assertFalse(contract["authorization"]["evaluation_authorized"])
        self.assertFalse(contract["authorization"]["returns_pnl_oos_allowed"])
        self.assertEqual(plan["schema"], PLAN_SCHEMA)
        self.assertEqual(plan["status"], PLAN_STATUS)
        self.assertFalse(plan["executable"])
        self.assertEqual(plan["plan_hash"], canonical_plan_hash(plan))
        validate_frozen_contract(contract, proposal=proposal, approval_receipt=receipt)
        validate_frozen_plan(plan, contract=contract)

    def test_contract_requires_future_materialization_hash_binding(self) -> None:
        _, _, contract, plan = _contract_and_plan()

        binding = contract["materialization_binding_contract"]
        self.assertEqual(binding["status"], "FUTURE_OUTPUT_HASH_BINDING_REQUIRED")
        self.assertTrue(binding["required_before_evaluator"])
        self.assertEqual(
            plan["next_allowed_action"],
            "WAIT_FOR_CAMPAIGN_AND_CAUSAL_MATERIALIZATION_THEN_REQUEST_"
            "EXACT_EVALUATOR_APPROVAL",
        )

    def test_rejects_receipt_for_another_proposal(self) -> None:
        proposal = _proposal()
        path = (REPO_ROOT / "proposal.json").resolve()
        receipt = _receipt(proposal, path)
        receipt["proposal_hash"] = "f" * 64

        with self.assertRaisesRegex(FreezeIntegrityError, "proposal_hash"):
            build_frozen_contract(
                proposal=proposal,
                proposal_path=path,
                proposal_file_sha256=receipt["proposal_file_sha256"],
                approval_receipt=receipt,
                approval_receipt_path=REPO_ROOT / "approval.json",
                approval_receipt_file_sha256="6" * 64,
            )

    def test_rejects_semantic_tampering_even_with_recomputed_hash(self) -> None:
        proposal, receipt, contract, _ = _contract_and_plan()
        contract = copy.deepcopy(contract)
        contract["acceptance_contract"]["sample"][
            "minimum_total_independent_events"
        ] = 1
        contract["contract_hash"] = canonical_contract_hash(contract)

        with self.assertRaisesRegex(FreezeIntegrityError, "contract content"):
            validate_frozen_contract(
                contract,
                proposal=proposal,
                approval_receipt=receipt,
            )

    def test_rejects_attempt_to_make_plan_executable(self) -> None:
        _, _, contract, plan = _contract_and_plan()
        plan = copy.deepcopy(plan)
        plan["executable"] = True
        plan["authorization"]["evaluation_authorized"] = True
        plan["plan_hash"] = canonical_plan_hash(plan)

        with self.assertRaisesRegex(FreezeIntegrityError, "plan content"):
            validate_frozen_plan(plan, contract=contract)

    def test_immutable_writer_refuses_overwrite(self) -> None:
        _, _, contract, _ = _contract_and_plan()
        temp_root = REPO_ROOT / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        suffix = f"{os.getpid()}-{uuid.uuid4().hex}"
        contract_path = temp_root / f"dense-ws-contract-{suffix}.json"
        plan_path = temp_root / f"dense-ws-plan-{suffix}.json"
        plan = build_frozen_plan(
            contract=contract,
            contract_path=contract_path,
            contract_file_sha256=serialized_file_sha256(contract),
        )
        try:
            write_frozen_pair(
                contract_path=contract_path,
                contract=contract,
                plan_path=plan_path,
                plan=plan,
            )
            self.assertTrue(contract_path.is_file())
            self.assertTrue(plan_path.is_file())
            with self.assertRaises(FileExistsError):
                write_frozen_pair(
                    contract_path=contract_path,
                    contract=contract,
                    plan_path=plan_path,
                    plan=plan,
                )
        finally:
            contract_path.unlink(missing_ok=True)
            plan_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
