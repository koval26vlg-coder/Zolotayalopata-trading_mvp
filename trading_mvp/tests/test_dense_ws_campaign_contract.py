from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_campaign_contract as campaign  # noqa: E402
import dense_ws_campaign_runner as runner  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DenseWsCampaignContractTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, Path | str]:
        universe = root / "universe.csv"
        universe.write_text(
            "rank,symbol,name,coin_id,market_cap_usd,price_usd\n"
            + "\n".join(
                f"{index},S{index},S{index},s{index},{1000 - index},1"
                for index in range(1, campaign.EXPECTED_UNIVERSE_ROWS + 1)
            )
            + "\n",
            encoding="utf-8",
        )
        universe_hash = _sha(universe)
        old_universe_hash = campaign.EXPECTED_UNIVERSE_SHA256
        campaign.EXPECTED_UNIVERSE_SHA256 = universe_hash

        bank = root / "bank.json"
        policy = root / "policy.json"
        schedule = root / "schedule.json"
        raw_writer = root / "ws_collector.py"
        durable = root / "ws_durable_collector.py"
        _write_json(bank, {"hypotheses": [{"id": campaign.HYPOTHESIS_ID}]})
        _write_json(policy, {"schema": "policy"})
        _write_json(schedule, {"schema": "schedule"})
        raw_writer.write_text("RAW_WRITER = True\n", encoding="utf-8")
        durable.write_text("DURABLE = True\n", encoding="utf-8")

        candidate = {
            "hypothesis_id": campaign.HYPOTHESIS_ID,
            "data_type": campaign.DATA_TYPE,
            "requested_start_local": campaign.EXPECTED_START_LOCAL,
            "window_id": campaign.EXPECTED_WINDOW_ID,
            "window_type": "WEEKEND",
            "hard_deadline_local": campaign.EXPECTED_HARD_DEADLINE_LOCAL,
            "writer_deadline_local": campaign.EXPECTED_WRITER_DEADLINE_LOCAL,
            "target_writer_sec": campaign.EXPECTED_WRITER_SEC,
            "segment_sec": campaign.EXPECTED_SEGMENT_SEC,
            "minimum_valid_segments": 8,
            "minimum_dual_venue_coverage": 0.8,
            "minimum_execution_snapshots": 180,
            "pit_blackouts": [
                {
                    "run_id": "pit_n04",
                    "start_local": "2026-08-01T00:45:00+03:00",
                    "end_local": "2026-08-01T01:40:00+03:00",
                    "pit_start_local": "2026-08-01T01:00:00+03:00",
                    "pit_end_local": "2026-08-01T01:20:00+03:00",
                }
            ],
            "phases": [dict(item) for item in campaign.EXPECTED_PHASES],
            "universe_path": str(universe),
            "universe_sha256": universe_hash,
            "universe_rows": campaign.EXPECTED_UNIVERSE_ROWS,
            "hypothesis_bank_sha256": _sha(bank),
            "continuous_policy_sha256": _sha(policy),
            "pit_schedule_sha256": _sha(schedule),
        }
        candidate_hash = hashlib.sha256(
            json.dumps(
                candidate,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        old_candidate_hash = campaign.EXPECTED_CANDIDATE_HASH
        campaign.EXPECTED_CANDIDATE_HASH = candidate_hash
        feasibility = root / "feasibility.json"
        payload = {
            "schema": campaign.EXPECTED_FEASIBILITY_SCHEMA,
            "mode": "PlanOnly",
            "research_only": True,
            "actual_collection_allowed": False,
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
            "verdict": campaign.EXPECTED_FEASIBILITY_VERDICT,
            "feasibility_reasons": [],
            "frozen_candidate": candidate,
            "candidate_contract_hash": candidate_hash,
            "resource_estimate": {
                "estimated_events": 25_000_000,
                "estimated_disk_bytes": 12_000_000_000,
                "disk_free_bytes_at_plan_time": 800_000_000_000,
                "disk_headroom_multiplier": 66.0,
            },
            "operational_baseline": {
                "sample_segments": [
                    {
                        "path": str(root / "prior.json"),
                        "duration_sec": 10_800,
                        "events_per_sec": 300.0,
                        "bytes_per_sec": 150_000.0,
                    }
                ]
            },
        }
        _write_json(feasibility, payload)
        return {
            "universe": universe,
            "bank": bank,
            "policy": policy,
            "schedule": schedule,
            "raw_writer": raw_writer,
            "durable": durable,
            "feasibility": feasibility,
            "candidate_hash": candidate_hash,
            "old_universe_hash": old_universe_hash,
            "old_candidate_hash": old_candidate_hash,
        }

    def _restore(self, fixture: dict[str, Path | str]) -> None:
        campaign.EXPECTED_UNIVERSE_SHA256 = str(fixture["old_universe_hash"])
        campaign.EXPECTED_CANDIDATE_HASH = str(fixture["old_candidate_hash"])

    def _build_bundle(
        self,
        root: Path,
        fixture: dict[str, Path | str],
    ) -> tuple[dict, dict, Path, Path]:
        contract = campaign.build_contract(
            feasibility_path=fixture["feasibility"],
            expected_feasibility_sha256=_sha(fixture["feasibility"]),
            expected_candidate_hash=str(fixture["candidate_hash"]),
            universe_path=fixture["universe"],
            hypothesis_bank_path=fixture["bank"],
            continuous_policy_path=fixture["policy"],
            pit_schedule_path=fixture["schedule"],
            raw_writer_path=fixture["raw_writer"],
            durable_collector_path=fixture["durable"],
            generated_at_utc="2026-07-31T05:00:00+00:00",
        )
        contract_path = root / "contract.json"
        plan_path = root / "plan.json"

        def build_plan(contract_file_sha256: str) -> dict:
            return campaign.build_plan(
                contract=contract,
                contract_path=contract_path,
                contract_file_sha256=contract_file_sha256,
                feasibility=campaign._read_json(fixture["feasibility"]),
                output_root=root / "output",
                generated_at_utc="2026-07-31T05:00:00+00:00",
            )

        persisted_contract, plan = campaign.write_bundle(
            contract_output_path=contract_path,
            plan_output_path=plan_path,
            contract=contract,
            plan_builder=build_plan,
        )
        return persisted_contract, plan, contract_path, plan_path

    def _build_controlled_bundle(
        self,
        root: Path,
        fixture: dict[str, Path | str],
    ) -> tuple[dict, dict, Path, Path, Path]:
        contract = campaign.build_contract(
            feasibility_path=fixture["feasibility"],
            expected_feasibility_sha256=_sha(fixture["feasibility"]),
            expected_candidate_hash=str(fixture["candidate_hash"]),
            universe_path=fixture["universe"],
            hypothesis_bank_path=fixture["bank"],
            continuous_policy_path=fixture["policy"],
            pit_schedule_path=fixture["schedule"],
            raw_writer_path=fixture["raw_writer"],
            durable_collector_path=fixture["durable"],
            generated_at_utc="2026-07-31T05:00:00+00:00",
        )
        contract_path = root / "contract.json"
        plan_path = root / "plan-ready.json"
        tool_paths = campaign._expected_launch_tool_paths()

        def build_plan(contract_file_sha256: str) -> dict:
            return campaign.build_plan(
                contract=contract,
                contract_path=contract_path,
                contract_file_sha256=contract_file_sha256,
                feasibility=campaign._read_json(fixture["feasibility"]),
                output_root=root / "campaign-output",
                generated_at_utc="2026-07-31T05:00:00+00:00",
                launcher_path=tool_paths["launcher"],
                status_tool_path=tool_paths["status"],
                stop_tool_path=tool_paths["stop"],
                runner_path=tool_paths["runner"],
            )

        persisted_contract, plan = campaign.write_bundle(
            contract_output_path=contract_path,
            plan_output_path=plan_path,
            contract=contract,
            plan_builder=build_plan,
        )
        feasibility = persisted_contract["source_candidate"]["feasibility"]
        runtime_policy = root / "runtime-policy.json"
        _write_json(
            runtime_policy,
            {
                "next_long_campaign": {
                    "status": "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT",
                    "campaign_id": campaign.CAMPAIGN_ID,
                    "hypothesis_id": campaign.HYPOTHESIS_ID,
                    "data_type": campaign.DATA_TYPE,
                    "feasibility_path": str(Path(feasibility["path"]).resolve()),
                    "feasibility_sha256": feasibility["sha256"],
                    "candidate_contract_hash": campaign.EXPECTED_CANDIDATE_HASH,
                    "contract_path": str(contract_path.resolve()),
                    "contract_file_sha256": _sha(contract_path),
                    "contract_hash": persisted_contract["contract_hash"],
                    "plan_path": str(plan_path.resolve()),
                    "plan_file_sha256": _sha(plan_path),
                    "plan_hash": plan["plan_hash"],
                    "plan_approval_state": "NOT_APPROVED",
                    "launch_control_status": plan["launch_controls"]["status"],
                    "window_id": campaign.EXPECTED_WINDOW_ID,
                    "target_writer_sec": campaign.EXPECTED_WRITER_SEC,
                    "max_runtime_sec": campaign.EXPECTED_MAX_RUNTIME_SEC,
                    "actual_collection_allowed": False,
                    "requested_action": plan["next_allowed_action"],
                }
            },
        )
        return persisted_contract, plan, contract_path, plan_path, runtime_policy

    def test_builds_hash_bound_non_starting_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, _ = self._build_bundle(
                    root,
                    fixture,
                )
                campaign.validate_plan(
                    plan,
                    contract=contract,
                    verify_files=True,
                )
            finally:
                self._restore(fixture)

        self.assertFalse(contract["actual_collection_allowed"])
        self.assertEqual(
            contract["execution_sampling_contract"]["max_quote_age_ms"],
            {"mexc": 6000, "gateio": 5000},
        )
        self.assertEqual(
            contract["cost_risk_no_grid_contract"]["cost"]["normal"]["total_cost_bps"],
            69.0,
        )
        self.assertEqual(plan["window"]["target_writer_sec"], 86_400)
        self.assertEqual(
            sum(item["writer_duration_sec"] for item in plan["phases"]), 86_400
        )
        self.assertEqual(
            plan["launch_controls"]["status"],
            "IMPLEMENTATION_REQUIRED_BEFORE_APPROVAL",
        )
        self.assertEqual(plan["plan_hash"], campaign.canonical_plan_hash(plan))

    def test_rehashed_candidate_and_scope_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, _, _, _ = self._build_bundle(root, fixture)
                tampered_candidate = copy.deepcopy(contract)
                tampered_candidate["source_candidate"]["frozen_candidate"][
                    "minimum_valid_segments"
                ] = 1
                tampered_candidate["contract_hash"] = campaign.canonical_contract_hash(
                    tampered_candidate
                )
                with self.assertRaisesRegex(ValueError, "frozen_candidate hash"):
                    campaign.validate_contract(tampered_candidate)

                tampered_scope = copy.deepcopy(contract)
                tampered_scope["authorization_scope"] = "campaign launch approved"
                tampered_scope["contract_hash"] = campaign.canonical_contract_hash(
                    tampered_scope
                )
                with self.assertRaisesRegex(ValueError, "authorization_scope"):
                    campaign.validate_contract(tampered_scope)
            finally:
                self._restore(fixture)

    def test_rehashed_plan_operational_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, _ = self._build_bundle(root, fixture)
                mutations = (
                    (
                        "post_collection",
                        lambda item: item["post_collection"].__setitem__(
                            "automatic_returns_or_pnl", True
                        ),
                    ),
                    (
                        "launch control status",
                        lambda item: item["launch_controls"].__setitem__(
                            "status", "APPROVED"
                        ),
                    ),
                    (
                        "next_allowed_action",
                        lambda item: item.__setitem__(
                            "next_allowed_action", "launch_now"
                        ),
                    ),
                    (
                        "append_safe",
                        lambda item: item["outputs"].__setitem__("append_safe", False),
                    ),
                )
                for label, mutate in mutations:
                    with self.subTest(label=label):
                        tampered = copy.deepcopy(plan)
                        mutate(tampered)
                        tampered["plan_hash"] = campaign.canonical_plan_hash(tampered)
                        with self.assertRaises(ValueError):
                            campaign.validate_plan(
                                tampered,
                                contract=contract,
                                verify_files=True,
                            )
            finally:
                self._restore(fixture)

    def test_policy_binding_rejects_rehashed_plan_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, contract_path, plan_path = self._build_bundle(
                    root,
                    fixture,
                )
                feasibility = contract["source_candidate"]["feasibility"]
                policy = {
                    "next_long_campaign": {
                        "status": "CONTRACT_FROZEN_PLANONLY_CONTROLS_REQUIRED",
                        "campaign_id": campaign.CAMPAIGN_ID,
                        "hypothesis_id": campaign.HYPOTHESIS_ID,
                        "data_type": campaign.DATA_TYPE,
                        "feasibility_path": str(Path(feasibility["path"]).resolve()),
                        "feasibility_sha256": feasibility["sha256"],
                        "candidate_contract_hash": campaign.EXPECTED_CANDIDATE_HASH,
                        "contract_path": str(contract_path.resolve()),
                        "contract_file_sha256": _sha(contract_path),
                        "contract_hash": contract["contract_hash"],
                        "plan_path": str(plan_path.resolve()),
                        "plan_file_sha256": _sha(plan_path),
                        "plan_hash": plan["plan_hash"],
                        "plan_approval_state": "NOT_APPROVED",
                        "launch_control_status": plan["launch_controls"]["status"],
                        "window_id": campaign.EXPECTED_WINDOW_ID,
                        "target_writer_sec": campaign.EXPECTED_WRITER_SEC,
                        "max_runtime_sec": campaign.EXPECTED_MAX_RUNTIME_SEC,
                        "actual_collection_allowed": False,
                        "requested_action": plan["next_allowed_action"],
                    }
                }
                campaign.validate_policy_binding(
                    policy,
                    contract=contract,
                    plan=plan,
                    contract_path=contract_path,
                    plan_path=plan_path,
                )
                policy["next_long_campaign"]["plan_hash"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "plan_hash"):
                    campaign.validate_policy_binding(
                        policy,
                        contract=contract,
                        plan=plan,
                        contract_path=contract_path,
                        plan_path=plan_path,
                    )
            finally:
                self._restore(fixture)

    def test_tampering_fails_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract = campaign.build_contract(
                    feasibility_path=fixture["feasibility"],
                    expected_feasibility_sha256=_sha(fixture["feasibility"]),
                    expected_candidate_hash=str(fixture["candidate_hash"]),
                    universe_path=fixture["universe"],
                    hypothesis_bank_path=fixture["bank"],
                    continuous_policy_path=fixture["policy"],
                    pit_schedule_path=fixture["schedule"],
                    raw_writer_path=fixture["raw_writer"],
                    durable_collector_path=fixture["durable"],
                    generated_at_utc="2026-07-31T05:00:00+00:00",
                )
                tampered = copy.deepcopy(contract)
                tampered["execution_sampling_contract"]["max_quote_age_ms"]["mexc"] = (
                    60_000
                )
                tampered["contract_hash"] = campaign.canonical_contract_hash(tampered)
                with self.assertRaisesRegex(ValueError, "execution_sampling_contract"):
                    campaign.validate_contract(tampered)
            finally:
                self._restore(fixture)

    def test_wrong_candidate_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                with self.assertRaisesRegex(
                    ValueError, "candidate contract hash mismatch"
                ):
                    campaign.build_contract(
                        feasibility_path=fixture["feasibility"],
                        expected_feasibility_sha256=_sha(fixture["feasibility"]),
                        expected_candidate_hash="0" * 64,
                        universe_path=fixture["universe"],
                        hypothesis_bank_path=fixture["bank"],
                        continuous_policy_path=fixture["policy"],
                        pit_schedule_path=fixture["schedule"],
                        raw_writer_path=fixture["raw_writer"],
                        durable_collector_path=fixture["durable"],
                        generated_at_utc="2026-07-31T05:00:00+00:00",
                    )
            finally:
                self._restore(fixture)

    def test_controlled_plan_binds_controls_but_blocks_operational_readiness(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, _, _ = self._build_controlled_bundle(root, fixture)
                campaign.validate_plan(plan, contract=contract, verify_files=True)
                controls = plan["launch_controls"]
                self.assertEqual(
                    controls["status"],
                    campaign.CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED,
                )
                self.assertEqual(
                    plan["operational_timing"]["status"],
                    "BLOCKED_ZERO_RUNTIME_HEADROOM",
                )
                self.assertFalse(plan["operational_timing"]["launch_ready"])
                self.assertFalse(plan["operational_readiness"]["launch_ready"])
                blocker_codes = {
                    item["code"]
                    for item in plan["operational_readiness"]["blockers"]
                }
                self.assertEqual(
                    blocker_codes,
                    {
                        "ZERO_RUNTIME_HEADROOM",
                        "GLOBAL_ACTIVE_WRITER_CAS_NOT_IMPLEMENTED",
                    },
                )
                self.assertTrue(
                    controls[
                        "commands_are_inert_until_operational_contract_refreeze"
                    ]
                )
                self.assertIn(
                    "-ConfirmedLongCampaign -Json",
                    controls["visible_command_after_approval"],
                )
                self.assertNotIn(
                    "-VisibleChild", controls["visible_command_after_approval"]
                )
                self.assertIn("-PreflightOnly -Json", controls["preflight_command"])

                tampered = copy.deepcopy(plan)
                tampered["launch_controls"]["visible_command_after_approval"] += (
                    " -VisibleChild"
                )
                tampered["plan_hash"] = campaign.canonical_plan_hash(tampered)
                with self.assertRaisesRegex(
                    ValueError, "visible_command_after_approval"
                ):
                    campaign.validate_plan(
                        tampered,
                        contract=contract,
                        verify_files=True,
                    )
            finally:
                self._restore(fixture)


    def test_cas_implemented_removes_cas_blocker(self) -> None:
        """When CAS is implemented the only remaining blocker is ZERO_HEADROOM."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract = campaign.build_contract(
                    feasibility_path=fixture["feasibility"],
                    expected_feasibility_sha256=_sha(fixture["feasibility"]),
                    expected_candidate_hash=str(fixture["candidate_hash"]),
                    universe_path=fixture["universe"],
                    hypothesis_bank_path=fixture["bank"],
                    continuous_policy_path=fixture["policy"],
                    pit_schedule_path=fixture["schedule"],
                    raw_writer_path=fixture["raw_writer"],
                    durable_collector_path=fixture["durable"],
                    generated_at_utc="2026-07-31T05:00:00+00:00",
                )
                contract_path = root / "contract.json"
                plan_path = root / "plan-v3.json"
                tool_paths = campaign._expected_launch_tool_paths()

                def build_plan(contract_file_sha256: str) -> dict:
                    return campaign.build_plan(
                        contract=contract,
                        contract_path=contract_path,
                        contract_file_sha256=contract_file_sha256,
                        feasibility=campaign._read_json(fixture["feasibility"]),
                        output_root=root / "campaign-output",
                        generated_at_utc="2026-07-31T05:00:00+00:00",
                        launcher_path=tool_paths["launcher"],
                        status_tool_path=tool_paths["status"],
                        stop_tool_path=tool_paths["stop"],
                        runner_path=tool_paths["runner"],
                        global_active_writer_cas_implemented=True,
                    )

                persisted_contract, plan = campaign.write_bundle(
                    contract_output_path=contract_path,
                    plan_output_path=plan_path,
                    contract=contract,
                    plan_builder=build_plan,
                )
                controls = plan["launch_controls"]
                # CAS is implemented, so only ZERO_HEADROOM remains
                blocker_codes = {
                    item["code"]
                    for item in plan["operational_readiness"]["blockers"]
                }
                self.assertEqual(blocker_codes, {"ZERO_RUNTIME_HEADROOM"})
                self.assertEqual(
                    plan["operational_readiness"]["global_active_writer_claim"]["status"],
                    "IMPLEMENTED",
                )
                self.assertEqual(
                    controls["status"],
                    campaign.CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED,
                )
            finally:
                self._restore(fixture)

    def test_v3_timing_with_cas_clears_both_blockers(self) -> None:
        """V3 timing (headroom) + CAS implemented → READY_FOR_APPROVAL."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract = campaign.build_contract(
                    feasibility_path=fixture["feasibility"],
                    expected_feasibility_sha256=_sha(fixture["feasibility"]),
                    expected_candidate_hash=str(fixture["candidate_hash"]),
                    universe_path=fixture["universe"],
                    hypothesis_bank_path=fixture["bank"],
                    continuous_policy_path=fixture["policy"],
                    pit_schedule_path=fixture["schedule"],
                    raw_writer_path=fixture["raw_writer"],
                    durable_collector_path=fixture["durable"],
                    generated_at_utc="2026-07-31T05:00:00+00:00",
                )
                contract_path = root / "contract.json"
                plan_path = root / "plan-v3-full.json"
                tool_paths = campaign._expected_launch_tool_paths()

                def build_plan(contract_file_sha256: str) -> dict:
                    return campaign.build_plan(
                        contract=contract,
                        contract_path=contract_path,
                        contract_file_sha256=contract_file_sha256,
                        feasibility=campaign._read_json(fixture["feasibility"]),
                        output_root=root / "campaign-output",
                        generated_at_utc="2026-07-31T05:00:00+00:00",
                        launcher_path=tool_paths["launcher"],
                        status_tool_path=tool_paths["status"],
                        stop_tool_path=tool_paths["stop"],
                        runner_path=tool_paths["runner"],
                        global_active_writer_cas_implemented=True,
                        use_v3_timing=True,
                    )

                persisted_contract, plan = campaign.write_bundle(
                    contract_output_path=contract_path,
                    plan_output_path=plan_path,
                    contract=contract,
                    plan_builder=build_plan,
                )
                # Both blockers resolved
                blocker_codes = {
                    item["code"]
                    for item in plan["operational_readiness"]["blockers"]
                }
                self.assertEqual(blocker_codes, set())
                self.assertTrue(plan["operational_readiness"]["launch_ready"])
                self.assertEqual(
                    plan["operational_readiness"]["global_active_writer_claim"]["status"],
                    "IMPLEMENTED",
                )
                self.assertEqual(
                    plan["launch_controls"]["status"],
                    "READY_FOR_SEPARATE_EXACT_APPROVAL",
                )
                # V3 timing values are in effect
                self.assertEqual(
                    plan["window"]["target_writer_sec"],
                    campaign.V3_EXPECTED_WRITER_SEC,
                )
            finally:
                self._restore(fixture)

    def test_controlled_plan_rejects_rehashed_tool_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, _, _ = self._build_controlled_bundle(root, fixture)
                substitute = root / "substitute.ps1"
                substitute.write_text("Write-Output 'substitute'\n", encoding="utf-8")
                tampered = copy.deepcopy(plan)
                tampered["launch_controls"]["tools"]["launcher"] = {
                    "path": str(substitute.resolve()),
                    "sha256": _sha(substitute),
                }
                tampered["plan_hash"] = campaign.canonical_plan_hash(tampered)
                with self.assertRaisesRegex(ValueError, "launcher.path"):
                    campaign.validate_plan(
                        tampered,
                        contract=contract,
                        verify_files=True,
                    )
            finally:
                self._restore(fixture)

    def test_aef_profile_binds_headroom_cap_global_cas_and_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            old_aef_candidate_hash = campaign.AEF_EXPECTED_CANDIDATE_HASH
            try:
                feasibility = campaign._read_json(fixture["feasibility"])
                candidate = feasibility["frozen_candidate"]
                candidate.update(
                    {
                        "requested_start_local": campaign.AEF_EXPECTED_START_LOCAL,
                        "window_id": campaign.AEF_EXPECTED_WINDOW_ID,
                        "writer_deadline_local": (
                            campaign.AEF_EXPECTED_WRITER_DEADLINE_LOCAL
                        ),
                        "hard_deadline_local": (
                            campaign.AEF_EXPECTED_HARD_DEADLINE_LOCAL
                        ),
                        "target_writer_sec": campaign.AEF_EXPECTED_WRITER_SEC,
                        "phases": [
                            dict(item) for item in campaign.AEF_EXPECTED_PHASES
                        ],
                        "uninterrupted_required": True,
                        "suppressed_pit_run_ids": list(
                            campaign.AEF_SUPPRESSED_PIT_RUN_IDS
                        ),
                    }
                )
                candidate_hash = hashlib.sha256(
                    json.dumps(
                        candidate,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                feasibility["candidate_contract_hash"] = candidate_hash
                campaign.AEF_EXPECTED_CANDIDATE_HASH = candidate_hash

                _write_json(Path(fixture["feasibility"]), feasibility)
                with self.assertRaisesRegex(ValueError, "hard_output_cap_bytes"):
                    campaign.build_contract(
                        feasibility_path=fixture["feasibility"],
                        expected_feasibility_sha256=_sha(fixture["feasibility"]),
                        expected_candidate_hash=candidate_hash,
                        universe_path=fixture["universe"],
                        hypothesis_bank_path=fixture["bank"],
                        continuous_policy_path=fixture["policy"],
                        pit_schedule_path=fixture["schedule"],
                        raw_writer_path=fixture["raw_writer"],
                        durable_collector_path=fixture["durable"],
                        generated_at_utc="2026-08-01T19:00:00+00:00",
                        factory_profile=campaign.AEF_PROFILE,
                    )

                feasibility["resource_estimate"]["hard_output_cap_bytes"] = (
                    campaign.AEF_HARD_OUTPUT_CAP_BYTES
                )
                _write_json(Path(fixture["feasibility"]), feasibility)

                contract = campaign.build_contract(
                    feasibility_path=fixture["feasibility"],
                    expected_feasibility_sha256=_sha(fixture["feasibility"]),
                    expected_candidate_hash=candidate_hash,
                    universe_path=fixture["universe"],
                    hypothesis_bank_path=fixture["bank"],
                    continuous_policy_path=fixture["policy"],
                    pit_schedule_path=fixture["schedule"],
                    raw_writer_path=fixture["raw_writer"],
                    durable_collector_path=fixture["durable"],
                    generated_at_utc="2026-08-01T19:00:00+00:00",
                    factory_profile=campaign.AEF_PROFILE,
                )
                contract_path = root / "aef-contract.json"
                plan_path = root / "aef-plan.json"
                tools = campaign._expected_launch_tool_paths()
                self.assertIn("campaign_quality", tools)
                self.assertIn("causal_materializer", tools)

                def build_plan(contract_file_sha256: str) -> dict:
                    return campaign.build_plan(
                        contract=contract,
                        contract_path=contract_path,
                        contract_file_sha256=contract_file_sha256,
                        feasibility=feasibility,
                        output_root=root / "aef-output",
                        generated_at_utc="2026-08-01T19:00:00+00:00",
                        launcher_path=tools["launcher"],
                        status_tool_path=tools["status"],
                        stop_tool_path=tools["stop"],
                        runner_path=tools["runner"],
                        global_writer_claim_path=tools["global_writer_claim"],
                        campaign_quality_path=tools["campaign_quality"],
                        causal_materializer_path=tools["causal_materializer"],
                    )

                persisted_contract, plan = campaign.write_bundle(
                    contract_output_path=contract_path,
                    plan_output_path=plan_path,
                    contract=contract,
                    plan_builder=build_plan,
                )
                campaign.validate_plan(
                    plan,
                    contract=persisted_contract,
                    verify_files=True,
                )

                self.assertEqual(plan["factory_profile"], campaign.AEF_PROFILE)
                self.assertEqual(
                    plan["launch_controls"]["status"],
                    "READY_FOR_SEPARATE_EXACT_APPROVAL",
                )
                self.assertEqual(
                    plan["resources"]["hard_output_cap_bytes"],
                    campaign.AEF_HARD_OUTPUT_CAP_BYTES,
                )
                self.assertEqual(
                    plan["window"]["target_writer_sec"],
                    campaign.AEF_EXPECTED_WRITER_SEC,
                )
                self.assertEqual(
                    [item["hard_end_local"] for item in plan["phases"]],
                    [item["hard_end_local"] for item in campaign.AEF_EXPECTED_PHASES],
                )
                self.assertIn(
                    "global_writer_claim",
                    plan["launch_controls"]["tools"],
                )
                self.assertIn(
                    "campaign_quality",
                    plan["launch_controls"]["tools"],
                )
                self.assertIn(
                    "causal_materializer",
                    plan["launch_controls"]["tools"],
                )
                self.assertFalse(
                    plan["post_collection"]["automatic_same_hash_progression"]
                )
                self.assertTrue(
                    plan["post_collection"][
                        "automatic_same_hash_progression_through_materialization"
                    ]
                )
                self.assertFalse(
                    plan["post_collection"][
                        "signal_and_evaluator_contract_frozen"
                    ]
                )
                self.assertEqual(
                    plan["post_collection"]["pipeline"][:3],
                    [
                        "campaign_data_quality",
                        "causal_regime_and_execution_snapshot_materialization",
                        "exact_signal_and_evaluator_contract_review",
                    ],
                )
                self.assertTrue(
                    plan["post_collection"]["stop_on_first_failed_gate"]
                )
                self.assertFalse(
                    plan["post_collection"]["automatic_live_or_private_api"]
                )

                tampered = copy.deepcopy(plan)
                del tampered["launch_controls"]["tools"]["global_writer_claim"]
                tampered["plan_hash"] = campaign.canonical_plan_hash(tampered)
                with self.assertRaises(ValueError):
                    campaign.validate_plan(
                        tampered,
                        contract=persisted_contract,
                        verify_files=True,
                    )

                tampered_quality = copy.deepcopy(plan)
                del tampered_quality["launch_controls"]["tools"]["campaign_quality"]
                tampered_quality["plan_hash"] = campaign.canonical_plan_hash(
                    tampered_quality
                )
                with self.assertRaises(ValueError):
                    campaign.validate_plan(
                        tampered_quality,
                        contract=persisted_contract,
                        verify_files=True,
                    )

                tampered_materializer = copy.deepcopy(plan)
                del tampered_materializer["launch_controls"]["tools"][
                    "causal_materializer"
                ]
                tampered_materializer["plan_hash"] = campaign.canonical_plan_hash(
                    tampered_materializer
                )
                with self.assertRaises(ValueError):
                    campaign.validate_plan(
                        tampered_materializer,
                        contract=persisted_contract,
                        verify_files=True,
                    )
            finally:
                campaign.AEF_EXPECTED_CANDIDATE_HASH = old_aef_candidate_hash
                self._restore(fixture)

    def test_runner_preflight_is_read_only_before_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                _, plan, _, plan_path, runtime_policy = self._build_controlled_bundle(
                    root, fixture
                )
                output_root = Path(plan["outputs"]["campaign_root"])
                self.assertFalse(output_root.exists())
                with (
                    mock.patch.object(
                        runner,
                        "gate_status",
                        return_value={
                            "status": "READY_FOR_POSTPROCESS",
                            "run_id": "fixture",
                            "live_process_ids": [],
                        },
                    ),
                    mock.patch.object(
                        runner.shutil,
                        "disk_usage",
                        return_value=mock.Mock(free=1_000_000_000_000),
                    ),
                ):
                    result = runner.preflight(
                        plan_path=plan_path,
                        expected_plan_hash=plan["plan_hash"],
                        policy_path=runtime_policy,
                        now=datetime.fromisoformat("2026-07-31T08:00:00+03:00"),
                    )
                self.assertEqual(result["status"], "BLOCKED")
                self.assertFalse(result["structurally_valid"])
                self.assertFalse(result["can_launch_now"])
                self.assertTrue(result["no_run_or_output_writes"])
                self.assertIn(
                    "long_campaign_contract_not_approval_ready:"
                    f"{campaign.CONTROLS_IMPLEMENTED_OPERATIONAL_BLOCKED}",
                    result["reasons"],
                )
                self.assertFalse(output_root.exists())
            finally:
                self._restore(fixture)

    def test_campaign_output_bytes_counts_entire_campaign_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, plan_path, runtime_policy = (
                    self._build_controlled_bundle(root, fixture)
                )
                runtime = runner.CampaignRuntime(
                    contract=contract,
                    plan=plan,
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    policy_path=runtime_policy,
                    reservation_token="a" * 32,
                )
                first = runtime.paths["root"] / "phase_01" / "seg_001" / "a.jsonl"
                second = runtime.paths["root"] / "phase_02" / "seg_001" / "b.jsonl"
                first.parent.mkdir(parents=True, exist_ok=True)
                second.parent.mkdir(parents=True, exist_ok=True)
                first.write_bytes(b"a" * 17)
                second.write_bytes(b"b" * 29)

                self.assertEqual(runtime.campaign_output_bytes(), 46)
            finally:
                self._restore(fixture)

    def test_phase_start_waits_for_exact_pit_postrun_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, plan_path, runtime_policy = (
                    self._build_controlled_bundle(root, fixture)
                )
                runtime = runner.CampaignRuntime(
                    contract=contract,
                    plan=plan,
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    policy_path=runtime_policy,
                    reservation_token="a" * 32,
                )
                pit_run_id = "pit_universe_v2_forward_20260803_n06"

                def guard(disposition: dict) -> dict:
                    return {
                        "status": "ACTIVE",
                        "stop_new_actions": False,
                        "usage": {
                            "status": "AVAILABLE",
                            "remaining_percent": 64.0,
                        },
                        "long_campaign_candidate": {
                            "status": "READY_FOR_APPROVAL",
                            "plan_hash": plan["plan_hash"],
                        },
                        "pit_postrun_disposition": disposition,
                    }

                cases = (
                    (
                        "pit writer still running",
                        {
                            "status": "RUNNING",
                            "run_id": pit_run_id,
                            "live_process_ids": [],
                        },
                        guard({"status": "NOT_APPLICABLE", "run_id": None}),
                        f"active_gate_running:{pit_run_id}",
                    ),
                    (
                        "pit stopped incomplete",
                        {
                            "status": "STOPPED_INCOMPLETE",
                            "run_id": pit_run_id,
                            "live_process_ids": [],
                        },
                        guard({"status": "NOT_APPLICABLE", "run_id": None}),
                        f"active_gate_stopped_incomplete:{pit_run_id}",
                    ),
                    (
                        "pit writer done but postrun missing",
                        {
                            "status": "READY_FOR_POSTPROCESS",
                            "run_id": pit_run_id,
                            "live_process_ids": [],
                        },
                        guard({"status": "MISSING", "run_id": pit_run_id}),
                        f"pit_postrun_not_complete:{pit_run_id}:MISSING",
                    ),
                    (
                        "pit postrun belongs to another run",
                        {
                            "status": "READY_FOR_POSTPROCESS",
                            "run_id": pit_run_id,
                            "live_process_ids": [],
                        },
                        guard(
                            {
                                "status": "COMPLETE",
                                "run_id": "pit_universe_v2_forward_other",
                            }
                        ),
                        (
                            "pit_postrun_not_complete:"
                            "pit_universe_v2_forward_other:COMPLETE"
                        ),
                    ),
                )
                for label, gate, autopilot, expected in cases:
                    with self.subTest(label=label):
                        with (
                            mock.patch.object(
                                runner,
                                "gate_status",
                                return_value=gate,
                            ),
                            mock.patch.object(
                                runner,
                                "autopilot_status",
                                return_value=autopilot,
                            ),
                        ):
                            self.assertIn(expected, runtime.phase_start_blockers())

                with (
                    mock.patch.object(
                        runner,
                        "gate_status",
                        return_value={
                            "status": "READY_FOR_POSTPROCESS",
                            "run_id": pit_run_id,
                            "live_process_ids": [],
                        },
                    ),
                    mock.patch.object(
                        runner,
                        "autopilot_status",
                        return_value=guard(
                            {"status": "COMPLETE", "run_id": pit_run_id}
                        ),
                    ),
                ):
                    self.assertEqual(runtime.phase_start_blockers(), [])
            finally:
                self._restore(fixture)

    def test_runner_preflight_blocks_when_campaign_cap_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, plan_path, runtime_policy = (
                    self._build_controlled_bundle(root, fixture)
                )
                plan = copy.deepcopy(plan)
                output_cap = 100
                plan["resources"]["estimated_disk_bytes"] = 50
                plan["resources"]["hard_output_cap_bytes"] = output_cap
                with (
                    mock.patch.object(
                        runner,
                        "load_validated_bundle",
                        return_value=(contract, plan, {}),
                    ),
                    mock.patch.object(
                        runner,
                        "gate_status",
                        return_value={
                            "status": "READY_FOR_POSTPROCESS",
                            "run_id": "fixture",
                            "live_process_ids": [],
                        },
                    ),
                    mock.patch.object(
                        runner.shutil,
                        "disk_usage",
                        return_value=mock.Mock(free=1_000_000_000_000),
                    ),
                    mock.patch.object(
                        runner,
                        "directory_size_bytes",
                        return_value=output_cap,
                    ),
                ):
                    result = runner.preflight(
                        plan_path=plan_path,
                        expected_plan_hash=plan["plan_hash"],
                        policy_path=runtime_policy,
                        now=datetime.fromisoformat(plan["window"]["start_local"]),
                        require_due=True,
                    )

                self.assertFalse(result["structurally_valid"])
                self.assertFalse(result["can_launch_now"])
                self.assertEqual(
                    result["existing_campaign_output_bytes"],
                    output_cap,
                )
                self.assertIn(
                    "campaign_output_cap_already_reached",
                    result["reasons"],
                )
            finally:
                self._restore(fixture)

    def test_runtime_stops_writer_when_campaign_cap_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, plan_path, runtime_policy = (
                    self._build_controlled_bundle(root, fixture)
                )
                plan = copy.deepcopy(plan)
                output_cap = 100
                plan["resources"]["hard_output_cap_bytes"] = output_cap
                runtime = runner.CampaignRuntime(
                    contract=contract,
                    plan=plan,
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    policy_path=runtime_policy,
                    reservation_token="a" * 32,
                )
                runtime.paths["control"].mkdir(parents=True, exist_ok=True)
                phase = copy.deepcopy(plan["phases"][0])
                observed_at = datetime.fromisoformat(phase["start_local"])
                process = mock.Mock(pid=42_424, returncode=None)
                process.poll.side_effect = lambda: process.returncode
                tracked = mock.Mock()
                tracked.cpu_percent.return_value = 0.0

                def stop_writer(writer: mock.Mock, *, reason: str) -> None:
                    self.assertEqual(reason, "campaign_output_cap_reached")
                    writer.returncode = 1

                with (
                    mock.patch.object(
                        runtime,
                        "campaign_output_bytes",
                        side_effect=[output_cap - 1, output_cap],
                    ),
                    mock.patch.object(runtime, "acquire_global_writer_claim"),
                    mock.patch.object(runtime, "claim_gate"),
                    mock.patch.object(runtime, "attach_global_writer"),
                    mock.patch.object(runtime, "attach_writer_to_gate"),
                    mock.patch.object(runtime, "update_state"),
                    mock.patch.object(runtime, "update_owned_gate") as update_gate,
                    mock.patch.object(runtime, "release_global_writer_claim") as release_claim,
                    mock.patch.object(runtime, "wait_for_gate"),
                    mock.patch.object(runner, "utc_now", return_value=observed_at),
                    mock.patch.object(runner.subprocess, "Popen", return_value=process),
                    mock.patch.object(runner.psutil, "Process", return_value=tracked),
                    mock.patch.object(runner, "terminate_writer", side_effect=stop_writer) as stop,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "phase_stopped_incomplete:.*:campaign_output_cap_reached",
                    ):
                        runtime.monitor_phase(
                            phase=phase,
                            symbol_plan={"symbols_arg": "mexc:S1USDT;gateio:S1_USDT"},
                        )

                stop.assert_called_once_with(
                    process,
                    reason="campaign_output_cap_reached",
                )
                self.assertEqual(runtime.phase_results[0]["status"], "STOPPED_INCOMPLETE")
                self.assertEqual(
                    runtime.phase_results[0]["stop_reason"],
                    "campaign_output_cap_reached",
                )
                update_gate.assert_called_once()
                self.assertEqual(update_gate.call_args.kwargs["status"], "STOPPED_INCOMPLETE")
                self.assertEqual(
                    update_gate.call_args.kwargs["reason"],
                    "campaign_output_cap_reached",
                )
                release_claim.assert_called_once_with("STOPPED_INCOMPLETE")
            finally:
                self._restore(fixture)

    def test_runner_preflight_blocks_any_existing_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                _, plan, _, plan_path, runtime_policy = self._build_controlled_bundle(
                    root, fixture
                )
                paths = runner.control_paths(plan)
                _write_json(
                    paths["reservation"],
                    {
                        "schema": runner.RESERVATION_SCHEMA,
                        "plan_hash": plan["plan_hash"],
                        "terminal_pid": None,
                    },
                )
                with (
                    mock.patch.object(
                        runner,
                        "gate_status",
                        return_value={
                            "status": "READY_FOR_POSTPROCESS",
                            "run_id": "fixture",
                            "live_process_ids": [],
                        },
                    ),
                    mock.patch.object(
                        runner.shutil,
                        "disk_usage",
                        return_value=mock.Mock(free=1_000_000_000_000),
                    ),
                ):
                    result = runner.preflight(
                        plan_path=plan_path,
                        expected_plan_hash=plan["plan_hash"],
                        policy_path=runtime_policy,
                        now=datetime.fromisoformat("2026-07-31T19:00:00+03:00"),
                        require_due=True,
                    )
                self.assertFalse(result["structurally_valid"])
                self.assertFalse(result["can_launch_now"])
                self.assertIn("launch_reservation_exists", result["reasons"])
            finally:
                self._restore(fixture)

    def test_symbol_plan_requires_canonical_bound_symbols_arg(self) -> None:
        mexc = [f"S{index}USDT" for index in range(10)]
        gateio = [f"S{index}_USDT" for index in range(10)]
        payload = {
            "symbols_by_exchange": {"mexc": mexc, "gateio": gateio},
            "symbols_arg": (f"gateio:{','.join(gateio)};mexc:{','.join(mexc)}"),
        }
        result = runner.validate_symbol_plan(payload)
        self.assertEqual(result["dual_venue_coverage"], 1.0)

        mismatched = copy.deepcopy(payload)
        mismatched["symbols_arg"] += ",EVILUSDT"
        with self.assertRaisesRegex(ValueError, "symbols_arg"):
            runner.validate_symbol_plan(mismatched)

        duplicated = copy.deepcopy(payload)
        duplicated["symbols_by_exchange"]["mexc"][-1] = mexc[0]
        duplicated["symbols_arg"] = (
            f"gateio:{','.join(gateio)};"
            f"mexc:{','.join(duplicated['symbols_by_exchange']['mexc'])}"
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            runner.validate_symbol_plan(duplicated)

    def test_raw_schema_and_venue_presence_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = []
            for exchange in ("mexc", "gateio"):
                path = root / f"ws_{exchange}.jsonl"
                rows = [
                    {
                        "recv_ts": 1_700_000_000.0 + index,
                        "exchange": exchange,
                        "event_type": "message",
                        "channel": "book",
                        "symbol": None,
                        "payload": {"encoding": "json", "data": {"n": index}},
                    }
                    for index in range(10)
                ]
                path.write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )
                paths.append(path)

            schema = runner.schema_probe(paths, max_lines=20)
            presence = runner.venue_presence_probe(paths)
            self.assertEqual(schema["checked_lines"], 20)
            self.assertEqual(
                presence["sampled_rows_by_venue"],
                {"mexc": 10, "gateio": 10},
            )

            malformed = root / "malformed.jsonl"
            malformed.write_text(
                json.dumps(
                    {
                        "recv_ts": 1.0,
                        "exchange": "mexc",
                        "event_type": "message",
                        "channel": None,
                        "symbol": None,
                        "payload": {"encoding": "base64", "data": "AA=="},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "base64 payload fields"):
                runner.schema_probe([malformed], max_lines=1)

    def test_stop_without_active_campaign_is_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                _, plan, _, plan_path, _ = self._build_controlled_bundle(root, fixture)
                output_root = Path(plan["outputs"]["campaign_root"])
                result = runner.request_stop(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    reason="fixture",
                )
                self.assertEqual(result["status"], "NO_ACTIVE_CAMPAIGN")
                self.assertFalse(result["stop_request_written"])
                self.assertFalse(output_root.exists())
            finally:
                self._restore(fixture)

    def test_owned_gate_publishes_and_restores_authoritative_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                (
                    contract,
                    plan,
                    _,
                    plan_path,
                    runtime_policy,
                ) = self._build_controlled_bundle(root, fixture)
                runtime = runner.CampaignRuntime(
                    contract=contract,
                    plan=plan,
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    policy_path=runtime_policy,
                    reservation_token="a" * 32,
                )
                runtime.previous_gate_path = root / "agent-log" / "active-run-gate.json"
                runtime.current_pointer_path = root / "agent-log" / "current-run.json"
                prior_gate = {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "prior",
                    "status": "READY_FOR_POSTPROCESS",
                    "approved_night_schedule": {"plan_hash": "frozen"},
                }
                prior_pointer = {
                    "schema": "active_run_pointer_v1",
                    "project": "trading_mvp",
                    "run_id": "prior",
                    "status": "READY_FOR_POSTPROCESS",
                }
                _write_json(runtime.previous_gate_path, prior_gate)
                _write_json(runtime.current_pointer_path, prior_pointer)
                prior_gate_bytes = runtime.previous_gate_path.read_bytes()
                prior_pointer_bytes = runtime.current_pointer_path.read_bytes()

                phase = plan["phases"][0]
                runtime.claim_gate(phase, writer_pid=12345)
                gate = runner.read_json(runtime.previous_gate_path)
                pointer = runner.read_json(runtime.current_pointer_path)
                self.assertEqual(gate["status"], "RUNNING")
                self.assertEqual(pointer["status"], "RUNNING")
                self.assertEqual(pointer["run_id"], phase["run_id"])
                self.assertEqual(
                    gate["approved_night_schedule"],
                    prior_gate["approved_night_schedule"],
                )
                self.assertTrue(Path(pointer["launch_record_path"]).is_file())

                runtime.update_owned_gate(
                    phase=phase,
                    status="READY_FOR_POSTPROCESS",
                    manifest=None,
                    reason=None,
                )
                pointer = runner.read_json(runtime.current_pointer_path)
                self.assertEqual(pointer["status"], "READY_FOR_POSTPROCESS")

                runtime.release_gate_for_blackout(phase)
                self.assertEqual(
                    runtime.previous_gate_path.read_bytes(),
                    prior_gate_bytes,
                )
                self.assertEqual(
                    runtime.current_pointer_path.read_bytes(),
                    prior_pointer_bytes,
                )
            finally:
                self._restore(fixture)

    def test_visible_launcher_static_invariants(self) -> None:
        tools = campaign._expected_launch_tool_paths()
        launcher = tools["launcher"].read_text(encoding="utf-8")
        self.assertIn("-WindowStyle Normal", launcher)
        self.assertIn('"-NoExit"', launcher)
        self.assertNotRegex(launcher, r"(?m)^\s*exit \$exitCode\b")
        self.assertIn("[System.IO.FileMode]::CreateNew", launcher)
        self.assertIn("$PreflightOnly", launcher)
        self.assertIn("-VisibleChild", launcher)
        self.assertIn("-ReservationPath", launcher)
        self.assertNotIn("-ReservationToken", launcher)
        self.assertIn("TRADING_MVP_DENSE_WS_RESERVATION_TOKEN", launcher)
        self.assertIn("owner_adoption_verified", launcher)
        self.assertIn('run_id = [string]$plan.campaign_id', launcher)
        self.assertIn("$exitCode -notin @(0, 1)", launcher)
        self.assertNotIn("command_line_verified = $commandLine", launcher)
        self.assertTrue(tools["status"].is_file())
        self.assertTrue(tools["stop"].is_file())
        self.assertTrue(tools["runner"].is_file())

    def test_runtime_command_redacts_reservation_token(self) -> None:
        with mock.patch.object(
            runner.sys,
            "argv",
            ["runner.py", "run", "--reservation-token", "secret-token"],
        ):
            command = runner.redacted_process_command()
        self.assertIn("<redacted>", command)
        self.assertNotIn("secret-token", command)

    def test_reservation_adoption_is_terminal_bound_and_owner_redacts_token(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                (
                    contract,
                    plan,
                    _,
                    plan_path,
                    runtime_policy,
                ) = self._build_controlled_bundle(root, fixture)
                runtime = runner.CampaignRuntime(
                    contract=contract,
                    plan=plan,
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    policy_path=runtime_policy,
                    reservation_token="a" * 32,
                )
                paths = runner.control_paths(plan)
                _write_json(
                    paths["reservation"],
                    {
                        "schema": runner.RESERVATION_SCHEMA,
                        "campaign_id": campaign.CAMPAIGN_ID,
                        "reservation_token": "a" * 32,
                        "top_level_pid": 111,
                        "expected_terminal_pid": 222,
                        "terminal_pid": None,
                        "plan_path": str(plan_path.resolve()),
                        "plan_hash": plan["plan_hash"],
                        "policy_path": str(runtime_policy.resolve()),
                        "explicit_confirmation": True,
                    },
                )
                with (
                    mock.patch.object(runner, "process_alive", return_value=True),
                    mock.patch.object(runner.os, "getppid", return_value=222),
                    mock.patch.object(runner.os, "getpid", return_value=333),
                ):
                    runtime.adopt_reservation()
                owner = runner.read_json(paths["owner"])
                reservation = runner.read_json(paths["reservation"])
                self.assertEqual(owner["terminal_pid"], 222)
                self.assertEqual(owner["orchestrator_pid"], 333)
                self.assertNotIn("reservation_token", owner)
                self.assertEqual(
                    owner["reservation_token_sha256"],
                    runner.reservation_token_sha256("a" * 32),
                )
                self.assertEqual(reservation["terminal_pid"], 222)
                self.assertEqual(reservation["orchestrator_pid"], 333)
                redacted = runner.redact_control_record(reservation)
                self.assertNotIn("reservation_token", redacted)
                self.assertTrue(redacted["reservation_token_present"])
            finally:
                self._restore(fixture)

    def test_reservation_adoption_rejects_unbound_terminal_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                contract, plan, _, plan_path, runtime_policy = (
                    self._build_controlled_bundle(root, fixture)
                )
                runtime = runner.CampaignRuntime(
                    contract=contract,
                    plan=plan,
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    policy_path=runtime_policy,
                    reservation_token="a" * 32,
                )
                paths = runner.control_paths(plan)
                _write_json(
                    paths["reservation"],
                    {
                        "schema": runner.RESERVATION_SCHEMA,
                        "campaign_id": campaign.CAMPAIGN_ID,
                        "reservation_token": "a" * 32,
                        "top_level_pid": 111,
                        "expected_terminal_pid": 222,
                        "plan_path": str(plan_path.resolve()),
                        "plan_hash": plan["plan_hash"],
                        "policy_path": str(runtime_policy.resolve()),
                        "explicit_confirmation": True,
                    },
                )
                with (
                    mock.patch.object(runner, "process_alive", return_value=True),
                    mock.patch.object(runner.os, "getppid", return_value=999),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "does not match the parent-bound reservation",
                    ):
                        runtime.adopt_reservation()
                self.assertFalse(paths["owner"].exists())
            finally:
                self._restore(fixture)

    def test_liveness_refreeze_provenance_is_hash_bound_and_non_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixture(root)
            try:
                proposal_path = root / "proposal.json"
                proposal = {
                    "schema": "collector_liveness_refreeze_v2",
                    "frozen_scope": "runtime_quality_contract_only",
                }
                proposal_hash = hashlib.sha256(
                    json.dumps(
                        proposal,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                proposal["proposal_hash"] = proposal_hash
                _write_json(proposal_path, proposal)
                approval_path = root / "approval.json"
                _write_json(
                    approval_path,
                    {
                        "proposal": {"proposal_hash": proposal_hash},
                        "authorized_scope": {
                            "runtime_quality_contract_files_listed_in_proposal_only": True
                        },
                        "campaign_launch_authorized": False,
                    },
                )
                runtime_manifest_path = root / "runtime-manifest.json"
                _write_json(
                    runtime_manifest_path,
                    {
                        "schema": "collector_liveness_runtime_manifest_v2",
                        "proposal_hash": proposal_hash,
                        "collector_launch_authorized": False,
                    },
                )
                contract = campaign.build_contract(
                    feasibility_path=fixture["feasibility"],
                    expected_feasibility_sha256=_sha(fixture["feasibility"]),
                    expected_candidate_hash=str(fixture["candidate_hash"]),
                    universe_path=fixture["universe"],
                    hypothesis_bank_path=fixture["bank"],
                    continuous_policy_path=fixture["policy"],
                    pit_schedule_path=fixture["schedule"],
                    raw_writer_path=fixture["raw_writer"],
                    durable_collector_path=fixture["durable"],
                    generated_at_utc="2026-08-02T20:00:00+00:00",
                    runtime_dependency_manifest_path=runtime_manifest_path,
                    refreeze_proposal_path=proposal_path,
                    expected_refreeze_proposal_hash=proposal_hash,
                    refreeze_approval_receipt_path=approval_path,
                )
                contract_path = root / "contract-refreeze.json"
                plan_path = root / "plan-refreeze.json"

                def build_plan(contract_file_sha256: str) -> dict:
                    return campaign.build_plan(
                        contract=contract,
                        contract_path=contract_path,
                        contract_file_sha256=contract_file_sha256,
                        feasibility=campaign._read_json(fixture["feasibility"]),
                        output_root=root / "output-refreeze",
                        generated_at_utc="2026-08-02T20:00:00+00:00",
                    )

                persisted_contract, plan = campaign.write_bundle(
                    contract_output_path=contract_path,
                    plan_output_path=plan_path,
                    contract=contract,
                    plan_builder=build_plan,
                )
            finally:
                self._restore(fixture)

        refreeze = persisted_contract["collector_liveness_refreeze"]
        self.assertEqual(refreeze["proposal_hash"], proposal_hash)
        self.assertFalse(refreeze["collector_launch_authorized"])
        self.assertFalse(refreeze["stopped_incomplete_retry_authorized"])
        self.assertEqual(
            plan["runtime_dependencies"]["collector_liveness_refreeze"],
            refreeze,
        )
        self.assertEqual(plan["approval_state"], "NOT_APPROVED")
        self.assertFalse(plan["actual_collection_allowed"])


if __name__ == "__main__":
    unittest.main()
