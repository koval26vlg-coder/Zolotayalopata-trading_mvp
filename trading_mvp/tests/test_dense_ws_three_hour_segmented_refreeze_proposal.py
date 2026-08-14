from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
MODULE_PATH = SRC / "dense_ws_three_hour_segmented_refreeze_proposal.py"


def _canonical_hash(value: dict, *, excluded_key: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluded_key}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_subject(testcase: unittest.TestCase) -> ModuleType:
    if not MODULE_PATH.is_file():
        testcase.fail(f"missing implementation module: {MODULE_PATH}")
    spec = importlib.util.spec_from_file_location(
        "dense_ws_three_hour_segmented_refreeze_proposal",
        MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        testcase.fail("unable to load implementation module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DenseWsThreeHourSegmentedRefreezeProposalTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> dict[str, Path | str]:
        continuous_policy_path = root / "continuous-policy.json"
        _write(
            continuous_policy_path,
            {
                "schema": "trading_mvp_continuous_production_policy_v1",
                "run_windows": {
                    "timezone": "Europe/Volgograd",
                    "utc_offset_minutes": 180,
                    "new_campaign_start_local": "19:00",
                    "weekday_hard_stop_local": "08:00",
                    "weekend": {
                        "opens": "FRIDAY 19:00",
                        "hard_stop": "MONDAY 08:00",
                        "fresh_start_allowed_inside_open_envelope": True,
                    },
                },
                "approval": {
                    "request_lead_minutes": 30,
                    "required_before_every_long_campaign": True,
                },
                "runtime": {
                    "short_offline_task_max_runtime_sec": 1800,
                    "shutdown_grace_sec": 1800,
                },
                "invariants": {
                    "single_market_data_writer": True,
                    "grid_and_retune_forbidden": True,
                    "live_orders": False,
                    "private_api_keys": False,
                    "real_capital": False,
                    "leverage": False,
                    "margin": False,
                },
            },
        )

        autopilot_policy_path = root / "autopilot-policy.json"
        _write(
            autopilot_policy_path,
            {
                "schema": "trading_mvp_autopilot_policy_v1",
                "policy_id": "autopilot-fixture",
                "status": "ACTIVE",
            },
        )

        pointer_path = root / "pit-pointer.json"
        _write(
            pointer_path,
            {
                "schema": "trading_mvp_autopilot_schedule_pointer_v1",
                "status": "ACTIVE",
                "project": "trading_mvp",
                "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
                "data_type": "PIT_UNIVERSE_V2_FORWARD",
                "collection_stage": "train_accrual",
                "plan_path": str(root / "pit-plan.json"),
                "plan_hash": "3" * 64,
                "train_target_distinct_dates": 20,
            },
        )

        contract_path = root / "dense-contract.json"
        contract = {
            "schema": "trading_mvp_dense_ws_microstructure_contract_v1",
            "mode": "PlanOnly",
            "campaign_id": "dense_ws_microstructure_regime_filter_v1_20260810_aef_24h",
            "hypothesis_id": "dense_ws_microstructure_regime_filter_v1",
            "data_type": "DENSE_WS_SEGMENTED",
            "authorization_scope": "contract-freeze and immutable PlanOnly only",
            "research_only": True,
            "actual_collection_allowed": False,
            "network_access": False,
            "source_candidate": {
                "candidate_contract_hash": "4" * 64,
                "frozen_candidate": {
                    "target_writer_sec": 86_400,
                    "minimum_writer_sec": 86_400,
                    "segment_sec": 3_600,
                    "minimum_valid_segments": 8,
                    "uninterrupted_required": True,
                    "phases": [
                        {
                            "phase_id": "phase_01",
                            "writer_duration_sec": 86_400,
                        }
                    ],
                },
            },
            "universe_contract": {
                "venues": ["mexc", "gateio"],
                "quote": "USDT",
                "market_type": "spot",
            },
            "raw_schema_contract": {"schema_version": 1},
            "segment_validity_contract": {
                "full_segment_sec": 3_600,
                "terminal_partial_segment_min_sec": 900,
                "terminal_partial_counts_toward_min_valid_segments": False,
                "campaign_minimums": {
                    "writer_duration_sec": 86_400,
                    "valid_full_segments": 8,
                },
                "gap_policy": {
                    "planned_gaps_do_not_count_as_writer_time": True,
                    "invalid_segments_are_never_stitched_as_valid_evidence": True,
                },
            },
            "causal_regime_contract": {"observation_grid_sec": 5},
            "execution_sampling_contract": {
                "sample_interval_sec": 5,
                "minimum_eligible_snapshots": 180,
            },
            "cost_risk_no_grid_contract": {
                "no_grid": {
                    "parameter_combinations": 1,
                    "grid_search": False,
                    "retune": False,
                },
                "risk": {
                    "research_simulation_only": True,
                    "leverage": False,
                    "margin": False,
                    "real_capital": False,
                },
            },
            "evidence_and_acceptance_contract": {
                "collection_can_accept_trading_hypothesis": False,
                "collection_can_open_oos": False,
                "collection_can_compute_returns_or_pnl": False,
            },
        }
        contract["contract_hash"] = _canonical_hash(
            contract,
            excluded_key="contract_hash",
        )
        _write(contract_path, contract)

        plan_path = root / "dense-plan.json"
        plan = {
            "schema": "trading_mvp_dense_ws_campaign_planonly_v1",
            "mode": "PlanOnly",
            "campaign_id": contract["campaign_id"],
            "hypothesis_id": contract["hypothesis_id"],
            "actual_collection_allowed": False,
            "network_access": False,
            "approval_state": "NOT_APPROVED",
            "window": {
                "target_writer_sec": 86_400,
                "max_runtime_sec": 88_200,
            },
            "contract": {"contract_hash": contract["contract_hash"]},
        }
        plan["plan_hash"] = _canonical_hash(plan, excluded_key="plan_hash")
        _write(plan_path, plan)

        return {
            "continuous_policy_path": continuous_policy_path,
            "continuous_policy_sha256": _sha256(continuous_policy_path),
            "autopilot_policy_path": autopilot_policy_path,
            "autopilot_policy_sha256": _sha256(autopilot_policy_path),
            "pointer_path": pointer_path,
            "pointer_sha256": _sha256(pointer_path),
            "contract_path": contract_path,
            "contract_sha256": _sha256(contract_path),
            "contract_hash": contract["contract_hash"],
            "plan_path": plan_path,
            "plan_sha256": _sha256(plan_path),
            "plan_hash": plan["plan_hash"],
        }

    def _build(self, root: Path, fixture: dict[str, Path | str]) -> dict:
        subject = _load_subject(self)
        return subject.build_proposal(
            source_contract_path=fixture["contract_path"],
            expected_source_contract_sha256=str(fixture["contract_sha256"]),
            expected_source_contract_hash=str(fixture["contract_hash"]),
            source_plan_path=fixture["plan_path"],
            expected_source_plan_sha256=str(fixture["plan_sha256"]),
            expected_source_plan_hash=str(fixture["plan_hash"]),
            continuous_policy_path=fixture["continuous_policy_path"],
            expected_continuous_policy_sha256=str(
                fixture["continuous_policy_sha256"]
            ),
            autopilot_policy_path=fixture["autopilot_policy_path"],
            expected_autopilot_policy_sha256=str(
                fixture["autopilot_policy_sha256"]
            ),
            pit_pointer_path=fixture["pointer_path"],
            expected_pit_pointer_sha256=str(fixture["pointer_sha256"]),
            expected_pit_plan_hash="3" * 64,
            pit_runtime_status="NO_PENDING_SEGMENT",
            pit_guard_observed_at_utc="2026-08-13T07:16:06+00:00",
            requested_start_local="2026-08-13T19:00:00+03:00",
            generated_at_utc="2026-08-13T07:20:00+00:00",
            output_path=root / "proposal.json",
        )

    def test_builds_minimum_calendar_schedule_with_nine_bounded_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            payload = self._build(root, fixture)

            schedule = payload["proposed_schedule_contract"]
            segments = schedule["segments"]
            self.assertEqual(len(segments), 9)
            self.assertEqual(schedule["total_writer_sec"], 89_100)
            self.assertGreaterEqual(schedule["total_writer_sec"], 86_400)
            self.assertEqual(schedule["total_valid_full_segments_planned"], 18)
            self.assertEqual(segments[0]["start_local"], "2026-08-13T19:00:00+03:00")
            self.assertEqual(segments[3]["hard_end_local"], "2026-08-14T07:15:00+03:00")
            self.assertEqual(segments[4]["start_local"], "2026-08-14T19:00:00+03:00")
            self.assertEqual(segments[-1]["hard_end_local"], "2026-08-15T10:20:00+03:00")
            for segment in segments:
                self.assertEqual(segment["writer_duration_sec"], 9_900)
                self.assertEqual(segment["max_runtime_sec"], 10_800)
                self.assertLessEqual(segment["max_runtime_sec"], 3 * 60 * 60)
                self.assertEqual(segment["finalization_headroom_sec"], 900)
                self.assertEqual(segment["full_durable_segments_planned"], 2)
                self.assertEqual(segment["terminal_partial_sec"], 2_700)

    def test_is_fail_closed_planonly_and_preserves_scientific_contract_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            payload = self._build(root, fixture)

            boundary = payload["authorization_boundary"]
            self.assertEqual(payload["mode"], "PlanOnly")
            self.assertEqual(payload["status"], "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL")
            self.assertFalse(boundary["implementation_authorized"])
            self.assertFalse(boundary["collector_launch_authorized"])
            self.assertFalse(boundary["network_access"])
            self.assertFalse(boundary["approval_receipt_created"])
            self.assertFalse(boundary["output_namespace_created"])
            self.assertFalse(boundary["returns_or_pnl_read"])
            self.assertFalse(boundary["oos_read"])
            self.assertFalse(boundary["grid_or_retune"])
            self.assertFalse(boundary["paper_or_live"])

            contract = json.loads(Path(fixture["contract_path"]).read_text(encoding="utf-8"))
            preserved = payload["preserved_contract_hashes"]
            for name in (
                "universe_contract",
                "raw_schema_contract",
                "segment_validity_contract",
                "causal_regime_contract",
                "execution_sampling_contract",
                "cost_risk_no_grid_contract",
                "evidence_and_acceptance_contract",
            ):
                expected = hashlib.sha256(
                    json.dumps(
                        contract[name],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                self.assertEqual(preserved[name], expected)

    def test_marks_uninterrupted_source_plan_incompatible_and_binds_pit_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            payload = self._build(root, fixture)

            mismatch = payload["source_runtime_incompatibility"]
            self.assertTrue(mismatch["source_uninterrupted_required"])
            self.assertEqual(mismatch["source_plan_max_runtime_sec"], 88_200)
            self.assertEqual(mismatch["current_per_run_cap_sec"], 10_800)
            self.assertFalse(mismatch["source_plan_launchable"])
            self.assertTrue(mismatch["material_schedule_contract_change"])

            pointer = payload["pit_pointer_binding"]
            self.assertEqual(pointer["file_sha256"], fixture["pointer_sha256"])
            self.assertEqual(pointer["plan_hash"], "3" * 64)
            self.assertEqual(pointer["runtime_status"], "NO_PENDING_SEGMENT")
            self.assertTrue(pointer["pointer_change_invalidates_remaining_schedule"])
            self.assertTrue(pointer["due_pit_segment_has_priority"])
            self.assertFalse(pointer["schedule_extension_activated"])

    def test_rejects_stale_hashes_and_non_idle_pit_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            subject = _load_subject(self)

            kwargs = {
                "source_contract_path": fixture["contract_path"],
                "expected_source_contract_sha256": "0" * 64,
                "expected_source_contract_hash": fixture["contract_hash"],
                "source_plan_path": fixture["plan_path"],
                "expected_source_plan_sha256": fixture["plan_sha256"],
                "expected_source_plan_hash": fixture["plan_hash"],
                "continuous_policy_path": fixture["continuous_policy_path"],
                "expected_continuous_policy_sha256": fixture[
                    "continuous_policy_sha256"
                ],
                "autopilot_policy_path": fixture["autopilot_policy_path"],
                "expected_autopilot_policy_sha256": fixture[
                    "autopilot_policy_sha256"
                ],
                "pit_pointer_path": fixture["pointer_path"],
                "expected_pit_pointer_sha256": fixture["pointer_sha256"],
                "expected_pit_plan_hash": "3" * 64,
                "pit_runtime_status": "NO_PENDING_SEGMENT",
                "pit_guard_observed_at_utc": "2026-08-13T07:16:06+00:00",
                "requested_start_local": "2026-08-13T19:00:00+03:00",
                "generated_at_utc": "2026-08-13T07:20:00+00:00",
                "output_path": root / "bad-hash.json",
            }
            with self.assertRaisesRegex(ValueError, "source contract file SHA-256 mismatch"):
                subject.build_proposal(**kwargs)

            kwargs["expected_source_contract_sha256"] = fixture["contract_sha256"]
            kwargs["pit_runtime_status"] = "DUE"
            kwargs["output_path"] = root / "due.json"
            with self.assertRaisesRegex(ValueError, "PIT runtime status"):
                subject.build_proposal(**kwargs)

    def test_rejects_executable_source_and_immutable_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            self._build(root, fixture)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite immutable"):
                self._build(root, fixture)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            plan_path = Path(fixture["plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["actual_collection_allowed"] = True
            plan["plan_hash"] = _canonical_hash(plan, excluded_key="plan_hash")
            _write(plan_path, plan)
            fixture["plan_sha256"] = _sha256(plan_path)
            fixture["plan_hash"] = plan["plan_hash"]
            with self.assertRaisesRegex(ValueError, "source plan must remain non-executable"):
                self._build(root, fixture)

    def test_persists_canonical_proposal_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            payload = self._build(root, fixture)
            output = root / "proposal.json"
            persisted = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["proposal_hash"],
                _canonical_hash(payload, excluded_key="proposal_hash"),
            )
            self.assertEqual(
                payload["proposal_hash_method"],
                "sha256_canonical_json_excluding_proposal_hash",
            )


if __name__ == "__main__":
    unittest.main()
