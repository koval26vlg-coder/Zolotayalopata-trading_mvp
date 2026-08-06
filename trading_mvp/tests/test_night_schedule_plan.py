from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import night_schedule_plan as schedule_plan  # noqa: E402
from night_schedule_plan import (  # noqa: E402
    authorize_collection_segment,
    build_night_schedule_plan,
    validate_night_schedule_plan,
)
from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_quality_ledger(path: Path, contract: dict, dates: list[str]) -> None:
    rows = []
    for index, scheduled_date in enumerate(dates, start=1):
        body = {
            "schema": "pit_universe_v2_quality_certification_v1",
            "track_key": f"{contract['id']}|{contract['required_data_type']}",
            "hypothesis_id": contract["id"],
            "data_type": contract["required_data_type"],
            "hypothesis_contract_sha256": contract["contract_hash"],
            "segment_run_id": f"accepted-{index:03d}",
            "scheduled_date": scheduled_date,
            "technical_quality_accepted": True,
        }
        rows.append({**body, "certification_id": hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class NightSchedulePlanTests(unittest.TestCase):
    def _build(self, root: Path, **overrides: object) -> tuple[dict, Path]:
        bank = root / "hypotheses.json"
        _write_json(
            bank,
            {
                "version": "test-v1",
                "hypotheses": [
                    {
                        "id": "pit_universe_membership_drift_reversion_v1",
                        "status": "BANKED_NEEDS_NEW_DATA",
                        "required_data_type": "PIT_UNIVERSE_V2_FORWARD",
                        "contract": build_pit_membership_drift_contract(),
                        "minimum_data": {
                            "days": 120,
                            "portfolio_events": 20,
                            "per_venue_events": 10,
                            "unique_dates": 10,
                        },
                    }
                ],
            },
        )
        goal = root / "goal.md"
        goal.write_text("# Canonical goal fixture\n", encoding="utf-8")
        output = root / "schedule.json"
        arguments: dict[str, object] = {
            "hypothesis_bank_path": bank,
            "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
            "data_type": "PIT_UNIVERSE_V2_FORWARD",
            "goal_path": goal,
            "output_path": output,
            "schedule_start_date": "2026-07-14",
            "nights": 14,
            "segment_start_local": "23:00",
            "segment_duration_sec": 1200,
            "interval_sec": 300,
            "output_root": str(root / "data"),
            "created_at_utc": "2026-07-14T13:30:00+00:00",
        }
        arguments.update(overrides)
        return build_night_schedule_plan(**arguments), output

    def test_builds_immutable_planonly_schedule_with_one_bounded_segment_per_night(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result, output = self._build(Path(temp_dir))
            plan = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["decision"], "AWAIT_EXPLICIT_SCHEDULE_APPROVAL")
            self.assertEqual(plan["schema"], "fast_first_night_schedule_plan_v2")
            self.assertEqual(plan["mode"], "PlanOnly")
            self.assertFalse(plan["schedule_approved"])
            self.assertFalse(plan["collection_started"])
            self.assertFalse(plan["network_access"])
            self.assertEqual(len(plan["segments"]), 14)
            self.assertEqual(plan["segments"][0]["start_local"], "2026-07-14T23:00:00+03:00")
            self.assertEqual(plan["segments"][-1]["start_local"], "2026-07-27T23:00:00+03:00")
            self.assertTrue(all(item["duration_sec"] == 1200 for item in plan["segments"]))
            self.assertTrue(all(item["end_before_night_deadline"] for item in plan["segments"]))
            self.assertEqual(plan["coverage_projection"]["scheduled_unique_dates"], 14)
            self.assertEqual(plan["coverage_projection"]["required_days"], 120)
            self.assertFalse(plan["coverage_projection"]["minimum_data_reached_by_this_schedule"])
            self.assertEqual(plan["next_allowed_action"], "await_explicit_night_schedule_approval")
            stage = plan["sealed_schedule"]["collection_stage"]
            self.assertEqual(stage["name"], "train_accrual")
            self.assertEqual(stage["initial_accepted_distinct_dates"], 0)
            self.assertEqual(stage["stage_target_distinct_dates"], 20)
            self.assertEqual(stage["maximum_new_accepted_dates"], 20)
            self.assertIsNone(stage["upstream_train_feasibility"])
            self.assertEqual(plan["plan_hash"], plan["sealed_schedule_hash"])
            runtime_tools = plan["sealed_schedule"]["runtime_tools"]
            for name, relative_path in (
                ("schedule_planner", "trading_mvp/src/night_schedule_plan.py"),
                ("visible_wrapper", "tools/start_pit_universe_snapshot_collect_visible.ps1"),
                ("collector", "trading_mvp/src/pit_universe_snapshot_collector.py"),
                ("public_probe_client", "trading_mvp/src/pit_universe_public_probe.py"),
                ("approval_script", "tools/approve_trading_night_schedule.ps1"),
                ("status_tool", "trading_mvp/src/night_schedule_status.py"),
                ("quality_certifier", "trading_mvp/src/night_schedule_quality.py"),
                ("segment_quality_evaluator", "trading_mvp/src/pit_universe_snapshot_quality.py"),
                ("hypothesis_contract_validator", "trading_mvp/src/hypothesis_contract.py"),
                ("costs_module", "trading_mvp/src/costs.py"),
                ("feasibility_estimator", "trading_mvp/src/feasibility_gate.py"),
                ("membership_drift_evaluator", "trading_mvp/src/pit_membership_drift_evaluator.py"),
            ):
                expected_path = (Path(__file__).resolve().parents[2] / relative_path).resolve()
                self.assertEqual(runtime_tools[name]["path"], str(expected_path))
                self.assertEqual(
                    runtime_tools[name]["sha256"],
                    hashlib.sha256(expected_path.read_bytes()).hexdigest(),
                )
            self.assertEqual(
                plan["sealed_schedule"]["execution_config"],
                {
                    "timeout_sec": 10,
                    "min_contracts_per_exchange": 50,
                    "min_free_disk_gib": 5.0,
                },
            )
            self.assertEqual(
                plan["sealed_schedule"]["quality_policy"],
                {
                    "policy_version": "pit_universe_v2_segment_quality_v3",
                    "min_exchanges_per_cycle": 2,
                    "max_error_cycle_ratio": 0.05,
                    "max_duplicate_snapshot_keys": 0,
                    "minimum_dual_venue_bbo_size_coverage": 0.95,
                    "require_final": True,
                    "require_positive_rows": True,
                    "reject_any_thin_exchange_cycle": True,
                    "max_clock_skew_sec": 60,
                    "required_distinct_days": 120,
                    "train_feasibility_distinct_days": 20,
                    "oos_accrual_requires_feasibility_pass": True,
                },
            )
            contract = build_pit_membership_drift_contract()
            self.assertEqual(plan["sealed_schedule"]["hypothesis_contract"], contract)
            self.assertEqual(
                plan["sealed_schedule"]["hypothesis_contract_sha256"],
                contract["contract_hash"],
            )
            self.assertEqual(plan["hypothesis"]["contract_hash"], contract["contract_hash"])
            self.assertEqual(validate_night_schedule_plan(output, plan["plan_hash"])["verdict"], "VALID")
            first_command = plan["segments"][0]["command_after_approval"]
            self.assertIn("start_pit_universe_snapshot_collect_visible.ps1", first_command)
            self.assertIn('-ApprovedNotBefore "2026-07-14T23:00:00+03:00"', first_command)
            self.assertIn('-ApprovedNotLaterThan "2026-07-15T07:00:00+03:00"', first_command)
            self.assertIn("-MinFreeDiskGiB 5", first_command)
            self.assertIn(f'-SchedulePlanPath "{output.resolve()}"', first_command)
            self.assertIn(f"-ExpectedSchedulePlanHash {plan['plan_hash']}", first_command)

    def test_plan_is_deterministic_except_creation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared_output_root = str(root / "data")
            first, _ = self._build(root / "first", output_root=shared_output_root)
            second, _ = self._build(root / "second", output_root=shared_output_root)

            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertEqual(first["sealed_schedule"], second["sealed_schedule"])

    def test_runtime_provenance_only_blocks_collection_data_plane_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = {}
            for name in schedule_plan.RUNTIME_TOOL_NAMES:
                path = root / f"{name}.txt"
                path.write_text(f"original-{name}\n", encoding="utf-8")
                records[name] = {
                    "path": str(path.resolve()),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            schedule_plan._validate_runtime_tools(records)

            governance = Path(records["costs_module"]["path"])
            governance.write_text("changed-governance-tool\n", encoding="utf-8")
            schedule_plan._validate_runtime_tools(records)

            collector = Path(records["collector"]["path"])
            collector.write_text("changed-collector\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "runtime tool collector provenance hash mismatch"):
                schedule_plan._validate_runtime_tools(records)

    def test_schedule_tolerates_unrelated_bank_and_goal_drift_but_not_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _result, output = self._build(root)
            plan = json.loads(output.read_text(encoding="utf-8"))
            bank_path = Path(plan["hypothesis_bank"]["path"])
            goal_path = Path(plan["goal_document"]["path"])

            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            bank["unrelated_note"] = "does not change the sealed hypothesis"
            _write_json(bank_path, bank)
            goal_path.write_text("# Updated editorial goal text\n", encoding="utf-8")
            self.assertEqual(
                validate_night_schedule_plan(output, plan["plan_hash"])["verdict"],
                "VALID",
            )

            bank["hypotheses"][0]["contract"]["hold_days"] = 999
            _write_json(bank_path, bank)
            with self.assertRaisesRegex(ValueError, "sealed hypothesis contract differs"):
                validate_night_schedule_plan(output, plan["plan_hash"])

    def test_rejects_more_than_fourteen_nights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "nights must be in \\[1, 14\\]"):
                self._build(Path(temp_dir), nights=15)

    def test_rejects_segment_longer_than_three_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "segment_duration_sec must be in \\[1, 10800\\]"):
                self._build(Path(temp_dir), segment_duration_sec=10801)

    def test_rejects_segment_that_crosses_0700_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must finish by 07:00"):
                self._build(
                    Path(temp_dir),
                    segment_start_local="06:30",
                    segment_duration_sec=3600,
                )

    def test_rejects_data_type_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "requires data_type=PIT_UNIVERSE_V2_FORWARD"):
                self._build(Path(temp_dir), data_type="DENSE_WS_SEGMENTED")

    def test_refuses_to_overwrite_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._build(root)
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite immutable"):
                self._build(root)

    def test_train_schedule_cannot_exceed_dates_remaining_before_feasibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract = build_pit_membership_drift_contract()
            ledger = root / "quality.jsonl"
            _write_quality_ledger(
                ledger,
                contract,
                [f"2026-06-{day:02d}" for day in range(1, 16)],
            )

            with self.assertRaisesRegex(ValueError, "only 5 accepted train dates remain"):
                self._build(root / "too-many", quality_ledger_path=ledger, nights=6)

            _, output = self._build(root / "bounded", quality_ledger_path=ledger, nights=5)
            plan = json.loads(output.read_text(encoding="utf-8"))
            stage = plan["sealed_schedule"]["collection_stage"]
            self.assertEqual(stage["initial_accepted_distinct_dates"], 15)
            self.assertEqual(stage["maximum_new_accepted_dates"], 5)

    def test_segment_authorization_stops_when_train_gate_has_been_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract = build_pit_membership_drift_contract()
            ledger = root / "quality.jsonl"
            first_dates = [f"2026-06-{day:02d}" for day in range(1, 20)]
            _write_quality_ledger(ledger, contract, first_dates)
            _, output = self._build(root / "schedule", quality_ledger_path=ledger, nights=1)
            plan = json.loads(output.read_text(encoding="utf-8"))

            allowed = authorize_collection_segment(
                output,
                plan["plan_hash"],
                plan["segments"][0]["run_id"],
            )
            self.assertEqual(allowed["verdict"], "AUTHORIZED")
            self.assertEqual(allowed["remaining_stage_dates_before_run"], 1)

            _write_quality_ledger(ledger, contract, first_dates + ["2026-06-20"])
            with self.assertRaisesRegex(ValueError, "train feasibility gate has already been reached"):
                authorize_collection_segment(
                    output,
                    plan["plan_hash"],
                    plan["segments"][0]["run_id"],
                )

    def test_validation_rejects_tampered_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, output = self._build(Path(temp_dir))
            plan = json.loads(output.read_text(encoding="utf-8"))
            plan["segments"][0]["duration_sec"] = 1199
            output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "runtime segment mismatch"):
                validate_night_schedule_plan(output, plan["plan_hash"])


if __name__ == "__main__":
    unittest.main()
