from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from spot_perp_basis_history_v2 import (  # noqa: E402
    PREFLIGHT_DECISION_READY,
    PREFLIGHT_SCHEMA,
    assess_archive_availability,
    build_candidate_pool,
    build_gate_spot_perp_plan,
    required_archive_urls,
)


def _pit_row(base: str, *, eligible: bool = True, volume: float = 2_000_000.0) -> dict[str, object]:
    return {
        "exchange": "gateio",
        "symbol": f"{base}_USDT",
        "base": base,
        "quote": "USDT",
        "contract_type": "linear_perp",
        "status": "trading",
        "listed_now": True,
        "inactive_or_delisted": False,
        "tombstone": False,
        "eligible_non_binance_spot": eligible,
        "binance_spot_listed": not eligible,
        "volume_24h_quote": volume,
    }


class GateSpotPerpHistoryV2Tests(unittest.TestCase):
    def test_candidate_pool_requires_unique_identity_and_active_spot_perp(self) -> None:
        pit_state = {
            "schema": "pit_universe_state_v1",
            "symbols": {
                "gateio:HYPE_USDT": {"row": _pit_row("HYPE")},
                "gateio:STETH_USDT": {"row": _pit_row("STETH")},
                "gateio:COLLIDE_USDT": {"row": _pit_row("COLLIDE")},
                "gateio:BIN_USDT": {"row": _pit_row("BIN", eligible=False)},
                "gateio:XAU_USDT": {"row": _pit_row("XAU")},
                "gateio:LOBSTER_USDT": {"row": {**_pit_row("LOBSTER"), "base": "龙虾", "symbol": "龙虾_USDT"}},
            },
        }
        registry_rows = [
            {"rank": "9", "name": "Hyperliquid", "symbol": "HYPE", "coin_id": "hype-hyperliquid"},
            {"rank": "10", "name": "Lido Staked Ether", "symbol": "STETH", "coin_id": "steth"},
            {"rank": "100", "name": "Collision A", "symbol": "COLLIDE", "coin_id": "collision-a"},
            {"rank": "101", "name": "Collision B", "symbol": "COLLIDE", "coin_id": "collision-b"},
            {"rank": "20", "name": "Binance Listed", "symbol": "BIN", "coin_id": "bin"},
            {"rank": "21", "name": "Tokenized Gold", "symbol": "XAU", "coin_id": "tokenized-gold"},
            {"rank": "22", "name": "Lobster", "symbol": "龙虾", "coin_id": "lobster"},
        ]
        spot_pairs = [
            {"id": "HYPE_USDT", "base": "HYPE", "quote": "USDT", "trade_status": "tradable"},
            {"id": "STETH_USDT", "base": "STETH", "quote": "USDT", "trade_status": "tradable"},
            {"id": "COLLIDE_USDT", "base": "COLLIDE", "quote": "USDT", "trade_status": "tradable"},
            {"id": "XAU_USDT", "base": "XAU", "quote": "USDT", "trade_status": "tradable"},
        ]
        spot_tickers = [{"currency_pair": "HYPE_USDT", "quote_volume": "3000000"}]

        candidates, rejected = build_candidate_pool(
            pit_state=pit_state,
            registry_rows=registry_rows,
            gate_spot_pairs=spot_pairs,
            gate_spot_tickers=spot_tickers,
        )

        self.assertEqual([row["base"] for row in candidates], ["HYPE"])
        self.assertEqual(candidates[0]["canonical_asset_id"], "coingecko:hype-hyperliquid")
        self.assertEqual(candidates[0]["minimum_current_quote_volume"], 2_000_000.0)
        self.assertEqual(rejected["excluded_category"], 2)
        self.assertEqual(rejected["identity_collision"], 1)
        self.assertEqual(rejected["binance_spot_or_unverified"], 1)
        self.assertEqual(rejected["invalid_symbol"], 1)

    def test_archive_assessment_requires_every_series_at_oldest_month(self) -> None:
        candidates = [
            {
                "canonical_asset_id": f"coingecko:asset-{index}",
                "base": f"A{index}",
                "gate_spot_symbol": f"A{index}_USDT",
                "gate_perp_symbol": f"A{index}_USDT",
                "minimum_current_quote_volume": float(10_000_000 - index),
            }
            for index in range(3)
        ]
        statuses: dict[str, dict[str, object]] = {}
        for candidate in candidates:
            urls = required_archive_urls(candidate["base"], "202512")
            for name, url in urls.items():
                statuses[url] = {"status": 200, "content_length": 100, "series": name}
        missing_url = required_archive_urls("A2", "202512")["funding"]
        statuses[missing_url] = {"status": 404, "content_length": 0, "series": "funding"}

        result = assess_archive_availability(
            candidates,
            statuses,
            oldest_month="202512",
            minimum_assets=2,
        )

        self.assertEqual(result["decision"], PREFLIGHT_DECISION_READY)
        self.assertEqual([row["base"] for row in result["eligible_assets"]], ["A0", "A1"])
        self.assertEqual(result["rejected_by_reason"], {"archive_boundary_missing": 1})

    def test_plan_derives_threshold_from_gate_four_operation_stress_cost(self) -> None:
        eligible = [
            {
                "canonical_asset_id": f"coingecko:asset-{index}",
                "base": f"A{index}",
                "gate_spot_symbol": f"A{index}_USDT",
                "gate_perp_symbol": f"A{index}_USDT",
                "minimum_current_quote_volume": float(20_000_000 - index),
                "archive_boundary": {"all_required_series_present": True},
            }
            for index in range(8)
        ]
        preflight = {
            "schema": PREFLIGHT_SCHEMA,
            "final": True,
            "decision": PREFLIGHT_DECISION_READY,
            "eligible_assets": eligible,
            "prior_rejection_invalidation": {
                "invalidated": True,
                "reason": "gate_order_book_size_field_s_was_not_parsed",
            },
            "input_hashes": {"pit_state_sha256": "a" * 64, "registry_sha256": "b" * 64},
        }

        plan = build_gate_spot_perp_plan(preflight, max_runtime_sec=600)

        self.assertEqual(plan["hypothesis"]["venue"], "gateio")
        self.assertEqual(plan["strategy"]["direction"], "long_spot_short_perp_only")
        self.assertEqual(plan["strategy"]["entry_threshold_bps"], 132.0)
        self.assertEqual(plan["economics"]["stress_cycle_cost"]["fees_bps"], 40.0)
        self.assertTrue(plan["acceptance_gates"]["price_only_net_expectancy_positive"])
        self.assertFalse(plan["safety"]["grid_search"])
        self.assertFalse(plan["safety"]["live_orders"])
        self.assertEqual(plan["next_allowed_command"], "fast-edge-gate-spot-perp-history-collect")


if __name__ == "__main__":
    unittest.main()
