from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import autopilot_same_scope_strategy_census as census  # noqa: E402


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _prior(path: Path) -> Path:
    return _write(
        path,
        {
            "schema": census.PRIOR_CENSUS_SCHEMA,
            "terminally_closed": [{"family": "closed-a"}] * 3,
            "materially_distinct_candidate_review": [
                {
                    "candidate": "candidate-a",
                    "selected": False,
                    "reason": "needs new data",
                }
            ],
            "selected_candidate": None,
        },
    )


def _basis(path: Path) -> Path:
    return _write(
        path,
        {
            "schema": census.BASIS_CURRENTNESS_SCHEMA,
            "status": "PASS_BRANCHES_REMAIN_TERMINAL",
            "terminal_reports": [{}, {}],
            "safety": {
                "network_access": False,
                "collector_started": False,
                "market_rows_read": False,
                "returns_read": False,
                "pnl_read": False,
                "oos_run": False,
                "grid_or_retune": False,
                "source_or_contract_mutated": False,
            },
        },
    )


def _guard(path: Path) -> Path:
    return _write(
        path,
        {
            "schema": census.GUARD_SCHEMA,
            "status": "ACTIVE",
            "stop_new_actions": False,
            "schedule_window": {
                "classification": "PREAPPROVED_SHORT_SEGMENT",
                "data_type": "PIT_UNIVERSE_V2_FORWARD",
                "run_id": "pit-n13",
                "accepted_distinct_dates": 8,
                "stage_target_distinct_dates": 20,
            },
            "long_campaign_approval": {
                "launch_window_status": "EXPIRED"
            },
            "long_campaign_candidate": {"campaign_id": "dense-old"},
        },
    )


class SameScopeStrategyCensusTests(unittest.TestCase):
    def test_reports_no_honest_alternative_without_reading_market_data(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = census.build_strategy_census(
                prior_census_path=_prior(root / "prior.json"),
                basis_currentness_path=_basis(root / "basis.json"),
                guard_snapshot_path=_guard(root / "guard.json"),
                generated_at_utc="2026-08-09T17:00:00+00:00",
            )
        pit = result["current_routes"][
            "pit_universe_membership_drift_reversion_v1"
        ]
        self.assertEqual(pit["accepted_distinct_dates"], 8)
        self.assertEqual(pit["dates_remaining"], 12)
        self.assertIsNone(result["selected_candidate"])
        self.assertEqual(
            result["verdict"],
            "NO_ALTERNATIVE_STRATEGY_CAN_BE_HONESTLY_TESTED_ON_CURRENT_IMMUTABLE_DATA",
        )
        self.assertFalse(result["safety"]["market_rows_read"])
        self.assertFalse(result["safety"]["returns_read"])

    def test_rejects_unsafe_basis_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            basis_path = _basis(root / "basis.json")
            payload = json.loads(basis_path.read_text(encoding="utf-8"))
            payload["safety"]["returns_read"] = True
            basis_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "safety boundary"):
                census.build_strategy_census(
                    prior_census_path=_prior(root / "prior.json"),
                    basis_currentness_path=basis_path,
                    guard_snapshot_path=_guard(root / "guard.json"),
                )


if __name__ == "__main__":
    unittest.main()
