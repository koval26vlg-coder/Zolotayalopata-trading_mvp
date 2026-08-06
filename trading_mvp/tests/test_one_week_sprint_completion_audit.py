from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from one_week_sprint_completion_audit import (  # noqa: E402
    EXPECTED_PIT_COLLECTION_STAGE,
    EXPECTED_PIT_DATA_TYPE,
    EXPECTED_PIT_HYPOTHESIS_ID,
    EXPECTED_TERMINAL_VERDICT,
    _implementation_hashes,
    derive_goal_state,
    validate_autopilot_binding,
    validate_pit_contract,
    verify_closed_branch_evidence,
)


class OneWeekSprintCompletionAuditTests(unittest.TestCase):
    def test_binds_all_completion_audit_implementation_sources(self) -> None:
        hashes = _implementation_hashes()
        self.assertEqual(
            set(hashes),
            {
                "code:one_week_sprint_completion_audit",
                "code:night_schedule_status",
                "code:night_schedule_quality",
            },
        )
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))

    def _autopilot_binding_inputs(self) -> dict:
        pointer_path = Path("pointer.json").resolve()
        plan_path = Path("plan.json").resolve()
        contract_hash = "a" * 64
        next_segment = {
            "run_id": "pit_next",
            "status": "PLANNED",
            "start_local": "2026-07-31T01:00:00+03:00",
            "hard_deadline_local": "2026-07-31T07:00:00+03:00",
        }
        return {
            "autopilot": {
                "schema": "trading_mvp_autopilot_state_v1",
                "project": "trading_mvp",
                "status": "ACTIVE",
                "observed_at_utc": "2026-07-30T20:00:00Z",
                "schedule_window": {
                    "pointer_path": str(pointer_path),
                    "plan_path": str(plan_path),
                    "plan_hash": "b" * 64,
                    "hypothesis_id": EXPECTED_PIT_HYPOTHESIS_ID,
                    "data_type": EXPECTED_PIT_DATA_TYPE,
                    "collection_stage": EXPECTED_PIT_COLLECTION_STAGE,
                    "hypothesis_contract_sha256": contract_hash,
                    "accepted_distinct_dates": 4,
                    "stage_target_distinct_dates": 20,
                    "status": "WAITING",
                    "run_id": "pit_next",
                },
            },
            "autopilot_path": Path("autopilot.json").resolve(),
            "pointer_path": pointer_path,
            "plan_path": plan_path,
            "plan_hash": "b" * 64,
            "pit_contract": {
                "hypothesis_id": EXPECTED_PIT_HYPOTHESIS_ID,
                "data_type": EXPECTED_PIT_DATA_TYPE,
                "collection_stage": EXPECTED_PIT_COLLECTION_STAGE,
                "hypothesis_contract_sha256": contract_hash,
            },
            "accepted_dates": 4,
            "train_target_dates": 20,
            "next_segment": next_segment,
        }

    def test_validates_autopilot_schedule_binding(self) -> None:
        inputs = self._autopilot_binding_inputs()
        binding = validate_autopilot_binding(**inputs)
        self.assertEqual(binding["schedule_status"], "WAITING")
        self.assertEqual(binding["run_id"], "pit_next")
        self.assertEqual(
            binding["hypothesis_contract_sha256"],
            "a" * 64,
        )

    def test_rejects_autopilot_plan_hash_mismatch(self) -> None:
        inputs = self._autopilot_binding_inputs()
        inputs["autopilot"]["schedule_window"]["plan_hash"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "plan_hash mismatch"):
            validate_autopilot_binding(**inputs)

    def test_rejects_autopilot_next_segment_mismatch(self) -> None:
        inputs = self._autopilot_binding_inputs()
        inputs["autopilot"]["schedule_window"]["run_id"] = "foreign_run"
        with self.assertRaisesRegex(ValueError, "run_id mismatch"):
            validate_autopilot_binding(**inputs)

    def test_rejects_no_pending_binding_with_status_segment(self) -> None:
        inputs = self._autopilot_binding_inputs()
        inputs["autopilot"]["schedule_window"]["status"] = "NO_PENDING_SEGMENT"
        with self.assertRaisesRegex(ValueError, "status audit found one"):
            validate_autopilot_binding(**inputs)

    def test_accepts_zero_bound_accepted_dates(self) -> None:
        inputs = self._autopilot_binding_inputs()
        inputs["accepted_dates"] = 0
        inputs["autopilot"]["schedule_window"]["accepted_distinct_dates"] = 0
        binding = validate_autopilot_binding(**inputs)
        self.assertEqual(binding["accepted_distinct_dates"], 0)

    def test_rejects_naive_autopilot_observation_time(self) -> None:
        inputs = self._autopilot_binding_inputs()
        inputs["autopilot"]["observed_at_utc"] = "2026-07-30T20:00:00"
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            validate_autopilot_binding(**inputs)

    def test_validates_frozen_pit_contract_across_pointer_plan_and_ledger(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "quality.jsonl"
            contract_hash = "a" * 64
            pointer = {
                "status": "ACTIVE",
                "hypothesis_id": EXPECTED_PIT_HYPOTHESIS_ID,
                "data_type": EXPECTED_PIT_DATA_TYPE,
                "collection_stage": EXPECTED_PIT_COLLECTION_STAGE,
                "quality_ledger_path": str(ledger_path),
            }
            plan = {
                "hypothesis": {
                    "id": EXPECTED_PIT_HYPOTHESIS_ID,
                    "required_data_type": EXPECTED_PIT_DATA_TYPE,
                },
                "sealed_schedule": {
                    "hypothesis_contract_sha256": contract_hash,
                    "collection_stage": {
                        "name": EXPECTED_PIT_COLLECTION_STAGE,
                        "quality_ledger": {"path": str(ledger_path)},
                    },
                },
            }
            entries = [
                {
                    "track_key": (
                        f"{EXPECTED_PIT_HYPOTHESIS_ID}|{EXPECTED_PIT_DATA_TYPE}"
                    ),
                    "hypothesis_contract_sha256": contract_hash,
                }
            ]

            result = validate_pit_contract(
                pointer=pointer,
                plan=plan,
                ledger_entries=entries,
                ledger_path=ledger_path,
            )

        self.assertEqual(result["hypothesis_contract_sha256"], contract_hash)

    def test_rejects_foreign_pit_contract_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "quality.jsonl"
            pointer = {
                "status": "ACTIVE",
                "hypothesis_id": EXPECTED_PIT_HYPOTHESIS_ID,
                "data_type": EXPECTED_PIT_DATA_TYPE,
                "collection_stage": EXPECTED_PIT_COLLECTION_STAGE,
                "quality_ledger_path": str(ledger_path),
            }
            plan = {
                "hypothesis": {
                    "id": EXPECTED_PIT_HYPOTHESIS_ID,
                    "required_data_type": EXPECTED_PIT_DATA_TYPE,
                },
                "sealed_schedule": {
                    "hypothesis_contract_sha256": "a" * 64,
                    "collection_stage": {
                        "name": EXPECTED_PIT_COLLECTION_STAGE,
                        "quality_ledger": {"path": str(ledger_path)},
                    },
                },
            }
            entries = [
                {
                    "track_key": (
                        f"{EXPECTED_PIT_HYPOTHESIS_ID}|{EXPECTED_PIT_DATA_TYPE}"
                    ),
                    "hypothesis_contract_sha256": "b" * 64,
                }
            ]

            with self.assertRaisesRegex(ValueError, "foreign"):
                validate_pit_contract(
                    pointer=pointer,
                    plan=plan,
                    ledger_entries=entries,
                    ledger_path=ledger_path,
                )

    def test_verifies_closed_branch_evidence_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence = Path(temp_dir) / "evidence.json"
            evidence.write_text('{"verdict":"REJECT"}\n', encoding="utf-8")
            expected = hashlib.sha256(evidence.read_bytes()).hexdigest()
            report = {
                "branches": [
                    {
                        "hypothesis_id": "candidate",
                        "verdict": "REJECT",
                        "reason": "gate_failed",
                        "evidence": {
                            "path": str(evidence),
                            "file_sha256": expected,
                        },
                    }
                ]
            }
            verified = verify_closed_branch_evidence(report)
            self.assertEqual(verified[0]["evidence_sha256"], expected)
            self.assertTrue(verified[0]["verified"])

    def test_rejects_changed_branch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence = Path(temp_dir) / "evidence.json"
            evidence.write_text("{}\n", encoding="utf-8")
            report = {
                "branches": [
                    {
                        "hypothesis_id": "candidate",
                        "evidence": {
                            "path": str(evidence),
                            "file_sha256": "0" * 64,
                        },
                    }
                ]
            }
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_closed_branch_evidence(report)

    def test_active_train_accrual_state(self) -> None:
        state = derive_goal_state(
            terminal_verdict=EXPECTED_TERMINAL_VERDICT,
            positive_edge_proven=False,
            accepted_dates=4,
            train_target_dates=20,
            approval_valid=True,
            schedule_decision="WAIT_FOR_NEXT_NIGHT_SEGMENT",
            autopilot_status="ACTIVE",
        )
        self.assertEqual(
            state["status"],
            "HISTORICAL_SPRINT_TERMINAL_PIT_TRAIN_ACCRUAL",
        )
        self.assertFalse(state["goal_complete"])

    def test_train_feasibility_becomes_due_at_twenty_dates(self) -> None:
        state = derive_goal_state(
            terminal_verdict=EXPECTED_TERMINAL_VERDICT,
            positive_edge_proven=False,
            accepted_dates=20,
            train_target_dates=20,
            approval_valid=True,
            schedule_decision="WAIT_FOR_NEXT_NIGHT_SEGMENT",
            autopilot_status="ACTIVE",
        )
        self.assertEqual(state["status"], "PIT_TRAIN_FEASIBILITY_DUE")

    def test_weekly_pause_precedes_schedule_work(self) -> None:
        state = derive_goal_state(
            terminal_verdict=EXPECTED_TERMINAL_VERDICT,
            positive_edge_proven=False,
            accepted_dates=4,
            train_target_dates=20,
            approval_valid=True,
            schedule_decision="WAIT_FOR_NEXT_NIGHT_SEGMENT",
            autopilot_status="PAUSED_WEEKLY_LIMIT",
        )
        self.assertEqual(state["status"], "PAUSED_WEEKLY_LIMIT")
        self.assertEqual(
            state["next_allowed_action"],
            "wait_for_weekly_quota_guard_to_resume",
        )

    def test_missed_segment_with_future_pending_segment_remains_active(self) -> None:
        state = derive_goal_state(
            terminal_verdict=EXPECTED_TERMINAL_VERDICT,
            positive_edge_proven=False,
            accepted_dates=4,
            train_target_dates=20,
            approval_valid=True,
            schedule_decision="NIGHT_SEGMENT_MISSED",
            autopilot_status="ACTIVE",
            next_segment_available=True,
        )
        self.assertEqual(
            state["status"],
            "HISTORICAL_SPRINT_TERMINAL_PIT_TRAIN_ACCRUAL",
        )
        self.assertFalse(state["goal_complete"])

    def test_missed_segment_without_future_pending_segment_is_critical(self) -> None:
        state = derive_goal_state(
            terminal_verdict=EXPECTED_TERMINAL_VERDICT,
            positive_edge_proven=False,
            accepted_dates=4,
            train_target_dates=20,
            approval_valid=True,
            schedule_decision="NIGHT_SEGMENT_MISSED",
            autopilot_status="ACTIVE",
            next_segment_available=False,
        )
        self.assertEqual(state["status"], "CRITICAL_PIT_SCHEDULE_STATE")
        self.assertEqual(state["next_allowed_action"], "user_review_required")


if __name__ == "__main__":
    unittest.main()
