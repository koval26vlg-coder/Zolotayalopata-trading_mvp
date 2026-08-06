from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_reconciliation_adapter import (  # noqa: E402
    DeterministicFixtureReconciliationAdapter,
    ReconciliationContract,
    SNAPSHOT_SCHEMA,
    reconcile_fixture_snapshot,
)


def _state(*, open_position: bool = True) -> dict:
    positions = {}
    if open_position:
        positions["A00"] = {
            "base": "A00",
            "long_venue": "mexc",
            "short_venue": "gateio",
        }
    return {"status": "OPEN" if open_position else "FLAT", "positions": positions}


def _snapshot(*, include_short: bool = True) -> dict:
    positions = [
        {
            "venue": "mexc",
            "base": "A00",
            "side": "LONG",
            "notional_quote": 500.0,
        }
    ]
    if include_short:
        positions.append(
            {
                "venue": "gateio",
                "base": "A00",
                "side": "SHORT",
                "notional_quote": 500.0,
            }
        )
    return {
        "schema": SNAPSHOT_SCHEMA,
        "observed_ts": 1_800_000_000,
        "balances": {
            "mexc": {"USDT": 2_000.0},
            "gateio": {"USDT": 2_000.0},
        },
        "positions": positions,
        "open_orders": [],
    }


class PaperReconciliationAdapterTests(unittest.TestCase):
    def test_matching_two_leg_fixture_is_read_only(self) -> None:
        state = _state()
        before = copy.deepcopy(state)
        provider = DeterministicFixtureReconciliationAdapter(_snapshot())
        result = reconcile_fixture_snapshot(
            state,
            provider,
            contract=ReconciliationContract(500.0),
        )
        self.assertEqual(result["verdict"], "MATCHED")
        self.assertFalse(result["kill_switch_required"])
        self.assertFalse(result["paper_state_mutated"])
        self.assertEqual(state, before)
        self.assertFalse(hasattr(provider, "place_order"))
        self.assertFalse(hasattr(provider, "cancel_order"))

    def test_missing_leg_requires_kill_switch(self) -> None:
        result = reconcile_fixture_snapshot(
            _state(),
            DeterministicFixtureReconciliationAdapter(_snapshot(include_short=False)),
            contract=ReconciliationContract(500.0),
        )
        self.assertEqual(result["verdict"], "RECONCILIATION_MISMATCH")
        self.assertTrue(result["kill_switch_required"])
        self.assertEqual(result["mismatches"][0]["type"], "missing_position_leg")

    def test_unexpected_order_and_notional_mismatch_are_reported(self) -> None:
        snapshot = _snapshot()
        snapshot["positions"][0]["notional_quote"] = 490.0
        snapshot["open_orders"].append(
            {"venue": "mexc", "base": "A00", "side": "BUY", "order_ref": "fixture"}
        )
        result = reconcile_fixture_snapshot(
            _state(),
            DeterministicFixtureReconciliationAdapter(snapshot),
            contract=ReconciliationContract(500.0, notional_tolerance_quote=1.0),
        )
        self.assertEqual(
            {row["type"] for row in result["mismatches"]},
            {"position_notional_mismatch", "unexpected_open_order"},
        )

    def test_flat_state_matches_empty_positions(self) -> None:
        snapshot = _snapshot()
        snapshot["positions"] = []
        result = reconcile_fixture_snapshot(
            _state(open_position=False),
            DeterministicFixtureReconciliationAdapter(snapshot),
            contract=ReconciliationContract(500.0),
        )
        self.assertTrue(result["matched"])

    def test_fixture_adapter_returns_defensive_copy(self) -> None:
        provider = DeterministicFixtureReconciliationAdapter(_snapshot())
        first = provider.read_snapshot()
        first["positions"].clear()
        self.assertEqual(len(provider.read_snapshot()["positions"]), 2)

    def test_duplicate_legs_and_invalid_balance_fail_closed(self) -> None:
        duplicate = _snapshot()
        duplicate["positions"].append(copy.deepcopy(duplicate["positions"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate position"):
            DeterministicFixtureReconciliationAdapter(duplicate)
        invalid = _snapshot()
        invalid["balances"]["mexc"]["USDT"] = -1
        with self.assertRaisesRegex(ValueError, "non-negative"):
            DeterministicFixtureReconciliationAdapter(invalid)


if __name__ == "__main__":
    unittest.main()
