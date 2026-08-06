from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pit_train_progress_monitor as monitor  # noqa: E402


def _segment(sequence: int, day: int) -> dict:
    return {
        "sequence": sequence,
        "run_id": f"pit_202608{day:02d}",
        "start_local": f"2026-08-{day:02d}T01:00:00+03:00",
        "end_local": f"2026-08-{day:02d}T01:20:00+03:00",
        "hard_deadline_local": f"2026-08-{day:02d}T07:00:00+03:00",
    }


def _inputs(
    *,
    gate_status: str = "READY_FOR_POSTPROCESS",
    accepted: int = 4,
) -> tuple[dict, dict, dict, dict]:
    segments = [_segment(index, index) for index in range(1, 15)]
    plan = {"sealed_schedule": {"segments": segments}}
    validation = {
        "plan_path": r"E:\schedule.json",
        "plan_hash": "a" * 64,
        "plan_file_sha256": "b" * 64,
        "collection_stage": "train_accrual",
        "current_accepted_certifications": [
            {
                "scheduled_date": f"2026-07-{index:02d}",
                "segment_run_id": f"old_{index}",
            }
            for index in range(1, accepted + 1)
        ],
    }
    gate = {
        "gate_status": gate_status,
        "run_id": "current",
        "replay_allowed": False,
        "process_ids": [123] if gate_status == "RUNNING" else [],
    }
    approval = {
        "status": "HASH_VALID_ACTIVE",
        "approval_record_path": r"C:\approval.json",
        "approval_record_sha256": "c" * 64,
        "expires_at": "2026-08-14T07:00:00+03:00",
    }
    return plan, validation, gate, approval


class PitTrainProgressMonitorTests(unittest.TestCase):
    def test_waiting_schedule_continues_offline_autopilot(self) -> None:
        plan, validation, gate, approval = _inputs()
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-07-28T22:00:00+03:00"
            ),
            approval_status=approval,
        )
        self.assertEqual(
            report["decision"],
            "SCHEDULE_WAIT_OFFLINE_AUTOPILOT_ACTIVE",
        )
        self.assertEqual(
            report["next_allowed_action"],
            "continue_bounded_offline_research_backlog",
        )
        self.assertEqual(report["train_eta"]["remaining_dates"], 16)
        self.assertEqual(
            report["train_eta"]["additional_dates_needed_after_schedule"], 2
        )
        self.assertEqual(
            report["train_eta"][
                "expired_uncertified_schedule_dates_excluded"
            ],
            0,
        )

    def test_expired_uncertified_dates_do_not_count_toward_projection(
        self,
    ) -> None:
        plan, validation, gate, approval = _inputs()
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-08-03T08:00:00+03:00"
            ),
            approval_status=approval,
        )

        self.assertEqual(
            report["train_eta"]["scheduled_new_dates_available"],
            11,
        )
        self.assertEqual(
            report["train_eta"][
                "expired_uncertified_schedule_dates_excluded"
            ],
            3,
        )
        self.assertEqual(
            report["train_eta"]["expired_uncertified_dates"],
            [
                "2026-08-01",
                "2026-08-02",
                "2026-08-03",
            ],
        )
        self.assertEqual(
            report["train_eta"][
                "projected_accepted_dates_at_schedule_end"
            ],
            15,
        )
        self.assertEqual(
            report["train_eta"]["additional_dates_needed_after_schedule"],
            5,
        )
        self.assertEqual(
            report["train_eta"][
                "earliest_possible_train_checkpoint_date_if_each_future_date_passes"
            ],
            "2026-08-19",
        )

    def test_due_uncertified_date_remains_available(self) -> None:
        plan, validation, gate, approval = _inputs()
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-08-03T01:05:00+03:00"
            ),
            approval_status=approval,
        )

        self.assertEqual(
            report["train_eta"]["scheduled_new_dates_available"],
            12,
        )
        self.assertEqual(
            report["train_eta"][
                "expired_uncertified_schedule_dates_excluded"
            ],
            2,
        )
        self.assertEqual(
            report["train_eta"]["additional_dates_needed_after_schedule"],
            4,
        )

    def test_due_and_countdown_are_identified_exactly(self) -> None:
        plan, validation, gate, approval = _inputs()
        due = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-08-01T01:05:00+03:00"
            ),
            approval_status=approval,
        )
        countdown = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-08-01T00:57:00+03:00"
            ),
            approval_status=approval,
        )
        self.assertEqual(due["decision"], "DUE_SEGMENT_VISIBLE_START")
        self.assertEqual(due["actionable_segment"]["run_id"], "pit_20260801")
        self.assertEqual(
            countdown["decision"], "COUNTDOWN_WINDOW_VISIBLE_START"
        )

    def test_running_gate_allows_status_only(self) -> None:
        plan, validation, gate, approval = _inputs(gate_status="RUNNING")
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-08-01T01:05:00+03:00"
            ),
            approval_status=approval,
        )
        self.assertEqual(report["decision"], "STATUS_ONLY_ACTIVE_RUN")
        self.assertEqual(
            report["next_allowed_action"],
            "monitor_current_visible_run_only",
        )

    def test_stopped_incomplete_blocks_progress(self) -> None:
        plan, validation, gate, approval = _inputs(
            gate_status="STOPPED_INCOMPLETE"
        )
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-07-28T22:00:00+03:00"
            ),
            approval_status=approval,
        )
        self.assertEqual(
            report["decision"], "BLOCKED_STOPPED_INCOMPLETE"
        )

    def test_monitor_never_reads_returns_pnl_or_signals(self) -> None:
        plan, validation, gate, approval = _inputs()
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-07-28T22:00:00+03:00"
            ),
            approval_status=approval,
        )
        self.assertEqual(
            report["evidence_boundaries"],
            {
                "returns_read": False,
                "pnl_read": False,
                "signals_read": False,
                "market_payloads_read": False,
                "quality_metadata_only": True,
            },
        )

    def test_accepted_dates_are_distinct(self) -> None:
        plan, validation, gate, approval = _inputs(accepted=0)
        validation["current_accepted_certifications"] = [
            {"scheduled_date": "2026-07-28", "segment_run_id": "one"},
            {"scheduled_date": "2026-07-28", "segment_run_id": "same-date"},
        ]
        report = monitor.summarize_progress(
            plan=plan,
            validation=validation,
            gate=gate,
            now_local=datetime.fromisoformat(
                "2026-07-28T22:00:00+03:00"
            ),
            approval_status=approval,
        )
        self.assertEqual(report["quality"]["accepted_distinct_dates"], 1)


if __name__ == "__main__":
    unittest.main()
