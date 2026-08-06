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

from pit_cross_venue_diagnostic_freeze import (  # noqa: E402
    FREEZE_DECISION,
    freeze_incomplete_run,
)
from pit_cross_venue_forward_collector import collect_forward_oos  # noqa: E402
from pit_cross_venue_forward_plan import PLAN_DECISION, PLAN_MODE, PLAN_SCHEMA  # noqa: E402


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_plan(root: Path) -> Path:
    probe = root / "probe.json"
    probe.write_text("{}\n", encoding="utf-8")
    bases = ["AAA", "BBB"]
    plan = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "decision": PLAN_DECISION,
        "would_start": False,
        "collect_started": False,
        "strategy_accepted": False,
        "source": {"probe_path": str(probe), "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest()},
        "sealed_universe": {
            "all_discovery_bases": bases,
            "all_discovery_bases_sha256": _canonical_sha({"bases": bases}),
            "identity_evaluation_bases": bases,
            "identity_evaluation_bases_sha256": _canonical_sha({"bases": bases}),
            "identity_quarantine_bases": [],
        },
        "collection_contract": {
            "interval_sec": 1,
            "target_valid_cycles": 2,
            "min_active_span_sec": 2,
            "max_active_duration_sec": 4,
            "min_valid_pairs_per_cycle": 2,
            "max_attempt_cycles": 5,
            "max_attempt_error_ratio": 0.5,
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


def _fetcher(_cycle: int, bases: list[str], _cfg) -> dict:
    return {
        "started_ts": 1_700_000_000.0,
        "finished_ts": 1_700_000_001.0,
        "discovery_errors": {},
        "pairs": [
            {
                "base": base,
                "fully_valid": True,
                "provisional_identity_match": True,
                "invalid_reasons": [],
                "max_net_screening_edge_bps": 1.0,
                "max_net_observed_base_fee_bps": 2.0,
            }
            for base in bases
        ],
    }


class _StoppingFetcher:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, cycle: int, bases: list[str], cfg) -> dict:
        self.calls += 1
        return _fetcher(cycle, bases, cfg)


class DiagnosticFreezeTests(unittest.TestCase):
    def test_freeze_validates_and_classifies_interrupted_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root)
            fetcher = _StoppingFetcher()
            manifest = collect_forward_oos(
                plan,
                root / "runs",
                "run-a",
                cycle_fetcher=fetcher,
                stop_requested=lambda: fetcher.calls >= 1,
                sleep_fn=lambda _seconds: None,
            )
            self.assertEqual(manifest["status"], "STOPPED_INCOMPLETE")

            output = root / "freeze.json"
            report = freeze_incomplete_run(plan, root / "runs" / "run-a", output, reason="workflow redesign")

            self.assertEqual(report["decision"], FREEZE_DECISION)
            self.assertEqual(report["dataset_role"], "diagnostic_only")
            self.assertTrue(report["integrity_verified"])
            self.assertFalse(report["safety"]["oos_evidence"])
            self.assertEqual(report["counts"]["attempt_cycles"], 1)
            self.assertTrue(output.is_file())

    def test_freeze_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _write_plan(root)
            fetcher = _StoppingFetcher()
            collect_forward_oos(
                plan,
                root / "runs",
                "run-a",
                cycle_fetcher=fetcher,
                stop_requested=lambda: fetcher.calls >= 1,
                sleep_fn=lambda _seconds: None,
            )
            output = root / "freeze.json"
            freeze_incomplete_run(plan, root / "runs" / "run-a", output, reason="workflow redesign")
            with self.assertRaises(FileExistsError):
                freeze_incomplete_run(plan, root / "runs" / "run-a", output, reason="rewrite")


if __name__ == "__main__":
    unittest.main()
