from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_cross_venue_fast_pipeline import DECISION_READY, FAST_MODE, FAST_SCHEMA  # noqa: E402
from pit_cross_venue_short_probe_collector import collect_short_probe  # noqa: E402
from pit_cross_venue_short_probe_plan import (  # noqa: E402
    SHORT_PLAN_DECISION,
    SHORT_PLAN_MODE,
    SHORT_PLAN_SCHEMA,
)


class _Clock:
    def __init__(self) -> None:
        self.wall = 1_700_000_000.0
        self.mono = 0.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


def _write_plan(root: Path, *, futility_attempts: int = 3) -> Path:
    fast = root / "fast.json"
    fast.write_text(
        json.dumps(
            {
                "schema": FAST_SCHEMA,
                "mode": FAST_MODE,
                "decision": DECISION_READY,
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "schema": SHORT_PLAN_SCHEMA,
        "mode": SHORT_PLAN_MODE,
        "decision": SHORT_PLAN_DECISION,
        "would_start": False,
        "collect_started": False,
        "strategy_accepted": False,
        "long_run_required_now": False,
        "source": {
            "fast_output_path": str(fast),
            "fast_output_sha256": hashlib.sha256(fast.read_bytes()).hexdigest(),
        },
        "instrument_scope": {"candidate_bases": ["AAA", "BBB", "CCC"]},
        "collection_contract": {
            "interval_sec": 1,
            "min_duration_sec": 1,
            "max_duration_sec": 5,
            "target_valid_samples": 2,
            "min_valid_pairs_per_sample": 2,
            "independence_gap_samples": 1,
            "target_notional_quote": 100.0,
            "depth_limit": 20,
            "max_index_divergence_bps": 100.0,
            "max_mark_index_divergence_bps": 200.0,
            "max_quote_age_sec": 10.0,
            "max_cross_venue_skew_sec": 5.0,
            "round_trip_fee_bps": 39.0,
            "slippage_bps": 10.0,
            "operational_buffer_bps": 20.0,
            "fixed_total_cost_bps": 69.0,
        },
        "sequential_stop_contract": {
            "quality_checkpoint_min_attempts": 2,
            "quality_min_valid_sample_ratio": 0.5,
            "quality_max_fetch_error_ratio": 0.5,
            "futility_checkpoint_min_attempts": futility_attempts,
            "futility_if_zero_fixed_cost_positive_samples": True,
            "success_min_valid_samples": 2,
            "success_min_independent_episodes": 2,
            "success_min_event_bases": 2,
            "success_max_top1_base_concentration": 0.6,
            "success_requires_positive_samples_in_both_chronological_halves": True,
        },
        "fail_closed_contract": {
            "thresholds_frozen_before_independent_short_probe": True,
            "threshold_mutation_after_start_allowed": False,
            "automatic_next_stage_allowed": False,
        },
    }
    path = root / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _pair(base: str, *, positive: bool) -> dict:
    return {
        "base": base,
        "provisional_identity_match": True,
        "fully_valid": True,
        "invalid_reasons": [],
        "gross_execution_edges": {
            "buy_mexc_sell_gateio_bps": 80.0 if positive else 10.0,
            "buy_gateio_sell_mexc_bps": -90.0,
        },
        "max_net_screening_edge_bps": 11.0 if positive else -59.0,
        "max_net_observed_base_fee_bps": 20.0 if positive else -50.0,
    }


class _Fetcher:
    def __init__(self, positive_by_call: list[set[str]]) -> None:
        self.positive_by_call = positive_by_call
        self.calls = 0

    def __call__(self, _sample: int, bases: list[str], _cfg) -> dict:
        positive = self.positive_by_call[min(self.calls, len(self.positive_by_call) - 1)]
        self.calls += 1
        return {
            "started_ts": 1_700_000_000.0,
            "finished_ts": 1_700_000_000.1,
            "discovery_errors": {},
            "pairs": [_pair(base, positive=base in positive) for base in bases],
        }


class ShortProbeCollectorTests(unittest.TestCase):
    def test_sequential_success_stops_before_max_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root)
            clock = _Clock()
            fetcher = _Fetcher([{"AAA"}, {"BBB"}])

            manifest = collect_short_probe(
                plan,
                root / "runs",
                "run-success",
                cycle_fetcher=fetcher,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertEqual(manifest["status"], "COMPLETED_SHORT_PROBE_READY_FOR_OFFLINE_EVALUATION")
            self.assertTrue(manifest["final"])
            self.assertEqual(manifest["attempt_sample_count"], 2)
            self.assertEqual(manifest["independent_episodes"], 2)
            self.assertFalse(manifest["long_run_allowed"])

    def test_zero_positive_samples_stops_at_futility_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root, futility_attempts=3)
            clock = _Clock()
            fetcher = _Fetcher([set()])

            manifest = collect_short_probe(
                plan,
                root / "runs",
                "run-futility",
                cycle_fetcher=fetcher,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertEqual(manifest["status"], "COMPLETED_SHORT_PROBE_FUTILITY")
            self.assertEqual(manifest["attempt_sample_count"], 3)
            self.assertEqual(manifest["stop_reason"], "futility_checkpoint_zero_fixed_cost_positive_samples")

    def test_resume_preserves_existing_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root)
            clock = _Clock()
            first_fetcher = _Fetcher([{"AAA"}])

            first = collect_short_probe(
                plan,
                root / "runs",
                "run-resume",
                cycle_fetcher=first_fetcher,
                stop_requested=lambda: first_fetcher.calls >= 1,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )
            sample = root / "runs" / "run-resume" / "samples" / "sample_000001.json"
            before = hashlib.sha256(sample.read_bytes()).hexdigest()
            self.assertEqual(first["status"], "STOPPED_INCOMPLETE")

            resumed = collect_short_probe(
                plan,
                root / "runs",
                "run-resume",
                resume=True,
                cycle_fetcher=_Fetcher([{"BBB"}]),
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertEqual(resumed["status"], "COMPLETED_SHORT_PROBE_READY_FOR_OFFLINE_EVALUATION")
            self.assertEqual(resumed["resume_count"], 1)
            self.assertEqual(before, hashlib.sha256(sample.read_bytes()).hexdigest())
            self.assertTrue((sample.parent / "sample_000002.json").is_file())


if __name__ == "__main__":
    unittest.main()
