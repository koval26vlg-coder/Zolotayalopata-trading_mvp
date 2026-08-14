from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pit_schedule_horizon import (  # noqa: E402
    _build_extension_plan_immutable,
    _load_json,
    _load_jsonl,
    _write_json_immutable,
    build_horizon_audit,
    compute_schedule_horizon,
)
from pit_train_progress_monitor import summarize_progress  # noqa: E402


TZ = timezone(timedelta(hours=3))
CONTRACT_HASH = "a" * 64


def make_plan(*, first_date: str, nights: int, target: int = 20) -> dict:
    first = datetime.fromisoformat(f"{first_date}T01:00:00+03:00")
    segments = []
    for index in range(nights):
        start = first + timedelta(days=index)
        segments.append(
            {
                "sequence": index + 1,
                "run_id": f"run-{index + 1}",
                "start_local": start.isoformat(),
                "hard_deadline_local": start.replace(
                    hour=7,
                    minute=0,
                ).isoformat(),
            }
        )
    return {
        "sealed_schedule": {
            "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
            "data_type": "PIT_UNIVERSE_V2_FORWARD",
            "hypothesis_contract_sha256": CONTRACT_HASH,
            "collection_stage": {
                "name": "train_accrual",
                "stage_target_distinct_dates": target,
            },
            "segments": segments,
        }
    }


def quality_row(
    scheduled_date: str,
    accepted: bool,
    *,
    contract_hash: str = CONTRACT_HASH,
) -> dict:
    return {
        "schema": "pit_universe_v2_quality_certification_v1",
        "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
        "data_type": "PIT_UNIVERSE_V2_FORWARD",
        "hypothesis_contract_sha256": contract_hash,
        "scheduled_date": scheduled_date,
        "technical_quality_accepted": accepted,
    }


class PitScheduleHorizonTests(unittest.TestCase):
    def test_extension_validation_failure_removes_published_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension_path = Path(temp_dir) / "extension.json"

            def fake_build(**kwargs: object) -> dict[str, object]:
                output_path = Path(str(kwargs["output_path"])).resolve()
                plan_hash = "c" * 64
                payload = {
                    "mode": "PlanOnly",
                    "plan_artifact_path": str(output_path),
                    "plan_hash": plan_hash,
                    "schedule_approved": False,
                    "collection_started": False,
                    "segments": [
                        {
                            "command_after_approval": (
                                f'pwsh -File collect.ps1 -Plan "{output_path}"'
                            )
                        }
                    ],
                }
                output_path.write_text(json.dumps(payload), encoding="utf-8")
                return {
                    "output_path": str(output_path),
                    "output_sha256": hashlib.sha256(
                        output_path.read_bytes()
                    ).hexdigest(),
                    "plan_hash": plan_hash,
                    "nights": 1,
                }

            def fake_validate(path: str | Path, _expected: str) -> dict[str, object]:
                target = Path(path).resolve()
                if target == extension_path.resolve():
                    raise ValueError("final validation failed")
                return {
                    "plan_file_sha256": hashlib.sha256(target.read_bytes()).hexdigest()
                }

            with (
                patch(
                    "pit_schedule_horizon.build_night_schedule_plan",
                    side_effect=fake_build,
                ),
                patch(
                    "pit_schedule_horizon.validate_night_schedule_plan",
                    side_effect=fake_validate,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "final validation failed"):
                    _build_extension_plan_immutable(
                        extension_target=extension_path,
                        plan_kwargs={"nights": 1},
                    )

            self.assertFalse(extension_path.exists())

    def test_rejects_ledger_change_during_schedule_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path = root / "quality.jsonl"
            ledger_path.write_text(
                json.dumps(quality_row("2026-07-14", True)) + "\n",
                encoding="utf-8",
            )
            plan = make_plan(first_date="2026-07-29", nights=1, target=2)
            plan["sealed_schedule"]["collection_stage"]["quality_ledger"] = {
                "path": str(ledger_path)
            }
            plan_path = root / "schedule.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            plan_file_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            audit_path = root / "audit.json"

            def mutate_ledger(*_args: object) -> dict[str, object]:
                replacement = quality_row("2026-07-15", True)
                replacement["certification_id"] = "invalid"
                ledger_path.write_text(
                    json.dumps(replacement) + "\n",
                    encoding="utf-8",
                )
                return {
                    "plan_file_sha256": plan_file_sha256,
                    "quality_ledger_path": str(ledger_path.resolve()),
                    "current_accepted_distinct_dates": 1,
                }

            with patch(
                "pit_schedule_horizon.validate_night_schedule_plan",
                side_effect=mutate_ledger,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "quality ledger changed during horizon build",
                ):
                    build_horizon_audit(
                        plan_path=plan_path,
                        expected_plan_hash="b" * 64,
                        observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
                        audit_output_path=audit_path,
                    )

            self.assertFalse(audit_path.exists())

    def test_extension_plan_rebinds_temp_path_before_immutable_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path = root / "quality.jsonl"
            ledger_path.write_text(
                json.dumps(quality_row("2026-07-14", True)) + "\n",
                encoding="utf-8",
            )
            plan = make_plan(first_date="2026-07-29", nights=1, target=3)
            plan["sealed_schedule"].update(
                {
                    "segment_duration_sec": 1200,
                    "interval_sec": 300,
                    "output_root": str(root / "outputs"),
                }
            )
            plan["sealed_schedule"]["collection_stage"]["quality_ledger"] = {
                "path": str(ledger_path)
            }
            plan["hypothesis_bank"] = {"path": str(root / "bank.json")}
            plan["goal_document"] = {"path": str(root / "goal.json")}
            plan_path = root / "schedule.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            plan_file_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            audit_path = root / "audit.json"
            extension_path = root / "extension.json"
            built_path: dict[str, Path] = {}

            def fake_build(**kwargs: object) -> dict[str, object]:
                output_path = Path(str(kwargs["output_path"])).resolve()
                self.assertFalse(output_path.exists())
                built_path["value"] = output_path
                plan_hash = "c" * 64
                payload = {
                    "mode": "PlanOnly",
                    "plan_artifact_path": str(output_path),
                    "plan_hash": plan_hash,
                    "schedule_approved": False,
                    "collection_started": False,
                    "segments": [
                        {
                            "command_after_approval": (
                                f'pwsh -File collect.ps1 -Plan "{output_path}"'
                            )
                        }
                    ],
                }
                output_path.write_text(json.dumps(payload), encoding="utf-8")
                return {
                    "output_path": str(output_path),
                    "output_sha256": hashlib.sha256(
                        output_path.read_bytes()
                    ).hexdigest(),
                    "plan_hash": plan_hash,
                    "nights": int(kwargs["nights"]),
                }

            def fake_validate(path: str | Path, _expected: str) -> dict[str, object]:
                target = Path(path).resolve()
                if target == plan_path.resolve():
                    return {
                        "plan_file_sha256": plan_file_sha256,
                        "quality_ledger_path": str(ledger_path.resolve()),
                        "current_accepted_distinct_dates": 1,
                    }
                return {
                    "plan_file_sha256": hashlib.sha256(target.read_bytes()).hexdigest()
                }

            with (
                patch(
                    "pit_schedule_horizon.build_night_schedule_plan",
                    side_effect=fake_build,
                ),
                patch(
                    "pit_schedule_horizon.validate_night_schedule_plan",
                    side_effect=fake_validate,
                ),
            ):
                result = build_horizon_audit(
                    plan_path=plan_path,
                    expected_plan_hash="b" * 64,
                    observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
                    audit_output_path=audit_path,
                    extension_output_path=extension_path,
                )

            extension = json.loads(extension_path.read_text(encoding="utf-8"))
            extension_text = extension_path.read_text(encoding="utf-8")
            self.assertNotEqual(built_path["value"], extension_path.resolve())
            self.assertEqual(
                extension["plan_artifact_path"], str(extension_path.resolve())
            )
            self.assertNotIn(str(built_path["value"]), extension_text)
            self.assertEqual(
                result["extension_proposal"]["output_sha256"],
                hashlib.sha256(extension_path.read_bytes()).hexdigest(),
            )

    def test_audit_binds_exact_builder_and_single_read_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path = root / "quality.jsonl"
            ledger_path.write_text(
                json.dumps(quality_row("2026-07-14", True)) + "\n",
                encoding="utf-8",
            )
            plan = make_plan(first_date="2026-07-29", nights=1, target=2)
            plan["sealed_schedule"]["collection_stage"]["quality_ledger"] = {
                "path": str(ledger_path)
            }
            plan_path = root / "schedule.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            plan_file_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            audit_path = root / "audit.json"

            with patch(
                "pit_schedule_horizon.validate_night_schedule_plan",
                return_value={
                    "plan_file_sha256": plan_file_sha256,
                    "quality_ledger_path": str(ledger_path.resolve()),
                    "current_accepted_distinct_dates": 1,
                },
            ):
                result = build_horizon_audit(
                    plan_path=plan_path,
                    expected_plan_hash="b" * 64,
                    observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
                    audit_output_path=audit_path,
                )

            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit_tool = Path(audit["audit_tool"]["path"])
            self.assertEqual(
                result["decision"], "CURRENT_SCHEDULE_SUFFICIENT_FOR_TRAIN_GATE"
            )
            self.assertEqual(
                audit["source_schedule"]["file_sha256"],
                plan_file_sha256,
            )
            self.assertEqual(
                audit["audit_tool"]["file_sha256"],
                hashlib.sha256(audit_tool.read_bytes()).hexdigest(),
            )

    def test_rejects_non_boolean_quality_acceptance(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=1, target=2)
        row = quality_row("2026-07-14", True)
        row["technical_quality_accepted"] = "false"

        with self.assertRaisesRegex(
            ValueError,
            "technical_quality_accepted must be boolean",
        ):
            compute_schedule_horizon(
                plan,
                [row],
                observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
            )

    def test_rejects_invalid_quality_scheduled_date(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=1, target=2)

        with self.assertRaisesRegex(ValueError, "scheduled_date"):
            compute_schedule_horizon(
                plan,
                [quality_row("not-a-date", True)],
                observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
            )

    def test_strict_json_rejects_duplicate_keys_and_nan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            duplicate_path = Path(temp_dir) / "duplicate.json"
            duplicate_path.write_text(
                '{"schema": "a", "schema": "b"}', encoding="utf-8"
            )
            nan_path = Path(temp_dir) / "nan.json"
            nan_path.write_text('{"value": NaN}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                _load_json(duplicate_path)
            with self.assertRaisesRegex(ValueError, "non-finite JSON constant"):
                _load_json(nan_path)

    def test_strict_jsonl_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = Path(temp_dir) / "quality.jsonl"
            ledger_path.write_text(
                '{"schema": "a", "schema": "b"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                _load_jsonl(ledger_path)

    def test_immutable_writer_does_not_overwrite_racing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "audit.json"
            original_link = os.link

            def create_target_before_link(source: str, destination: str) -> None:
                target.write_text("sentinel", encoding="utf-8")
                original_link(source, destination)

            with patch(
                "pit_schedule_horizon.os.link",
                side_effect=create_target_before_link,
            ):
                with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                    _write_json_immutable(target, {"new": True})

            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")
            self.assertEqual(list(target.parent.glob("*.tmp.*")), [])

    def test_detects_four_date_shortfall_after_two_expired_windows(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-16", False),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 7, 30, 21, 0, tzinfo=TZ),
        )

        self.assertEqual(result["decision"], "PLANONLY_EXTENSION_REQUIRED")
        self.assertEqual(result["accepted_distinct_dates"], 4)
        self.assertEqual(
            result["expired_unaccepted_dates"], ["2026-07-29", "2026-07-30"]
        )
        self.assertEqual(result["reachable_scheduled_dates"], 12)
        self.assertEqual(result["maximum_reachable_distinct_dates"], 16)
        self.assertEqual(result["train_gate_shortfall_dates"], 4)
        self.assertEqual(result["observed_quality_acceptance_rate"], 0.8)
        self.assertEqual(result["recommended_extension_nights"], 5)
        self.assertEqual(result["extension_start_date"], "2026-08-12")

    def test_extension_start_skips_windows_expired_after_source_schedule(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-16", False),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 8, 13, 10, 36, tzinfo=TZ),
        )

        self.assertEqual(result["extension_start_date"], "2026-08-14")

    def test_extension_can_use_today_when_segment_start_is_still_future(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)

        result = compute_schedule_horizon(
            plan,
            [quality_row("2026-07-14", True)],
            observed_at=datetime(2026, 8, 13, 0, 30, tzinfo=TZ),
        )

        self.assertEqual(result["extension_start_date"], "2026-08-13")

    def test_caps_rate_adjusted_extension_at_remaining_stage_capacity(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-16", False),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
            quality_row("2026-07-31", True),
            quality_row("2026-08-02", True),
            quality_row("2026-08-03", True),
            quality_row("2026-08-04", True),
            quality_row("2026-08-10", True),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 8, 10, 19, 49, tzinfo=TZ),
        )

        self.assertEqual(result["accepted_distinct_dates"], 9)
        self.assertEqual(result["reachable_scheduled_dates"], 1)
        self.assertEqual(result["train_gate_shortfall_dates"], 10)
        self.assertEqual(result["rate_adjusted_extension_nights"], 12)
        self.assertEqual(result["remaining_stage_capacity_nights"], 11)
        self.assertEqual(result["recommended_extension_nights"], 11)
        self.assertTrue(result["extension_capacity_limited_by_stage"])
        self.assertTrue(result["single_plan_extension_capacity_sufficient"])

    def test_reports_sufficient_when_current_horizon_can_reach_target(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=16)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
        )

        self.assertEqual(
            result["decision"],
            "CURRENT_SCHEDULE_SUFFICIENT_FOR_TRAIN_GATE",
        )
        self.assertEqual(result["train_gate_shortfall_dates"], 0)
        self.assertEqual(result["recommended_extension_nights"], 0)
        self.assertIsNone(result["extension_start_date"])

    def test_ignores_quality_rows_from_another_contract(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=1, target=2)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True, contract_hash="b" * 64),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
        )

        self.assertEqual(result["accepted_dates"], ["2026-07-14"])
        self.assertEqual(result["maximum_reachable_distinct_dates"], 2)
        self.assertEqual(
            result["decision"],
            "CURRENT_SCHEDULE_SUFFICIENT_FOR_TRAIN_GATE",
        )

    def test_horizon_and_progress_projection_share_expiry_semantics(
        self,
    ) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-16", False),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]
        observed_at = datetime(2026, 7, 30, 21, 0, tzinfo=TZ)
        horizon = compute_schedule_horizon(
            plan,
            rows,
            observed_at=observed_at,
        )
        accepted = [
            {
                "scheduled_date": str(row["scheduled_date"]),
                "segment_run_id": f"accepted-{row['scheduled_date']}",
            }
            for row in rows
            if row["technical_quality_accepted"]
        ]
        progress = summarize_progress(
            plan=plan,
            validation={
                "plan_path": r"E:\schedule.json",
                "plan_hash": "b" * 64,
                "plan_file_sha256": "c" * 64,
                "collection_stage": "train_accrual",
                "current_accepted_certifications": accepted,
            },
            gate={
                "gate_status": "READY_FOR_POSTPROCESS",
                "run_id": "sidecar",
                "replay_allowed": False,
                "process_ids": [],
            },
            now_local=observed_at,
            approval_status={"status": "HASH_VALID_ACTIVE"},
        )

        self.assertEqual(
            progress["train_eta"]["scheduled_new_dates_available"],
            horizon["reachable_scheduled_dates"],
        )
        self.assertEqual(
            progress["train_eta"]["expired_uncertified_dates"],
            horizon["expired_unaccepted_dates"],
        )
        self.assertEqual(
            progress["train_eta"]["projected_accepted_dates_at_schedule_end"],
            horizon["maximum_reachable_distinct_dates"],
        )
        self.assertEqual(
            progress["train_eta"]["additional_dates_needed_after_schedule"],
            horizon["train_gate_shortfall_dates"],
        )


if __name__ == "__main__":
    unittest.main()
