from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments import (  # noqa: E402
    SETUP_REGISTRY,
    append_experiment_record,
    extract_metrics_from_artifact,
    make_experiment_record,
    read_experiment_ledger,
    setup_registry_payload,
    summarize_experiment_ledger,
)


class ExperimentTests(unittest.TestCase):
    def test_setup_registry_contains_core_setups(self) -> None:
        payload = setup_registry_payload()
        setup_ids = {item["setup_id"] for item in payload["setups"]}
        self.assertEqual(payload["count"], len(SETUP_REGISTRY))
        self.assertTrue({"flow_continue", "fade_exhaustion", "perp_replay", "liquidity_sweep_reversal", "funding_basis_carry"}.issubset(setup_ids))
        self.assertTrue(
            {
                "cross_venue_dislocation",
                "listing_event_drift_reversal",
                "slow_liquidity_reversal",
                "pit_universe_event_liquidity",
                "venue_local_lottery_max_factor_v1",
                "venue_local_funding_pressure_reversal_v1",
            }.issubset(setup_ids)
        )

    def test_record_roundtrip_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "experiment_ledger.jsonl"
            record = make_experiment_record(
                source_video_id="abc123",
                source_url="https://www.youtube.com/watch?v=abc123",
                participant="Михаил Латогузов",
                claim_family="orderbook_tape_continuation",
                hypothesis="Order book continuation should survive maker queue and quality filters.",
                setup_id="flow_continue",
                dataset="ws_normalized_6h_20260604.jsonl",
                config={"execution_mode": "maker"},
                result_artifact="exports/trading-mvp/backtests/ws_grid_search_signal_type_maker_quality_6h_20260608.json",
                metrics={"net_pnl_quote": -0.2, "profit_factor": 0.72},
                verdict="rejected",
                verdict_reason="negative net pnl after costs",
                tags=["microstructure", "maker"],
                notes="research-only",
            )
            append_experiment_record(ledger, record)
            rows = read_experiment_ledger(ledger)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["setup_id"], "flow_continue")
            summary = summarize_experiment_ledger(ledger, verdict="rejected", setup_id="flow_continue", top_n=5)
            self.assertEqual(summary["total_records"], 1)
            self.assertEqual(summary["filtered_records"], 1)
            self.assertEqual(summary["by_verdict"]["rejected"], 1)

    def test_extract_metrics_from_artifact_uses_signal_specific_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            payload = {
                "best_by_signal_type": {
                    "flow_continue": {"metrics": {"net_pnl_quote": 1.23, "profit_factor": 1.5}},
                    "fade_exhaustion": {"metrics": {"net_pnl_quote": -2.0, "profit_factor": 0.7}},
                }
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            metrics = extract_metrics_from_artifact(path, setup_id="flow_continue")
            self.assertEqual(metrics["net_pnl_quote"], 1.23)
            self.assertEqual(metrics["profit_factor"], 1.5)

    def test_make_experiment_record_rejects_unknown_setup(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown setup_id"):
            make_experiment_record(
                source_video_id="abc123",
                source_url="https://www.youtube.com/watch?v=abc123",
                participant="",
                claim_family="unknown",
                hypothesis="test",
                setup_id="not_a_setup",
                dataset="x.jsonl",
                config={},
                result_artifact="",
                metrics={},
                verdict="untested",
                verdict_reason="",
            )

    def test_record_captures_reproducible_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset.jsonl"
            artifact = root / "result.json"
            dataset.write_text('{"x":1}\n', encoding="utf-8")
            artifact.write_text(json.dumps({"metrics": {"net_pnl_quote": 1.0}}), encoding="utf-8")

            record = make_experiment_record(
                source_video_id="",
                source_url="",
                participant="internal research",
                claim_family="point_in_time_universe",
                hypothesis="PIT universe events may contain a structural liquidity edge.",
                setup_id="pit_universe_event_liquidity",
                dataset=str(dataset),
                config={"spot_fee_bps": 10.0},
                result_artifact=str(artifact),
                metrics={"net_pnl_quote": 1.0},
                verdict="promising",
                verdict_reason="research gate passed",
                fee_schedule_revision="base_tier_2026-07",
                evaluation_scope="chronological_oos",
                oos_status="passed",
            )

            self.assertEqual(len(record.dataset_sha256), 64)
            self.assertEqual(len(record.result_artifact_sha256), 64)
            self.assertEqual(len(record.config_sha256), 64)
            self.assertTrue(record.python_version)
            self.assertTrue(record.platform)
            self.assertEqual(record.fee_schedule_revision, "base_tier_2026-07")
            self.assertEqual(record.evaluation_scope, "chronological_oos")
            self.assertTrue(record.provenance_complete)

    def test_append_rejects_artifact_changed_after_record_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset.jsonl"
            artifact = root / "result.json"
            ledger = root / "ledger.jsonl"
            dataset.write_text("{}\n", encoding="utf-8")
            artifact.write_text("{}", encoding="utf-8")
            record = make_experiment_record(
                source_video_id="",
                source_url="",
                participant="internal research",
                claim_family="listing_event",
                hypothesis="fixture",
                setup_id="listing_event_drift_reversal",
                dataset=str(dataset),
                config={},
                result_artifact=str(artifact),
                metrics={},
                verdict="rejected",
                verdict_reason="fixture",
            )
            artifact.write_text('{"changed":true}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                append_experiment_record(ledger, record)

    def test_positive_verdict_requires_existing_dataset_and_result(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires existing"):
            make_experiment_record(
                source_video_id="",
                source_url="",
                participant="internal research",
                claim_family="listing_event",
                hypothesis="fixture",
                setup_id="listing_event_drift_reversal",
                dataset="missing.jsonl",
                config={},
                result_artifact="missing.json",
                metrics={},
                verdict="promising",
                verdict_reason="should be blocked",
            )


if __name__ == "__main__":
    unittest.main()
