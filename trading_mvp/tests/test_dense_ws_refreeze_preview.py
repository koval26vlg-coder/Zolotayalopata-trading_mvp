from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_refreeze_preview as preview  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DenseWsRefreezePreviewTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> dict[str, Path | str]:
        repo = root / "repo"
        source = repo / "trading_mvp" / "src" / "dense_ws_campaign_contract.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(
            (
                'AEF_CAMPAIGN_ID = "dense_ws_microstructure_regime_filter_v1_20260804_aef_24h"\r\n'
                'AEF_EXPECTED_CANDIDATE_HASH = "' + "a" * 64 + '"\r\n'
                'AEF_EXPECTED_WINDOW_ID = "OLD_WINDOW"\r\n'
                "AEF_EXPECTED_WRITER_SEC = 86_400\r\n"
                "AEF_EXPECTED_MAX_RUNTIME_SEC = 88_200\r\n"
                'AEF_EXPECTED_START_LOCAL = "2026-08-04T01:40:00+03:00"\r\n'
                'AEF_EXPECTED_WRITER_DEADLINE_LOCAL = "2026-08-05T01:40:00+03:00"\r\n'
                'AEF_EXPECTED_HARD_DEADLINE_LOCAL = "2026-08-05T02:10:00+03:00"\r\n'
                "AEF_SUPPRESSED_PIT_RUN_IDS = ()\r\n"
                "AEF_EXPECTED_PHASES = (\r\n"
                "    {\r\n"
                '        "phase_id": "phase_01",\r\n'
                '        "start_local": "2026-08-04T01:40:00+03:00",\r\n'
                '        "end_local": "2026-08-05T01:40:00+03:00",\r\n'
                '        "hard_end_local": "2026-08-05T02:10:00+03:00",\r\n'
                '        "writer_duration_sec": 86_400,\r\n'
                '        "complete_durable_segments": 24,\r\n'
                "    },\r\n"
                ")\r\n"
            ).encode("utf-8")
        )

        source_policy = repo / "docs" / "plans" / "continuous.json"
        _write_json(source_policy, {"schema": preview.POLICY_SCHEMA, "policy_id": "source"})

        reservation_path = root / "reservation.json"
        reservation = {
            "schema": preview.RESERVATION_SCHEMA,
            "mode": "PlanOnly",
            "status": preview.CONTINGENT_STATUS,
            "source": {
                "pit_schedule_approved": False,
                "extension_binding": {
                    "fresh_horizon_required": True,
                    "approval_request_not_before_local": "2026-08-10T19:00:00+03:00",
                },
            },
            "reservation": {
                "campaign_id": "dense_ws_microstructure_regime_filter_v1_20260815_aef_24h",
                "window_id": "WEEKEND_2026-08-14_2026-08-17",
                "start_local": "2026-08-15T01:40:00+03:00",
                "writer_deadline_local": "2026-08-16T01:40:00+03:00",
                "hard_deadline_local": "2026-08-16T02:10:00+03:00",
                "writer_duration_sec": 86_400,
                "max_runtime_sec": 88_200,
                "hard_output_cap_bytes": 25_000_000_000,
                "uninterrupted_required": True,
                "suppressed_pit_run_ids": [],
                "preceding_pit": {
                    "run_id": "pit_universe_v2_forward_20260815_n04",
                    "end_local": "2026-08-15T01:20:00+03:00",
                },
                "deferred_pit": {
                    "run_id": "pit_universe_v2_forward_20260816_n05",
                    "original_start_local": "2026-08-16T01:00:00+03:00",
                    "original_end_local": "2026-08-16T01:20:00+03:00",
                    "new_start_local": "2026-08-16T02:15:00+03:00",
                    "new_end_local": "2026-08-16T02:35:00+03:00",
                    "hard_deadline_local": "2026-08-16T07:00:00+03:00",
                },
            },
            "frozen_invariants": {
                "hypothesis_changed": False,
                "venue_changed": False,
                "universe_changed": False,
                "signal_changed": False,
                "cost_changed": False,
                "risk_changed": False,
                "duration_changed": False,
                "output_cap_changed": False,
                "grid_or_retune": False,
            },
            "authorization_boundary": {
                "this_is_not_contract_refreeze_approval": True,
                "this_is_not_launch_approval": True,
                "collector_launch_allowed": False,
                "network_access": False,
                "market_data_read": False,
                "returns_or_pnl": False,
                "oos": False,
                "paper_or_live": False,
                "private_api": False,
                "real_capital": False,
                "leverage_or_margin": False,
                "stopped_incomplete_retry_authorized": False,
            },
        }
        reservation["reservation_hash"] = preview._canonical_hash(
            reservation, excluded_key="reservation_hash"
        )
        _write_json(reservation_path, reservation)

        amendment_path = root / "amendment.json"
        amendment = {
            "mode": "PlanOnly",
            "plan_hash": "b" * 64,
            "explicit_approval_required": True,
            "time_only_amendment": {
                "run_id": "pit_universe_v2_forward_20260816_n05",
                "original_start_local": "2026-08-16T01:00:00+03:00",
                "original_end_local": "2026-08-16T01:20:00+03:00",
                "new_start_local": "2026-08-16T02:15:00+03:00",
                "new_end_local": "2026-08-16T02:35:00+03:00",
                "hard_deadline_local": "2026-08-16T07:00:00+03:00",
                "trade_contract_changed": False,
            },
        }
        _write_json(amendment_path, amendment)

        candidate_policy_path = root / "candidate-policy.json"
        candidate_policy = {
            "schema": preview.POLICY_SCHEMA,
            "pit_no_skip_time_only_amendment": {
                "source_policy_path": str(source_policy.resolve()),
                "source_policy_sha256": _sha(source_policy),
                "reservation_path": str(reservation_path.resolve()),
                "reservation_file_sha256": _sha(reservation_path),
                "reservation_hash": reservation["reservation_hash"],
                "amended_pit_schedule_path": str(amendment_path.resolve()),
                "amended_pit_schedule_file_sha256": _sha(amendment_path),
                "amended_pit_schedule_plan_hash": "b" * 64,
                "trade_contract_changed": False,
                "collector_launch_allowed": False,
                "contingent_on_fresh_pit_extension_approval": True,
            },
            "accelerated_evidence_factory": {
                "dense_writer_target_sec": 86_400,
                "dense_campaign_max_elapsed_sec": 88_200,
                "continuous_evidence_exception": {
                    "campaign_id": reservation["reservation"]["campaign_id"],
                    "window_id": reservation["reservation"]["window_id"],
                    "start_local": reservation["reservation"]["start_local"],
                    "writer_deadline_local": reservation["reservation"]["writer_deadline_local"],
                    "hard_deadline_local": reservation["reservation"]["hard_deadline_local"],
                    "deferred_pit_run_id": reservation["reservation"]["deferred_pit"]["run_id"],
                    "suppressed_pit_run_ids": [],
                },
                "market_data_sequence": [
                    {"run_id": reservation["reservation"]["preceding_pit"]["run_id"]},
                    {"run_id": reservation["reservation"]["campaign_id"] + "_phase_01"},
                    {"run_id": reservation["reservation"]["deferred_pit"]["run_id"]},
                ],
            },
        }
        _write_json(candidate_policy_path, candidate_policy)

        feasibility_path = root / "feasibility.json"
        phase = {
            "phase_id": "phase_01",
            "start_local": reservation["reservation"]["start_local"],
            "end_local": reservation["reservation"]["writer_deadline_local"],
            "hard_end_local": reservation["reservation"]["hard_deadline_local"],
            "writer_duration_sec": 86_400,
            "complete_durable_segments": 24,
        }
        feasibility = {
            "schema": preview.FEASIBILITY_SCHEMA,
            "mode": "PlanOnly",
            "would_start": False,
            "network_access": False,
            "returns_read": False,
            "pnl_computed": False,
            "oos_read": False,
            "grid_or_retune": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "actual_collection_allowed": False,
            "hypothesis": {"id": "dense_ws_microstructure_regime_filter_v1"},
            "candidate_universe": {"sha256": "c" * 64, "rows": 1388},
            "window_feasibility": {
                "window_id": reservation["reservation"]["window_id"],
                "campaign_start_local": reservation["reservation"]["start_local"],
                "writer_deadline_local": reservation["reservation"]["writer_deadline_local"],
                "hard_deadline_local": reservation["reservation"]["hard_deadline_local"],
                "planned_writer_sec": 86_400,
                "uninterrupted_required": True,
                "suppressed_pit_run_ids": [],
            },
            "resource_estimate": {
                "estimated_disk_bytes": 12_000_000_000,
                "hard_output_cap_bytes": 25_000_000_000,
            },
            "frozen_candidate": {
                "hypothesis_id": "dense_ws_microstructure_regime_filter_v1",
                "requested_start_local": reservation["reservation"]["start_local"],
                "window_id": reservation["reservation"]["window_id"],
                "hard_deadline_local": reservation["reservation"]["hard_deadline_local"],
                "writer_deadline_local": reservation["reservation"]["writer_deadline_local"],
                "target_writer_sec": 86_400,
                "continuous_policy_sha256": _sha(candidate_policy_path),
                "pit_schedule_sha256": _sha(amendment_path),
                "universe_sha256": "c" * 64,
                "universe_rows": 1388,
                "suppressed_pit_run_ids": [],
                "phases": [phase],
            },
            "verdict": preview.FEASIBILITY_VERDICT,
        }
        feasibility["candidate_contract_hash"] = preview._canonical_value_hash(
            feasibility["frozen_candidate"]
        )
        _write_json(feasibility_path, feasibility)
        return {
            "repo": repo,
            "source": source,
            "source_policy": source_policy,
            "reservation": reservation_path,
            "reservation_hash": reservation["reservation_hash"],
            "candidate_policy": candidate_policy_path,
            "amendment": amendment_path,
            "feasibility": feasibility_path,
            "candidate_contract_hash": feasibility["candidate_contract_hash"],
        }

    def _build(self, root: Path, fixture: dict[str, Path | str]) -> dict:
        planned = {
            key: root / "planned" / f"{key}.json" for key in preview.PLANNED_OUTPUT_KEYS
        }
        with (
            mock.patch.object(preview.pit_schedule, "validate_night_schedule_plan"),
            mock.patch.object(
                preview,
                "_verify_patch_roundtrip",
                side_effect=lambda **kwargs: kwargs["expected_postimage_sha256"],
            ),
        ):
            return preview.build_refreeze_preview(
                repo_root=fixture["repo"],
                source_path=fixture["source"],
                expected_source_sha256=_sha(Path(fixture["source"])),
                source_policy_path=fixture["source_policy"],
                expected_source_policy_sha256=_sha(Path(fixture["source_policy"])),
                reservation_path=fixture["reservation"],
                expected_reservation_sha256=_sha(Path(fixture["reservation"])),
                expected_reservation_hash=str(fixture["reservation_hash"]),
                candidate_policy_path=fixture["candidate_policy"],
                expected_candidate_policy_sha256=_sha(Path(fixture["candidate_policy"])),
                amendment_path=fixture["amendment"],
                expected_amendment_sha256=_sha(Path(fixture["amendment"])),
                expected_amendment_plan_hash="b" * 64,
                feasibility_path=fixture["feasibility"],
                expected_feasibility_sha256=_sha(Path(fixture["feasibility"])),
                expected_candidate_contract_hash=str(fixture["candidate_contract_hash"]),
                output_patch_path=root / "preview.patch",
                output_proposal_path=root / "proposal.json",
                planned_outputs=planned,
                generated_at_utc="2026-08-09T18:00:00Z",
                git_executable=root / "unused-git.exe",
            )

    def test_builds_contingent_non_authorizing_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            result = self._build(root, fixture)
            proposal = json.loads((root / "proposal.json").read_text(encoding="utf-8"))

            self.assertEqual(result["status"], preview.PREVIEW_STATUS)
            self.assertFalse(result["collector_launch_allowed"])
            self.assertFalse(result["approval_request_allowed"])
            self.assertEqual(proposal["proposal_hash"], preview.canonical_proposal_hash(proposal))
            self.assertEqual(proposal["exact_preview"]["isolated_git_apply_check"], "PASS")

    def test_patch_changes_only_the_nine_aef_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            self._build(root, fixture)
            patch_text = (root / "preview.patch").read_text(encoding="utf-8")
            proposal = json.loads((root / "proposal.json").read_text(encoding="utf-8"))

            self.assertIn("+AEF_CAMPAIGN_ID", patch_text)
            self.assertIn('+        "hard_end_local": "2026-08-16T02:10:00+03:00",', patch_text)
            self.assertNotIn("hypothesis", patch_text.lower())
            self.assertNotIn("\n \n", patch_text)
            self.assertEqual(len(proposal["exact_preview"]["changed_scope_only"]), 9)
            self.assertEqual(
                proposal["exact_preview"]["expected_source_postimage_sha256"],
                proposal["exact_preview"]["isolated_git_apply_postimage_sha256"],
            )

    def test_rejects_source_preimage_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            source = Path(fixture["source"])
            source.write_bytes(source.read_bytes() + b"# drift\r\n")
            with self.assertRaisesRegex(ValueError, "source file SHA-256 mismatch"):
                with mock.patch.object(preview, "_sha256_file", wraps=preview._sha256_file):
                    preview.build_refreeze_preview(
                        repo_root=fixture["repo"],
                        source_path=source,
                        expected_source_sha256="0" * 64,
                        source_policy_path=fixture["source_policy"],
                        expected_source_policy_sha256=_sha(Path(fixture["source_policy"])),
                        reservation_path=fixture["reservation"],
                        expected_reservation_sha256=_sha(Path(fixture["reservation"])),
                        expected_reservation_hash=str(fixture["reservation_hash"]),
                        candidate_policy_path=fixture["candidate_policy"],
                        expected_candidate_policy_sha256=_sha(Path(fixture["candidate_policy"])),
                        amendment_path=fixture["amendment"],
                        expected_amendment_sha256=_sha(Path(fixture["amendment"])),
                        expected_amendment_plan_hash="b" * 64,
                        feasibility_path=fixture["feasibility"],
                        expected_feasibility_sha256=_sha(Path(fixture["feasibility"])),
                        expected_candidate_contract_hash=str(
                            fixture["candidate_contract_hash"]
                        ),
                        output_patch_path=root / "preview.patch",
                        output_proposal_path=root / "proposal.json",
                        planned_outputs={
                            key: root / "planned" / key for key in preview.PLANNED_OUTPUT_KEYS
                        },
                        generated_at_utc="2026-08-09T18:00:00Z",
                        git_executable=root / "git.exe",
                    )

    def test_rejects_stale_top_level_pit_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            policy_path = Path(fixture["candidate_policy"])
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["pit_n08_time_only_amendment"] = {"run_id": "stale"}
            _write_json(policy_path, policy)
            feasibility_path = Path(fixture["feasibility"])
            feasibility = json.loads(feasibility_path.read_text(encoding="utf-8"))
            feasibility["frozen_candidate"]["continuous_policy_sha256"] = _sha(policy_path)
            feasibility.pop("candidate_contract_hash")
            feasibility["candidate_contract_hash"] = preview._canonical_value_hash(
                feasibility["frozen_candidate"]
            )
            _write_json(feasibility_path, feasibility)
            fixture["candidate_contract_hash"] = feasibility["candidate_contract_hash"]

            with self.assertRaisesRegex(ValueError, "retained stale PIT bindings"):
                self._build(root, fixture)

    def test_rejects_feasibility_policy_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            feasibility_path = Path(fixture["feasibility"])
            feasibility = json.loads(feasibility_path.read_text(encoding="utf-8"))
            feasibility["frozen_candidate"]["continuous_policy_sha256"] = "d" * 64
            feasibility.pop("candidate_contract_hash")
            feasibility["candidate_contract_hash"] = preview._canonical_value_hash(
                feasibility["frozen_candidate"]
            )
            _write_json(feasibility_path, feasibility)
            fixture["candidate_contract_hash"] = feasibility["candidate_contract_hash"]

            with self.assertRaisesRegex(ValueError, "continuous_policy_sha256 mismatch"):
                self._build(root, fixture)

    def test_refuses_to_overwrite_immutable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            self._build(root, fixture)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                self._build(root, fixture)


if __name__ == "__main__":
    unittest.main()
