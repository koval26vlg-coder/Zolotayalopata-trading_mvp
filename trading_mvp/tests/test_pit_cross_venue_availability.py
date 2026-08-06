from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pit_cross_venue_availability import build_availability_report  # noqa: E402


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class PitCrossVenueAvailabilityTests(unittest.TestCase):
    def _fixtures(self, root: Path) -> tuple[Path, Path, Path]:
        screen = root / "screen.json"
        gap = root / "gap.json"
        fees = root / "fees"
        fees.mkdir()
        _write(
            screen,
            {
                "schema": "pit_linear_perp_cross_venue_screen_v1",
                "mode": "pit_linear_perp_cross_venue_screen_planonly",
                "decision": "PIT_LINEAR_PERP_SCREEN_CANDIDATES_REQUIRE_DEEPER_EVIDENCE",
                "strategy_accepted": False,
                "replay_allowed": False,
                "oos_ready": False,
                "source": {"run_id": "run-1", "mask_sha256": "mask"},
                "time_span": {"start_utc": "2026-07-10T00:00:00+00:00", "end_utc": "2026-07-11T00:00:00+00:00"},
                "summary": {"cost_positive_events": 10, "cost_positive_bases": 2},
                "per_base": [
                    {"base": "AAA", "cost_positive_events": 8},
                    {"base": "BBB", "cost_positive_events": 2},
                ],
                "evidence_gaps": [
                    "bid_ask_quantity_and_executable_capacity_missing",
                    "contract_multiplier_and_spec_parity_not_verified",
                    "exchange_quote_timestamps_and_subsecond_staleness_missing",
                    "funding_rate_and_funding_pnl_missing",
                ],
            },
        )
        _write(
            gap,
            {
                "schema": "pit_linear_perp_cross_venue_evidence_gap_v1",
                "mode": "pit_linear_perp_cross_venue_evidence_gap_planonly",
                "decision": "PIT_LINEAR_PERP_SCREEN_EVIDENCE_GAP_BLOCKED_CONTRACT_IDENTITY_DEPTH_FUNDING",
                "strategy_accepted": False,
                "replay_allowed": False,
                "oos_ready": False,
                "raw_observations": {"cost_positive_events": 10},
                "validated_candidates": {"events": 0, "bases": 0},
                "next_valid_move": "build_public_contract_identity_depth_funding_availability_preflight_planonly",
            },
        )
        _write(
            fees / "mexc_contract_detail.json",
            {"data": [{"symbol": "AAA_USDT", "contractSize": "10"}]},
        )
        _write(
            fees / "gate_usdt_contracts.json",
            [{"name": "AAA_USDT", "quanto_multiplier": "10"}],
        )
        return screen, gap, fees

    def test_rejects_current_dataset_even_when_static_metadata_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screen, gap, fees = self._fixtures(root)

            report = build_availability_report(screen, gap, fees, root / "availability.json")

            self.assertEqual(
                report["decision"],
                "PIT_LINEAR_PERP_CURRENT_DATASET_REJECTED_FOR_EDGE_VALIDATION_MISSING_HISTORICAL_EVIDENCE",
            )
            self.assertEqual(report["metadata_coverage"]["both_venues_bases"], ["AAA"])
            self.assertEqual(report["metadata_coverage"]["missing_any_venue_bases"], ["BBB"])
            self.assertFalse(report["historical_retrofit_possible"])
            self.assertFalse(report["oos_ready"])
            self.assertFalse(report["strategy_accepted"])
            self.assertEqual(report["validated_candidates"]["events"], 0)

    def test_missing_metadata_files_fail_closed_but_still_produce_planonly_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screen, gap, _ = self._fixtures(root)
            missing = root / "missing-fees"

            report = build_availability_report(screen, gap, missing, root / "availability.json")

            self.assertFalse(report["static_metadata"]["available"])
            self.assertEqual(report["metadata_coverage"]["both_venues_bases"], [])
            self.assertEqual(report["validated_candidates"]["events"], 0)

    def test_rejects_gap_report_that_does_not_preserve_safety_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screen, gap, fees = self._fixtures(root)
            payload = json.loads(gap.read_text(encoding="utf-8"))
            payload["replay_allowed"] = True
            _write(gap, payload)

            with self.assertRaisesRegex(ValueError, "evidence-gap safety"):
                build_availability_report(screen, gap, fees, root / "availability.json")


if __name__ == "__main__":
    unittest.main()
