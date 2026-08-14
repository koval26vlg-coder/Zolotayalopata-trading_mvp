from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_recollect_control_plane import (  # noqa: E402
    build_approval_bundle,
    canonical_json_hash,
    expected_approval_text,
    main,
    validate_approval_bundle,
    validate_postcollect_quality_context,
)


PLAN_PATH = Path(r"C:\repo\docs\plans\slow-recollect.json")
RECEIPT_PATH = Path(r"C:\repo\docs\agent-log\approvals\slow-recollect.json")
PLAN_FILE_SHA256 = "1" * 64


def make_plan() -> dict[str, object]:
    plan: dict[str, object] = {
        "schema": "trading_mvp_slow_liquidity_history_recollect_planonly_v1",
        "plan_id": "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6",
        "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
        "actual_collection_allowed": False,
        "approval_request": {
            "exact_user_text_template": (
                "Разрешаю exact recollect по plan_hash=<PLAN_HASH> и "
                "plan_file_sha256=<PLAN_FILE_SHA256>: 9 монет, 900 секунд, "
                "100 MB. STOPPED_INCOMPLETE не повторять."
            )
        },
        "approval_receipt": {
            "path": str(RECEIPT_PATH),
            "status": "NOT_CREATED",
            "single_use": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "execution": {
            "run_id": "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6",
            "output_path": r"C:\data\slow-recollect",
            "output_jsonl": r"C:\data\slow-recollect\ohlcv.jsonl",
            "manifest_path": r"C:\data\slow-recollect\manifest.json",
            "launch_record_path": r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json",
            "max_runtime_sec": 900,
            "hard_output_cap_bytes": 100_000_000,
            "maximum_http_attempts": 126,
            "logical_requests": 63,
            "history_days": 56,
            "target_bases": 9,
            "candles_per_request": 1000,
            "single_use": True,
            "resume_allowed": False,
            "stopped_incomplete_retry_authorized": False,
            "exchanges": ["mexc", "gateio"],
            "timeframes": ["1h", "4h"],
        },
        "universe": {
            "path": r"C:\repo\docs\plans\slow-recollect-universe.csv",
            "quote": "USDT",
            "bases": [
                "STETH",
                "WEETH",
                "CC",
                "OKB",
                "RAIN",
                "MNT",
                "USDD",
                "BDX",
                "EDGE",
            ]
        },
        "guard_contract": {
            "preapproval_decision": (
                "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE"
            ),
            "required_decision_after_approval": (
                "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6"
            ),
            "required_policy_rebind_status": (
                "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
            ),
        },
        "forbidden": [
            "resume or retry after STOPPED_INCOMPLETE",
            "evaluator",
            "OOS",
            "returns or PnL",
        ],
        "plan_hash_method": "sha256_canonical_json_excluding_plan_hash",
    }
    plan["plan_hash"] = canonical_json_hash(plan, excluded_key="plan_hash")
    return plan


def make_postcollect_context() -> dict[str, object]:
    plan = make_plan()
    user_text = expected_approval_text(
        plan,
        plan_hash=str(plan["plan_hash"]),
        plan_file_sha256=PLAN_FILE_SHA256,
    )
    bundle = build_approval_bundle(
        plan=plan,
        plan_path=PLAN_PATH,
        plan_file_sha256=PLAN_FILE_SHA256,
        active_policy=make_policy(),
        active_gate=make_gate(plan),
        user_approval_text=user_text,
        approved_at_utc="2026-08-12T07:30:00Z",
    )
    receipt_file_sha256 = hashlib.sha256(bundle.receipt_bytes).hexdigest()
    execution = plan["execution"]
    universe = plan["universe"]
    assert isinstance(execution, dict)
    assert isinstance(universe, dict)
    manifest_file_sha256 = "2" * 64
    output_file_sha256 = "3" * 64

    gate = copy.deepcopy(bundle.gate)
    gate.update(
        {
            "status": "READY_FOR_POSTPROCESS",
            "run_id": execution["run_id"],
            "final": True,
            "next_goal_decision": (
                "SLOW_LIQUIDITY_HISTORY_RECOLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
            ),
            "plan_path": str(PLAN_PATH),
            "plan_hash": plan["plan_hash"],
            "output_path": execution["output_jsonl"],
            "manifest_path": execution["manifest_path"],
        }
    )
    launch_record = {
        "schema": "trading_mvp_slow_liquidity_recollect_launch_v1",
        "status": "COMPLETE",
        "run_id": execution["run_id"],
        "terminal_ownership_verified": True,
        "plan_path": str(PLAN_PATH),
        "plan_file_sha256": PLAN_FILE_SHA256,
        "plan_hash": plan["plan_hash"],
        "approval_receipt_path": str(RECEIPT_PATH),
        "approval_receipt_sha256": receipt_file_sha256,
        "output_path": execution["output_path"],
        "output_jsonl": execution["output_jsonl"],
        "manifest_path": execution["manifest_path"],
        "manifest_sha256": manifest_file_sha256,
        "output_jsonl_sha256": output_file_sha256,
        "retry_authorized": False,
        "started_at_utc": "2026-08-12T07:29:59Z",
        "finished_at_utc": "2026-08-12T07:40:01Z",
    }
    manifest = {
        "mode": "slow_liquidity_history_collect",
        "quality_contract_version": "slow_liquidity_history_exact_v2",
        "run_id": execution["run_id"],
        "started_at": "2026-08-12T07:30:01Z",
        "finished_at": "2026-08-12T07:40:00Z",
        "final": True,
        "decision": (
            "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
        ),
        "universe_path": universe["path"],
        "output_jsonl": execution["output_jsonl"],
        "manifest_path": execution["manifest_path"],
        "history_days": execution["history_days"],
        "history_anchor_ts": 1_786_519_800,
        "history_anchor_iso": "2026-08-12T07:30:00Z",
        "selected_bases": copy.deepcopy(universe["bases"]),
        "quote": universe["quote"],
        "exchanges": copy.deepcopy(execution["exchanges"]),
        "granularities": copy.deepcopy(execution["timeframes"]),
        "candles_per_request": execution["candles_per_request"],
        "planned_market_granularity_requests": 36,
        "completed_market_granularity_requests": 36,
        "http_requests": execution["logical_requests"],
    }
    return {
        "plan": plan,
        "receipt": bundle.receipt,
        "receipt_file_sha256": receipt_file_sha256,
        "policy": bundle.policy,
        "gate": gate,
        "launch_record": launch_record,
        "manifest": manifest,
        "manifest_file_sha256": manifest_file_sha256,
        "output_file_sha256": output_file_sha256,
    }


def make_policy() -> dict[str, object]:
    return {
        "schema": "trading_mvp_autopilot_policy_v1",
        "policy_id": "active-policy",
        "project": "trading_mvp",
        "mode": "AUTOPILOT",
    }


def make_gate(plan: dict[str, object]) -> dict[str, object]:
    guard = plan["guard_contract"]
    assert isinstance(guard, dict)
    return {
        "schema": "active_run_gate_v1",
        "project": "trading_mvp",
        "status": "READY_FOR_POSTPROCESS",
        "run_id": "slow_liquidity_history_collect_20260811_181046",
        "next_goal_decision": guard["preapproval_decision"],
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
    }


class SlowLiquidityRecollectControlPlaneTests(unittest.TestCase):
    def test_postcollect_quality_context_binds_exact_completed_run(self) -> None:
        context = make_postcollect_context()

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=context["gate"],
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=context["manifest"],
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256=str(context["output_file_sha256"]),
        )

        self.assertEqual(errors, [])

    def test_postcollect_quality_context_rejects_invalid_collection_time_chain(self) -> None:
        context = make_postcollect_context()
        manifest = copy.deepcopy(context["manifest"])
        assert isinstance(manifest, dict)
        manifest["finished_at"] = "2026-08-12T07:40:02Z"

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=context["gate"],
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=manifest,
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256=str(context["output_file_sha256"]),
        )

        self.assertIn("quality_collection_time_chain_invalid", errors)

    def test_postcollect_quality_context_rejects_unbound_history_anchor(self) -> None:
        context = make_postcollect_context()
        manifest = copy.deepcopy(context["manifest"])
        assert isinstance(manifest, dict)
        manifest["history_anchor_iso"] = "2026-08-11T07:30:00Z"

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=context["gate"],
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=manifest,
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256=str(context["output_file_sha256"]),
        )

        self.assertIn("quality_manifest_history_anchor_iso_mismatch", errors)

    def test_postcollect_quality_context_rejects_wrong_gate_run(self) -> None:
        context = make_postcollect_context()
        gate = copy.deepcopy(context["gate"])
        assert isinstance(gate, dict)
        gate["run_id"] = "different_run"

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=gate,
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=context["manifest"],
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256=str(context["output_file_sha256"]),
        )

        self.assertIn("quality_gate_run_id_mismatch", errors)

    def test_postcollect_quality_context_rejects_manifest_substitution(self) -> None:
        context = make_postcollect_context()
        manifest = copy.deepcopy(context["manifest"])
        assert isinstance(manifest, dict)
        manifest["selected_bases"] = list(manifest["selected_bases"])[:-1]

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=context["gate"],
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=manifest,
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256=str(context["output_file_sha256"]),
        )

        self.assertIn("quality_manifest_bases_mismatch", errors)

    def test_postcollect_quality_context_rejects_quote_substitution(self) -> None:
        context = make_postcollect_context()
        manifest = copy.deepcopy(context["manifest"])
        assert isinstance(manifest, dict)
        manifest["quote"] = "USDC"

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=context["gate"],
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=manifest,
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256=str(context["output_file_sha256"]),
        )

        self.assertIn("quality_manifest_quote_mismatch", errors)

    def test_postcollect_quality_context_rejects_output_hash_substitution(self) -> None:
        context = make_postcollect_context()

        errors = validate_postcollect_quality_context(
            plan=context["plan"],
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=context["receipt"],
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=str(context["receipt_file_sha256"]),
            policy=context["policy"],
            gate=context["gate"],
            launch_record=context["launch_record"],
            launch_record_path=Path(
                r"C:\repo\docs\agent-log\run-gates\slow-recollect.launch.json"
            ),
            manifest=context["manifest"],
            manifest_path=Path(r"C:\data\slow-recollect\manifest.json"),
            manifest_file_sha256=str(context["manifest_file_sha256"]),
            output_path=Path(r"C:\data\slow-recollect\ohlcv.jsonl"),
            output_file_sha256="4" * 64,
        )

        self.assertIn("quality_output_sha256_mismatch", errors)

    def test_expected_approval_text_binds_plan_and_file_hashes(self) -> None:
        plan = make_plan()

        text = expected_approval_text(
            plan,
            plan_hash=str(plan["plan_hash"]),
            plan_file_sha256=PLAN_FILE_SHA256,
        )

        self.assertIn(str(plan["plan_hash"]), text)
        self.assertIn(PLAN_FILE_SHA256, text)
        self.assertNotIn("<PLAN_HASH>", text)
        self.assertNotIn("<PLAN_FILE_SHA256>", text)

    def test_build_rejects_changed_user_approval_scope(self) -> None:
        plan = make_plan()
        user_text = expected_approval_text(
            plan,
            plan_hash=str(plan["plan_hash"]),
            plan_file_sha256=PLAN_FILE_SHA256,
        ).replace("900 секунд", "901 секунда")

        with self.assertRaisesRegex(ValueError, "user approval text mismatch"):
            build_approval_bundle(
                plan=plan,
                plan_path=PLAN_PATH,
                plan_file_sha256=PLAN_FILE_SHA256,
                active_policy=make_policy(),
                active_gate=make_gate(plan),
                user_approval_text=user_text,
                approved_at_utc="2026-08-12T07:30:00Z",
            )

    def test_bundle_binds_receipt_policy_and_gate_without_hash_cycle(self) -> None:
        plan = make_plan()
        user_text = expected_approval_text(
            plan,
            plan_hash=str(plan["plan_hash"]),
            plan_file_sha256=PLAN_FILE_SHA256,
        )

        bundle = build_approval_bundle(
            plan=plan,
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            active_policy=make_policy(),
            active_gate=make_gate(plan),
            user_approval_text=user_text,
            approved_at_utc="2026-08-12T07:30:00Z",
        )

        receipt_file_sha256 = hashlib.sha256(bundle.receipt_bytes).hexdigest()
        rebind = bundle.policy["slow_liquidity_history_recollect"]
        self.assertEqual(rebind["approval_receipt_file_sha256"], receipt_file_sha256)
        self.assertEqual(
            bundle.gate["slow_liquidity_recollect_approval_receipt_sha256"],
            receipt_file_sha256,
        )
        self.assertEqual(
            bundle.receipt["receipt_hash"],
            canonical_json_hash(bundle.receipt, excluded_key="receipt_hash"),
        )

        errors = validate_approval_bundle(
            plan=plan,
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=bundle.receipt,
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=receipt_file_sha256,
            policy=bundle.policy,
            gate=bundle.gate,
        )
        self.assertEqual(errors, [])

    def test_validation_rejects_self_asserted_receipt_without_policy_rebind(self) -> None:
        plan = make_plan()
        user_text = expected_approval_text(
            plan,
            plan_hash=str(plan["plan_hash"]),
            plan_file_sha256=PLAN_FILE_SHA256,
        )
        bundle = build_approval_bundle(
            plan=plan,
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            active_policy=make_policy(),
            active_gate=make_gate(plan),
            user_approval_text=user_text,
            approved_at_utc="2026-08-12T07:30:00Z",
        )
        receipt_file_sha256 = hashlib.sha256(bundle.receipt_bytes).hexdigest()
        policy = copy.deepcopy(bundle.policy)
        del policy["slow_liquidity_history_recollect"]

        errors = validate_approval_bundle(
            plan=plan,
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=bundle.receipt,
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=receipt_file_sha256,
            policy=policy,
            gate=bundle.gate,
        )

        self.assertIn("policy_rebind_missing", errors)

    def test_validation_rejects_gate_not_bound_to_receipt(self) -> None:
        plan = make_plan()
        user_text = expected_approval_text(
            plan,
            plan_hash=str(plan["plan_hash"]),
            plan_file_sha256=PLAN_FILE_SHA256,
        )
        bundle = build_approval_bundle(
            plan=plan,
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            active_policy=make_policy(),
            active_gate=make_gate(plan),
            user_approval_text=user_text,
            approved_at_utc="2026-08-12T07:30:00Z",
        )
        receipt_file_sha256 = hashlib.sha256(bundle.receipt_bytes).hexdigest()
        gate = copy.deepcopy(bundle.gate)
        gate["slow_liquidity_recollect_approval_receipt_sha256"] = "0" * 64

        errors = validate_approval_bundle(
            plan=plan,
            plan_path=PLAN_PATH,
            plan_file_sha256=PLAN_FILE_SHA256,
            receipt=bundle.receipt,
            receipt_path=RECEIPT_PATH,
            receipt_file_sha256=receipt_file_sha256,
            policy=bundle.policy,
            gate=gate,
        )

        self.assertIn("gate_receipt_sha256_mismatch", errors)

    def test_build_rejects_unexpected_preapproval_gate(self) -> None:
        plan = make_plan()
        gate = make_gate(plan)
        gate["next_goal_decision"] = "UNRELATED_DECISION"
        user_text = expected_approval_text(
            plan,
            plan_hash=str(plan["plan_hash"]),
            plan_file_sha256=PLAN_FILE_SHA256,
        )

        with self.assertRaisesRegex(ValueError, "preapproval gate decision mismatch"):
            build_approval_bundle(
                plan=plan,
                plan_path=PLAN_PATH,
                plan_file_sha256=PLAN_FILE_SHA256,
                active_policy=make_policy(),
                active_gate=gate,
                user_approval_text=user_text,
                approved_at_utc="2026-08-12T07:30:00Z",
            )

    def test_render_and_validate_cli_use_candidate_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            policy_path = root / "policy.json"
            gate_path = root / "gate.json"
            receipt_path = root / "receipt.json"
            user_text_path = root / "approval.txt"
            policy_candidate_path = root / "policy.candidate.json"
            gate_candidate_path = root / "gate.candidate.json"

            plan = make_plan()
            plan["approval_receipt"]["path"] = str(receipt_path)
            plan["plan_hash"] = canonical_json_hash(
                plan, excluded_key="plan_hash"
            )
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            policy = make_policy()
            gate = make_gate(plan)
            policy_path.write_text(
                json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            gate_path.write_text(
                json.dumps(gate, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            plan_file_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            user_text_path.write_text(
                expected_approval_text(
                    plan,
                    plan_hash=str(plan["plan_hash"]),
                    plan_file_sha256=plan_file_sha256,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                render_exit = main(
                    [
                        "render",
                        "--plan",
                        str(plan_path),
                        "--expected-plan-file-sha256",
                        plan_file_sha256,
                        "--expected-plan-hash",
                        str(plan["plan_hash"]),
                        "--policy",
                        str(policy_path),
                        "--gate",
                        str(gate_path),
                        "--user-approval-text-file",
                        str(user_text_path),
                        "--receipt-output",
                        str(receipt_path),
                        "--policy-output",
                        str(policy_candidate_path),
                        "--gate-output",
                        str(gate_candidate_path),
                        "--approved-at-utc",
                        "2026-08-12T07:30:00Z",
                    ]
                )
            self.assertEqual(render_exit, 0, stdout.getvalue())
            rendered = json.loads(stdout.getvalue())
            self.assertEqual(rendered["status"], "CANDIDATE_BUNDLE_RENDERED")
            self.assertEqual(
                json.loads(policy_path.read_text(encoding="utf-8")), policy
            )
            self.assertEqual(json.loads(gate_path.read_text(encoding="utf-8")), gate)

            receipt_file_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                validate_exit = main(
                    [
                        "validate",
                        "--plan",
                        str(plan_path),
                        "--expected-plan-file-sha256",
                        plan_file_sha256,
                        "--expected-plan-hash",
                        str(plan["plan_hash"]),
                        "--receipt",
                        str(receipt_path),
                        "--expected-receipt-file-sha256",
                        receipt_file_sha256,
                        "--policy",
                        str(policy_candidate_path),
                        "--gate",
                        str(gate_candidate_path),
                    ]
                )
            self.assertEqual(validate_exit, 0, stdout.getvalue())
            validated = json.loads(stdout.getvalue())
            self.assertEqual(validated["status"], "VALID")
            self.assertEqual(validated["errors"], [])


if __name__ == "__main__":
    unittest.main()
