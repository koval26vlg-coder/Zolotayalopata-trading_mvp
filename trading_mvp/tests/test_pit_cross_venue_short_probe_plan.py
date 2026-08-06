from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_cross_venue_fast_pipeline import DECISION_READY, FAST_MODE, FAST_SCHEMA  # noqa: E402
from pit_cross_venue_short_probe_plan import (  # noqa: E402
    SHORT_PLAN_DECISION,
    build_short_probe_plan,
)


def _write_fast_output(root: Path, *, ready: bool = True) -> Path:
    original_plan = root / "original_plan.json"
    original_plan.write_text(
        json.dumps(
            {
                "collection_contract": {
                    "max_index_divergence_bps": 100.0,
                    "max_mark_index_divergence_bps": 200.0,
                    "max_quote_age_sec": 10.0,
                    "max_cross_venue_skew_sec": 5.0,
                }
            }
        ),
        encoding="utf-8",
    )
    import hashlib

    freeze = root / "freeze.json"
    freeze.write_text(
        json.dumps(
            {
                "source": {
                    "plan_path": str(original_plan),
                    "plan_sha256": hashlib.sha256(original_plan.read_bytes()).hexdigest(),
                }
            }
        ),
        encoding="utf-8",
    )
    value = {
        "schema": FAST_SCHEMA,
        "mode": FAST_MODE,
        "decision": DECISION_READY if ready else "REJECTED",
        "strategy_accepted": False,
        "oos_evidence": False,
        "source": {
            "diagnostic_freeze_path": str(freeze),
            "diagnostic_freeze_sha256": hashlib.sha256(freeze.read_bytes()).hexdigest(),
        },
        "cost_gate": {"fixed_total_cost_bps": 69.0},
        "diagnostics": {"eligible_for_short_probe": ready, "eligibility_reasons": [] if ready else ["failed"]},
        "short_probe_contract": {
            "candidate_bases": ["AAA", "BBB"],
            "interval_sec": 5,
            "min_duration_sec": 3600,
            "max_duration_sec": 10800,
            "target_valid_samples": 1000,
            "early_quality_checkpoint_sec": 900,
            "early_futility_checkpoint_sec": 1800,
            "min_valid_sample_ratio": 0.7,
            "max_fetch_error_ratio": 0.1,
        },
    }
    path = root / "fast.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class ShortProbePlanTests(unittest.TestCase):
    def test_builds_fail_closed_short_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fast = _write_fast_output(root)
            output = root / "plan.json"

            plan = build_short_probe_plan(fast, output)

            self.assertEqual(plan["decision"], SHORT_PLAN_DECISION)
            self.assertFalse(plan["would_start"])
            self.assertFalse(plan["long_run_required_now"])
            self.assertEqual(plan["instrument_scope"]["candidate_bases"], ["AAA", "BBB"])
            self.assertEqual(plan["collection_contract"]["max_duration_sec"], 10800)
            self.assertEqual(plan["collection_contract"]["min_valid_pairs_per_sample"], 2)
            self.assertEqual(plan["collection_contract"]["independence_gap_samples"], 60)
            self.assertEqual(plan["sequential_stop_contract"]["success_min_independent_episodes"], 30)
            self.assertFalse(plan["sequential_stop_contract"]["automatic_long_run_transition"])
            self.assertTrue(plan["fail_closed_contract"]["thresholds_frozen_before_independent_short_probe"])

    def test_rejected_fast_output_cannot_build_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fast = _write_fast_output(root, ready=False)
            with self.assertRaises(ValueError):
                build_short_probe_plan(fast, root / "plan.json")

    def test_plan_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fast = _write_fast_output(root)
            output = root / "plan.json"
            build_short_probe_plan(fast, output)
            with self.assertRaises(FileExistsError):
                build_short_probe_plan(fast, output)


if __name__ == "__main__":
    unittest.main()
