from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_cross_venue_forward_plan import ForwardOosPlanConfig, build_forward_oos_plan  # noqa: E402


class PitCrossVenueForwardPlanTests(unittest.TestCase):
    def test_plan_seals_full_discovery_and_identity_universe_without_edge_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe = root / "probe.json"
            output = root / "plan.json"
            bases = ["AAA", "BBB", "CCC"]
            universe_sha = hashlib.sha256(
                json.dumps({"bases": bases}, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            probe.write_text(
                json.dumps(
                    {
                        "schema": "pit_linear_perp_cross_venue_forward_probe_v1",
                        "mode": "pit_linear_perp_cross_venue_forward_public_probe",
                        "decision": "PIT_LINEAR_PERP_FORWARD_PROBE_ACCEPTED_READY_FOR_OOS_APPROVAL_PACKET",
                        "strategy_accepted": False,
                        "collect_started": False,
                        "source": {"availability_sha256": "a" * 64},
                        "discovery_universe": {
                            "bases": bases,
                            "count": 3,
                            "sha256": universe_sha,
                        },
                        "summary": {
                            "provisional_identity_pairs": 2,
                            "fully_valid_pairs": 1,
                            "one_shot_cost_positive_pairs": 0,
                        },
                        "pairs": [
                            {"base": "AAA", "provisional_identity_match": True, "fully_valid": True},
                            {"base": "BBB", "provisional_identity_match": True, "fully_valid": False},
                            {"base": "CCC", "provisional_identity_match": False, "fully_valid": False},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cfg = ForwardOosPlanConfig(
                interval_sec=300,
                target_valid_cycles=10,
                min_active_span_sec=3_600,
                max_active_duration_sec=7_200,
                min_identity_pairs=2,
                min_valid_pair_coverage_ratio=0.5,
            )

            plan = build_forward_oos_plan(probe, output, cfg)

            self.assertEqual(plan["decision"], "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY")
            self.assertEqual(plan["sealed_universe"]["all_discovery_bases"], ["AAA", "BBB", "CCC"])
            self.assertEqual(plan["sealed_universe"]["identity_evaluation_bases"], ["AAA", "BBB"])
            self.assertEqual(plan["sealed_universe"]["identity_quarantine_bases"], ["CCC"])
            self.assertEqual(plan["collection_contract"]["min_valid_pairs_per_cycle"], 1)
            self.assertEqual(plan["probe_diagnostics"]["one_shot_cost_positive_pairs"], 0)
            self.assertFalse(plan["would_start"])
            self.assertFalse(plan["strategy_accepted"])
            self.assertTrue(plan["requires_explicit_user_approval_for_actual_collect"])
            self.assertTrue(output.is_file())

    def test_plan_rejects_unaccepted_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe = root / "probe.json"
            probe.write_text(
                json.dumps(
                    {
                        "schema": "pit_linear_perp_cross_venue_forward_probe_v1",
                        "mode": "pit_linear_perp_cross_venue_forward_public_probe",
                        "decision": "PIT_LINEAR_PERP_FORWARD_PROBE_REJECTED_INSUFFICIENT_IDENTITY_MATCHES",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "accepted probe"):
                build_forward_oos_plan(probe, root / "plan.json", ForwardOosPlanConfig(min_identity_pairs=1))


if __name__ == "__main__":
    unittest.main()
