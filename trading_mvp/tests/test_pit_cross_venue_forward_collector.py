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

from pit_cross_venue_forward_collector import collect_forward_oos  # noqa: E402
from pit_cross_venue_forward_plan import PLAN_DECISION, PLAN_MODE, PLAN_SCHEMA  # noqa: E402


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class _Clock:
    def __init__(self, wall: float = 1_700_000_000.0) -> None:
        self.wall = wall
        self.mono = 0.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


def _write_plan(
    root: Path,
    *,
    target_valid_cycles: int = 2,
    min_active_span_sec: int = 2,
    max_active_duration_sec: int = 4,
    min_valid_pairs_per_cycle: int = 2,
    max_attempt_error_ratio: float = 0.5,
) -> Path:
    probe = root / "probe.json"
    probe.write_text("{}\n", encoding="utf-8")
    all_bases = ["AAA", "BBB", "CCC"]
    identity_bases = ["AAA", "BBB"]
    plan = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "decision": PLAN_DECISION,
        "would_start": False,
        "collect_started": False,
        "strategy_accepted": False,
        "source": {
            "probe_path": str(probe),
            "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        },
        "sealed_universe": {
            "all_discovery_bases": all_bases,
            "all_discovery_bases_sha256": _canonical_sha({"bases": all_bases}),
            "identity_evaluation_bases": identity_bases,
            "identity_evaluation_bases_sha256": _canonical_sha({"bases": identity_bases}),
            "identity_quarantine_bases": ["CCC"],
        },
        "collection_contract": {
            "interval_sec": 1,
            "target_valid_cycles": target_valid_cycles,
            "min_active_span_sec": min_active_span_sec,
            "max_active_duration_sec": max_active_duration_sec,
            "min_valid_pairs_per_cycle": min_valid_pairs_per_cycle,
            "max_attempt_cycles": max_active_duration_sec + 1,
            "max_attempt_error_ratio": max_attempt_error_ratio,
            "retry_attempts": 3,
            "retry_initial_backoff_sec": 0.5,
            "target_notional_quote": 100.0,
            "depth_limit": 20,
            "max_index_divergence_bps": 100.0,
            "max_mark_index_divergence_bps": 200.0,
            "max_quote_age_sec": 10.0,
            "max_cross_venue_skew_sec": 5.0,
        },
    }
    path = root / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _pair(base: str, valid: bool) -> dict:
    return {
        "base": base,
        "provisional_identity_match": valid,
        "fully_valid": valid,
        "invalid_reasons": [] if valid else ["fixture_invalid"],
        "max_net_screening_edge_bps": -10.0,
    }


class _CycleFetcher:
    def __init__(self, clock: _Clock, validity: list[set[str]]) -> None:
        self.clock = clock
        self.validity = validity
        self.calls = 0

    def __call__(self, attempt_cycle: int, bases: list[str], _probe_config) -> dict:
        valid = self.validity[min(self.calls, len(self.validity) - 1)]
        self.calls += 1
        return {
            "started_ts": self.clock.time(),
            "finished_ts": self.clock.time(),
            "discovery_errors": {},
            "pairs": [_pair(base, base in valid) for base in bases],
        }


class PitCrossVenueForwardCollectorTests(unittest.TestCase):
    def test_failed_segment_is_retained_but_not_counted_as_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root)
            clock = _Clock()
            fetcher = _CycleFetcher(clock, [{"AAA"}, {"AAA", "BBB"}, {"AAA", "BBB"}])

            manifest = collect_forward_oos(
                plan,
                root / "runs",
                "run-a",
                cycle_fetcher=fetcher,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertTrue(manifest["final"])
            self.assertTrue(manifest["quality_complete"])
            self.assertEqual(manifest["attempt_cycle_count"], 3)
            self.assertEqual(manifest["valid_cycle_count"], 2)
            self.assertEqual(manifest["failed_cycle_count"], 1)
            first = json.loads((root / "runs" / "run-a" / "segments" / "cycle_000001.json").read_text())
            self.assertFalse(first["cycle_valid"])
            self.assertEqual(first["valid_pair_count"], 1)

    def test_interrupted_run_resumes_same_run_without_overwriting_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root, min_active_span_sec=1, max_active_duration_sec=5)
            clock = _Clock()
            first_fetcher = _CycleFetcher(clock, [{"AAA", "BBB"}])

            first_manifest = collect_forward_oos(
                plan,
                root / "runs",
                "run-resume",
                cycle_fetcher=first_fetcher,
                stop_requested=lambda: first_fetcher.calls >= 1,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )
            segment = root / "runs" / "run-resume" / "segments" / "cycle_000001.json"
            before = hashlib.sha256(segment.read_bytes()).hexdigest()

            self.assertFalse(first_manifest["final"])
            self.assertEqual(first_manifest["status"], "STOPPED_INCOMPLETE")

            second_fetcher = _CycleFetcher(clock, [{"AAA", "BBB"}])
            resumed = collect_forward_oos(
                plan,
                root / "runs",
                "run-resume",
                resume=True,
                cycle_fetcher=second_fetcher,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertTrue(resumed["final"])
            self.assertTrue(resumed["quality_complete"])
            self.assertEqual(resumed["attempt_cycle_count"], 2)
            self.assertEqual(resumed["resume_count"], 1)
            self.assertEqual(before, hashlib.sha256(segment.read_bytes()).hexdigest())
            self.assertTrue((root / "runs" / "run-resume" / "segments" / "cycle_000002.json").is_file())

    def test_max_duration_finalizes_insufficient_evidence_without_rewriting_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(
                root,
                target_valid_cycles=3,
                min_active_span_sec=1,
                max_active_duration_sec=2,
                max_attempt_error_ratio=0.5,
            )
            clock = _Clock()
            fetcher = _CycleFetcher(clock, [set()])

            manifest = collect_forward_oos(
                plan,
                root / "runs",
                "run-shortfall",
                cycle_fetcher=fetcher,
                wall_time_fn=clock.time,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertTrue(manifest["final"])
            self.assertFalse(manifest["quality_complete"])
            self.assertEqual(manifest["status"], "COMPLETED_INSUFFICIENT_EVIDENCE")
            self.assertGreaterEqual(manifest["failed_cycle_count"], 1)


if __name__ == "__main__":
    unittest.main()
