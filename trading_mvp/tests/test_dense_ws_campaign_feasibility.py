from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dense_ws_campaign_feasibility import build_feasibility  # noqa: E402


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class DenseWsCampaignFeasibilityTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> dict[str, Path]:
        bank = root / "bank.json"
        _write(
            bank,
            {
                "hypotheses": [
                    {
                        "id": "dense_ws_microstructure_regime_filter_v1",
                        "status": "BANKED_NEEDS_NEW_DATA",
                        "required_data_type": "DENSE_WS_SEGMENTED",
                        "thesis": "frozen before OOS",
                        "minimum_data": {
                            "hours": 24,
                            "valid_segments": 8,
                            "dual_venue_coverage": 0.8,
                            "execution_snapshots": 180,
                        },
                        "forbidden": ["orderbook grid"],
                    }
                ]
            },
        )
        policy = root / "continuous.json"
        _write(
            policy,
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
                    },
                },
                "approval": {"request_lead_minutes": 30},
                "runtime": {
                    "short_offline_task_max_runtime_sec": 1800,
                    "shutdown_grace_sec": 900,
                },
            },
        )
        schedule = root / "schedule.json"
        _write(
            schedule,
            {
                "segments": [
                    {
                        "run_id": "pit_1",
                        "start_local": "2026-08-01T01:00:00+03:00",
                        "end_local": "2026-08-01T01:20:00+03:00",
                    }
                ]
            },
        )
        universe = root / "universe.csv"
        universe.write_text("symbol\nAAA\nBBB\n", encoding="utf-8")
        manifests = root / "manifests"
        for index in range(2):
            segment = manifests / f"seg_{index + 1:03d}"
            segment.mkdir(parents=True)
            gate = segment / "gate.jsonl"
            mexc = segment / "mexc.jsonl"
            gate.write_text("x" * 100, encoding="utf-8")
            mexc.write_text("x" * 100, encoding="utf-8")
            _write(
                segment / "manifest.json",
                {
                    "requested_duration_sec": 3600,
                    "actual_duration_sec": 3600,
                    "completed": True,
                    "final": True,
                    "total_events": 7200,
                    "errors": {},
                    "results": [
                        {
                            "exchange": "gateio",
                            "events": 3600,
                            "errors": [],
                            "output": str(gate),
                        },
                        {
                            "exchange": "mexc",
                            "events": 3600,
                            "errors": [],
                            "output": str(mexc),
                        },
                    ],
                },
            )
        return {
            "bank": bank,
            "policy": policy,
            "schedule": schedule,
            "universe": universe,
            "manifests": manifests,
        }

    def test_weekend_plan_allocates_24h_around_pit_blackout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = self._fixtures(root)
            output = root / "result.json"
            result = build_feasibility(
                hypothesis_bank_path=fixtures["bank"],
                continuous_policy_path=fixtures["policy"],
                pit_schedule_path=fixtures["schedule"],
                prior_manifest_root=fixtures["manifests"],
                universe_path=fixtures["universe"],
                requested_start_local="2026-07-31T19:00:00+03:00",
                output_path=output,
            )
            self.assertTrue(output.exists())

        self.assertEqual(
            result["verdict"],
            "FEASIBILITY_CONFIRMED_CONTRACT_FREEZE_REQUIRED",
        )
        self.assertFalse(result["would_start"])
        self.assertFalse(result["network_access"])
        self.assertFalse(result["returns_read"])
        self.assertEqual(
            result["window_feasibility"]["planned_writer_sec"],
            24 * 3600,
        )
        self.assertGreaterEqual(
            result["window_feasibility"]["complete_durable_segments"],
            8,
        )
        self.assertEqual(
            len(result["window_feasibility"]["pit_blackouts"]),
            1,
        )
        self.assertFalse(
            result["operational_baseline"][
                "admissible_for_hypothesis_evidence"
            ]
        )

    def test_missing_operational_samples_fails_feasibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = self._fixtures(root)
            empty = root / "empty"
            empty.mkdir()
            result = build_feasibility(
                hypothesis_bank_path=fixtures["bank"],
                continuous_policy_path=fixtures["policy"],
                pit_schedule_path=fixtures["schedule"],
                prior_manifest_root=empty,
                universe_path=fixtures["universe"],
                requested_start_local="2026-07-31T19:00:00+03:00",
                output_path=root / "failed.json",
            )

        self.assertEqual(
            result["verdict"],
            "INFEASIBLE_ON_CURRENT_WINDOW_OR_OPERATIONS",
        )
        self.assertIn(
            "insufficient_operational_throughput_samples",
            result["feasibility_reasons"],
        )

    def test_segmented_campaign_uses_later_nights_without_weekday_daytime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = self._fixtures(root)
            policy = json.loads(fixtures["policy"].read_text(encoding="utf-8"))
            policy["runtime"]["shutdown_grace_sec"] = 1_800
            policy["accelerated_evidence_factory"] = {
                "segmented_campaign_max_windows": 3,
                "hard_campaign_output_cap_bytes": 25_000_000_000,
            }
            _write(fixtures["policy"], policy)
            _write(
                fixtures["schedule"],
                {
                    "segments": [
                        {
                            "run_id": "pit_n06",
                            "start_local": "2026-08-03T01:00:00+03:00",
                            "end_local": "2026-08-03T01:20:00+03:00",
                        }
                    ]
                },
            )
            try:
                result = build_feasibility(
                    hypothesis_bank_path=fixtures["bank"],
                    continuous_policy_path=fixtures["policy"],
                    pit_schedule_path=fixtures["schedule"],
                    prior_manifest_root=fixtures["manifests"],
                    universe_path=fixtures["universe"],
                    requested_start_local="2026-08-02T19:00:00+03:00",
                    output_path=root / "segmented.json",
                    target_writer_sec_override=105_000,
                )
            except ValueError as exc:
                self.fail(f"segmented campaign should be feasible: {exc}")

        window = result["window_feasibility"]
        self.assertEqual(
            result["verdict"],
            "FEASIBILITY_CONFIRMED_CONTRACT_FREEZE_REQUIRED",
        )
        self.assertEqual(window["window_type"], "SEGMENTED")
        self.assertEqual(window["planned_writer_sec"], 105_000)
        self.assertEqual(window["unallocated_writer_sec"], 0)
        self.assertEqual(window["hard_deadline_local"], "2026-08-05T08:00:00+03:00")
        self.assertEqual(len(window["collection_windows"]), 3)
        self.assertEqual(
            [phase["start_local"] for phase in window["phases"]],
            [
                "2026-08-02T19:00:00+03:00",
                "2026-08-03T01:40:00+03:00",
                "2026-08-03T19:00:00+03:00",
                "2026-08-04T19:00:00+03:00",
            ],
        )
        for phase in window["phases"]:
            start = phase["start_local"][11:16]
            end = phase["end_local"][11:16]
            self.assertTrue(start >= "19:00" or start < "08:00")
            self.assertTrue(end <= "08:00" or end >= "19:00")
        self.assertGreaterEqual(window["complete_durable_segments"], 24)

    def test_exact_evidence_exception_allows_one_uninterrupted_24h_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = self._fixtures(root)
            policy = json.loads(fixtures["policy"].read_text(encoding="utf-8"))
            policy["runtime"]["shutdown_grace_sec"] = 1_800
            policy["accelerated_evidence_factory"] = {
                "continuous_evidence_exception": {
                    "enabled": True,
                    "campaign_id": (
                        "dense_ws_microstructure_regime_filter_v1_20260803_aef_24h"
                    ),
                    "window_id": "EVIDENCE_EXCEPTION_2026-08-03_24H",
                    "start_local": "2026-08-03T01:30:00+03:00",
                    "writer_duration_sec": 86_400,
                    "writer_deadline_local": "2026-08-04T01:30:00+03:00",
                    "hard_deadline_local": "2026-08-04T02:00:00+03:00",
                    "uninterrupted_required": True,
                    "suppressed_pit_run_ids": ["pit_n07"],
                },
                "hard_campaign_output_cap_bytes": 25_000_000_000,
            }
            _write(fixtures["policy"], policy)
            _write(
                fixtures["schedule"],
                {
                    "segments": [
                        {
                            "run_id": "pit_n06",
                            "start_local": "2026-08-03T01:00:00+03:00",
                            "end_local": "2026-08-03T01:20:00+03:00",
                        },
                        {
                            "run_id": "pit_n07",
                            "start_local": "2026-08-04T01:00:00+03:00",
                            "end_local": "2026-08-04T01:20:00+03:00",
                        }
                    ]
                },
            )
            result = build_feasibility(
                hypothesis_bank_path=fixtures["bank"],
                continuous_policy_path=fixtures["policy"],
                pit_schedule_path=fixtures["schedule"],
                prior_manifest_root=fixtures["manifests"],
                universe_path=fixtures["universe"],
                requested_start_local="2026-08-03T01:30:00+03:00",
                output_path=root / "continuous-feasibility.json",
                target_writer_sec_override=86_400,
                certification_sec=600,
            )

        window = result["window_feasibility"]
        self.assertEqual(
            result["verdict"],
            "FEASIBILITY_CONFIRMED_CONTRACT_FREEZE_REQUIRED",
        )
        self.assertEqual(window["window_type"], "EVIDENCE_VALUE_EXCEPTION")
        self.assertEqual(window["window_id"], "EVIDENCE_EXCEPTION_2026-08-03_24H")
        self.assertEqual(window["planned_writer_sec"], 86_400)
        self.assertEqual(window["unallocated_writer_sec"], 0)
        self.assertEqual(window["campaign_end_local"], "2026-08-04T01:30:00+03:00")
        self.assertEqual(window["hard_deadline_local"], "2026-08-04T02:00:00+03:00")
        self.assertEqual(window["pit_blackouts"], [])
        self.assertEqual(window["suppressed_pit_run_ids"], ["pit_n07"])
        self.assertEqual(
            window["phases"],
            [
                {
                    "phase_id": "phase_01",
                    "start_local": "2026-08-03T01:30:00+03:00",
                    "end_local": "2026-08-04T01:30:00+03:00",
                    "hard_end_local": "2026-08-04T02:00:00+03:00",
                    "writer_duration_sec": 86_400,
                    "complete_durable_segments": 24,
                }
            ],
        )
        self.assertTrue(window["uninterrupted_required"])


if __name__ == "__main__":
    unittest.main()
