from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_n08_no_skip_feasibility_amendment as amendment  # noqa: E402
import night_schedule_plan as pit_schedule  # noqa: E402


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class DenseWsN08NoSkipFeasibilityAmendmentTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> dict[str, Path | str]:
        candidate = {
            "hypothesis_id": "dense_ws_microstructure_regime_filter_v1",
            "data_type": "DENSE_WS_SEGMENTED",
            "requested_start_local": "2026-08-04T01:40:00+03:00",
            "window_id": "EVIDENCE_EXCEPTION_2026-08-04_24H",
            "writer_deadline_local": "2026-08-05T01:40:00+03:00",
            "hard_deadline_local": "2026-08-05T02:10:00+03:00",
            "target_writer_sec": 86400,
            "segment_sec": 3600,
            "suppressed_pit_run_ids": [amendment.N08_RUN_ID],
        }
        feasibility = root / "base-feasibility.json"
        _write(
            feasibility,
            {
                "schema": "trading_mvp_dense_ws_campaign_feasibility_v1",
                "mode": "PlanOnly",
                "research_only": True,
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
                "window_feasibility": {
                    "phases": [
                        {
                            "phase_id": "phase_01",
                            "start_local": "2026-08-04T01:40:00+03:00",
                            "hard_end_local": "2026-08-05T02:10:00+03:00",
                        }
                    ],
                    "pit_blackouts": [],
                    "suppressed_pit_run_ids": [amendment.N08_RUN_ID],
                },
                "operational_baseline": {"source_root": "diagnostic-only"},
                "frozen_candidate": candidate,
                "candidate_contract_hash": amendment._canonical_hash(candidate),
            },
        )
        policy = root / "policy.json"
        _write(
            policy,
            {
                "accelerated_evidence_factory": {
                    "continuous_evidence_exception": {
                        "campaign_id": "dense_ws_microstructure_regime_filter_v1_20260804_aef_24h",
                        "start_local": "2026-08-04T01:40:00+03:00",
                        "writer_deadline_local": "2026-08-05T01:40:00+03:00",
                        "hard_deadline_local": "2026-08-05T02:10:00+03:00",
                        "suppressed_pit_run_ids": [],
                        "deferred_pit_run_id": amendment.N08_RUN_ID,
                        "deferred_pit_start_local": "2026-08-05T02:15:00+03:00",
                        "deferred_pit_end_local": "2026-08-05T02:35:00+03:00",
                        "deferred_pit_requires_dense_finalization": True,
                        "deferred_pit_requires_global_writer_claim_absent": True,
                    }
                }
            },
        )
        pit = root / "pit.json"
        _write(
            pit,
            {
                "schema": pit_schedule.PLAN_SCHEMA,
                "mode": "PlanOnly",
                "plan_hash": "a" * 64,
                "time_only_amendment": {
                    "run_id": amendment.N08_RUN_ID,
                    "new_start_local": "2026-08-05T02:15:00+03:00",
                    "new_end_local": "2026-08-05T02:35:00+03:00",
                    "hard_deadline_local": "2026-08-05T07:00:00+03:00",
                    "trade_contract_changed": False,
                },
                "segments": [
                    {
                        "run_id": amendment.N08_RUN_ID,
                        "start_local": "2026-08-05T02:15:00+03:00",
                        "end_local": "2026-08-05T02:35:00+03:00",
                        "hard_deadline_local": "2026-08-05T07:00:00+03:00",
                    }
                ],
            },
        )
        return {
            "feasibility": feasibility,
            "policy": policy,
            "pit": pit,
            "feasibility_sha": hashlib.sha256(feasibility.read_bytes()).hexdigest(),
        }

    def test_rebinds_only_time_provenance_without_reloading_partial_market_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            output = root / "amended-feasibility.json"
            result = amendment.build_no_skip_feasibility_amendment(
                base_feasibility_path=fixture["feasibility"],
                expected_base_feasibility_sha256=str(fixture["feasibility_sha"]),
                continuous_policy_path=fixture["policy"],
                amended_pit_schedule_path=fixture["pit"],
                expected_amended_pit_plan_hash="a" * 64,
                output_path=output,
                generated_at_utc="2026-08-03T16:30:00+00:00",
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "TIME_ONLY_N08_NO_SKIP_FEASIBILITY_VALID")
            self.assertEqual(payload["window_feasibility"]["suppressed_pit_run_ids"], [])
            self.assertEqual(payload["frozen_candidate"]["suppressed_pit_run_ids"], [])
            self.assertEqual(
                payload["time_only_n08_no_skip_amendment"]["global_writer_gap_sec"],
                300,
            )
            self.assertFalse(payload["time_only_n08_no_skip_amendment"]["legacy_partial_market_data_reread"])

    def test_rejects_n08_that_overlaps_dense_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            policy = json.loads(Path(fixture["policy"]).read_text(encoding="utf-8"))
            policy["accelerated_evidence_factory"]["continuous_evidence_exception"][
                "deferred_pit_start_local"
            ] = "2026-08-05T02:10:00+03:00"
            policy["accelerated_evidence_factory"]["continuous_evidence_exception"][
                "deferred_pit_end_local"
            ] = "2026-08-05T02:30:00+03:00"
            _write(Path(fixture["policy"]), policy)
            pit = json.loads(Path(fixture["pit"]).read_text(encoding="utf-8"))
            pit["time_only_amendment"]["new_start_local"] = "2026-08-05T02:10:00+03:00"
            pit["time_only_amendment"]["new_end_local"] = "2026-08-05T02:30:00+03:00"
            pit["segments"][0]["start_local"] = "2026-08-05T02:10:00+03:00"
            pit["segments"][0]["end_local"] = "2026-08-05T02:30:00+03:00"
            _write(Path(fixture["pit"]), pit)

            with self.assertRaisesRegex(ValueError, "strictly after dense hard finalization"):
                amendment.build_no_skip_feasibility_amendment(
                    base_feasibility_path=fixture["feasibility"],
                    expected_base_feasibility_sha256=str(fixture["feasibility_sha"]),
                    continuous_policy_path=fixture["policy"],
                    amended_pit_schedule_path=fixture["pit"],
                    expected_amended_pit_plan_hash="a" * 64,
                    output_path=root / "overlap.json",
                    generated_at_utc="2026-08-03T16:30:00+00:00",
                )

    def test_rejects_policy_that_still_suppresses_n08(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self._fixtures(root)
            policy = json.loads(Path(fixture["policy"]).read_text(encoding="utf-8"))
            policy["accelerated_evidence_factory"]["continuous_evidence_exception"][
                "suppressed_pit_run_ids"
            ] = [amendment.N08_RUN_ID]
            _write(Path(fixture["policy"]), policy)

            with self.assertRaisesRegex(ValueError, "must not suppress PIT n08"):
                amendment.build_no_skip_feasibility_amendment(
                    base_feasibility_path=fixture["feasibility"],
                    expected_base_feasibility_sha256=str(fixture["feasibility_sha"]),
                    continuous_policy_path=fixture["policy"],
                    amended_pit_schedule_path=fixture["pit"],
                    expected_amended_pit_plan_hash="a" * 64,
                    output_path=root / "still-suppressed.json",
                    generated_at_utc="2026-08-03T16:30:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
