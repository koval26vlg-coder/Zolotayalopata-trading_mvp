from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pit_cross_venue_evidence_gap import build_evidence_gap_report  # noqa: E402


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _screen(cost_positive_events: int = 100) -> dict[str, object]:
    per_base = []
    if cost_positive_events:
        per_base = [
            {
                "base": "COLLISION",
                "evaluations": 200,
                "positive_gross_events": 100,
                "cost_positive_events": 90,
                "max_gross_edge_bps": 500_000.0,
                "max_net_screening_edge_bps": 499_931.0,
            },
            {
                "base": "POSSIBLE",
                "evaluations": 200,
                "positive_gross_events": 50,
                "cost_positive_events": 10,
                "max_gross_edge_bps": 90.0,
                "max_net_screening_edge_bps": 21.0,
            },
        ]
    return {
        "schema": "pit_linear_perp_cross_venue_screen_v1",
        "mode": "pit_linear_perp_cross_venue_screen_planonly",
        "decision": (
            "PIT_LINEAR_PERP_SCREEN_CANDIDATES_REQUIRE_DEEPER_EVIDENCE"
            if cost_positive_events
            else "PIT_LINEAR_PERP_SCREEN_REJECTED_NO_EDGE_AFTER_BASE_COSTS"
        ),
        "research_only": True,
        "screening_only": True,
        "accepted": False,
        "strategy_accepted": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "backtest_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_ready": False,
        "source": {"mask_sha256": "mask", "run_id": "run-1"},
        "instrument_scope": {
            "screened_contract_type": "linear_perp",
            "supports_spot_objective": False,
        },
        "spot_objective_verdict": "REJECTED_INSTRUMENT_MISMATCH_AND_PRIOR_NEGATIVE_SPOT_SCAN",
        "summary": {
            "source_rows": 1000,
            "retained_rows": 900,
            "retained_cycles_seen": 100,
            "matched_bases": len(per_base),
            "evaluations": 400 if per_base else 0,
            "positive_gross_events": 150 if per_base else 0,
            "cost_positive_events": cost_positive_events,
            "cost_positive_bases": len(per_base),
            "max_gross_edge_bps": 500_000.0 if per_base else 10.0,
            "max_net_screening_edge_bps": 499_931.0 if per_base else -59.0,
            "scan_complete": True,
        },
        "per_base": per_base,
        "evidence_gaps": [
            "contract_multiplier_and_spec_parity_not_verified",
            "bid_ask_quantity_and_executable_capacity_missing",
            "funding_rate_and_funding_pnl_missing",
        ],
    }


class PitCrossVenueEvidenceGapTests(unittest.TestCase):
    def test_blocks_raw_candidates_when_identity_depth_and_funding_are_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "screen.json"
            output = root / "gap.json"
            _write(source, _screen())

            report = build_evidence_gap_report(source, output)

            self.assertEqual(
                report["decision"],
                "PIT_LINEAR_PERP_SCREEN_EVIDENCE_GAP_BLOCKED_CONTRACT_IDENTITY_DEPTH_FUNDING",
            )
            self.assertEqual(report["raw_observations"]["cost_positive_events"], 100)
            self.assertEqual(report["validated_candidates"]["events"], 0)
            self.assertAlmostEqual(report["concentration"]["top_1_share"], 0.9)
            self.assertEqual(report["diagnostics"]["extreme_price_scale_bases"], ["COLLISION"])
            self.assertEqual(report["diagnostics"]["persistent_raw_positive_bases"], ["COLLISION"])
            self.assertFalse(report["strategy_accepted"])
            self.assertFalse(report["replay_allowed"])
            self.assertTrue(output.exists())

    def test_preserves_no_edge_rejection_without_requesting_more_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "screen.json"
            _write(source, _screen(0))

            report = build_evidence_gap_report(source, root / "gap.json")

            self.assertEqual(report["decision"], "PIT_LINEAR_PERP_SCREEN_EVIDENCE_GAP_REJECTED_NO_RAW_EDGE")
            self.assertEqual(report["validated_candidates"]["events"], 0)
            self.assertEqual(report["next_valid_move"], "select_new_structural_hypothesis_planonly")

    def test_rejects_unsafe_or_non_screen_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "screen.json"
            payload = _screen()
            payload["strategy_accepted"] = True
            _write(source, payload)

            with self.assertRaisesRegex(ValueError, "safety flags"):
                build_evidence_gap_report(source, root / "gap.json")


if __name__ == "__main__":
    unittest.main()
