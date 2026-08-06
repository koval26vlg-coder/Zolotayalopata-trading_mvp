from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from historical_basis_universe import (  # noqa: E402
    build_basis_universe_availability,
    classify_excluded_categories,
)


class FakeHistoryClient:
    def __init__(self, missing_symbols: set[str] | None = None) -> None:
        self.missing_symbols = missing_symbols or set()

    def fetch_5m_series(self, symbol: str, series: str, start_sec: int, end_sec: int):
        if symbol in self.missing_symbols:
            return []
        return [{"ts": float(start_sec), "open": 1.0, "close": 1.0, "volume_quote": 2_000_000.0}]


class RetentionLimitedHistoryClient(FakeHistoryClient):
    def fetch_5m_series(self, symbol: str, series: str, start_sec: int, end_sec: int):
        raise RuntimeError("gateio:5m:maximum_recent_points=10000")


def _write_inputs(root: Path, *, count: int = 12, duplicate_symbol: bool = False) -> tuple[Path, Path]:
    registry = root / "coins.csv"
    rows = [
        {
            "rank": str(index + 1),
            "name": f"Asset {index}",
            "symbol": f"A{index}",
            "coin_id": f"asset-{index}",
            "market_cap_usd": "1000000",
            "price_usd": "1",
        }
        for index in range(count)
    ]
    if duplicate_symbol:
        rows.append({**rows[0], "coin_id": "asset-collision", "name": "Collision"})
    with registry.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    symbols: dict[str, object] = {}
    for index in range(count):
        base = f"A{index}"
        for exchange in ("mexc", "gateio"):
            symbol = f"{base}_USDT"
            symbols[f"{exchange}|{symbol}"] = {
                "row": {
                    "exchange": exchange,
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "contract_type": "linear_perp",
                    "status": "trading",
                    "listed_now": True,
                    "tombstone": False,
                    "eligible_non_binance_spot": True,
                    "binance_spot_listed": False,
                    "volume_24h_quote": 5_000_000.0 - index,
                    "spread_bps": 2.0,
                }
            }
    pit = root / "universe_state.json"
    pit.write_text(json.dumps({"schema": "pit_universe_state_v1", "symbols": symbols}), encoding="utf-8")
    return pit, registry


class HistoricalBasisUniverseTests(unittest.TestCase):
    def test_category_classifier_blocks_structural_non_crypto_assets(self) -> None:
        self.assertIn("wrapped", classify_excluded_categories("Wrapped Ether", "WETH", "weth"))
        self.assertIn("staked", classify_excluded_categories("Lido Staked Ether", "STETH", "steth"))
        self.assertIn("tokenized", classify_excluded_categories("Tesla Tokenized Stock", "TSLASTOCK", "tsla"))
        self.assertEqual(classify_excluded_categories("Hyperliquid", "HYPE", "hype-hyperliquid"), [])

    def test_builder_confirms_identity_and_all_six_boundary_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pit, registry = _write_inputs(root)
            output = root / "universe.json"
            result = build_basis_universe_availability(
                pit,
                registry,
                output,
                clients={"mexc": FakeHistoryClient(), "gateio": FakeHistoryClient()},
                now_sec=220 * 86_400 + 3_600,
                max_runtime_sec=60,
            )
            self.assertEqual(result["decision"], "READY_FOR_BASIS_PLAN")
            self.assertEqual(len(result["assets"]), 12)
            self.assertTrue(all(row["common_history_days"] == 220 for row in result["assets"]))
            self.assertTrue(all(row["canonical_asset_id"].startswith("coingecko:") for row in result["assets"]))
            self.assertEqual(result["history_probe"]["required_series_count_per_asset"], 6)

    def test_identity_collision_and_missing_history_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pit, registry = _write_inputs(root, count=9, duplicate_symbol=True)
            output = root / "universe.json"
            missing = {"A1_USDT"}
            result = build_basis_universe_availability(
                pit,
                registry,
                output,
                clients={"mexc": FakeHistoryClient(missing), "gateio": FakeHistoryClient()},
                now_sec=220 * 86_400 + 3_600,
                max_runtime_sec=60,
            )
            self.assertEqual(result["decision"], "INSUFFICIENT_EXECUTABLE_UNIVERSE")
            self.assertEqual(len(result["assets"]), 7)
            self.assertGreaterEqual(result["rejections_by_reason"]["identity_collision"], 1)
            self.assertGreaterEqual(result["rejections_by_reason"]["history_boundary_missing"], 1)

    def test_history_api_retention_limit_is_insufficient_data_not_universe_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pit, registry = _write_inputs(root, count=9)
            output = root / "universe.json"
            result = build_basis_universe_availability(
                pit,
                registry,
                output,
                clients={"mexc": FakeHistoryClient(), "gateio": RetentionLimitedHistoryClient()},
                now_sec=220 * 86_400 + 3_600,
                max_runtime_sec=60,
            )

            self.assertEqual(result["decision"], "INSUFFICIENT_DATA")
            self.assertEqual(result["rejections_by_reason"]["history_api_retention_limit"], 9)
            self.assertEqual(result["next_allowed_command"], "close-hypothesis-insufficient-history-api-retention")


if __name__ == "__main__":
    unittest.main()
