from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from funding_pairs import (  # noqa: E402
    analyze_pairs,
    basis_stats,
    leg_annualized_pct,
    spread_stats,
)


class SpreadStatsTests(unittest.TestCase):
    def test_positive_spread_short_a(self) -> None:
        daily_a = {day: 0.0010 for day in range(0, 10)}
        daily_b = {day: 0.0002 for day in range(0, 10)}
        stats = spread_stats(daily_a, daily_b, 0, 9)
        assert stats is not None
        self.assertEqual(stats["aligned_days"], 10)
        self.assertAlmostEqual(stats["mean_daily_spread_bps"], 8.0)
        self.assertAlmostEqual(stats["annualized_spread_pct"], 0.0008 * 365 * 100, places=2)
        self.assertEqual(stats["direction"], "short_a_long_b")
        self.assertEqual(stats["sign_consistency"], 1.0)

    def test_negative_spread_short_b(self) -> None:
        daily_a = {0: 0.0001, 1: 0.0001}
        daily_b = {0: 0.0005, 1: 0.0005}
        stats = spread_stats(daily_a, daily_b, 0, 1)
        assert stats is not None
        self.assertEqual(stats["direction"], "short_b_long_a")
        self.assertGreater(stats["abs_annualized_spread_pct"], 0)

    def test_no_overlap_returns_none(self) -> None:
        self.assertIsNone(spread_stats({0: 0.1}, {5: 0.1}, 0, 1))

    def test_window_filter(self) -> None:
        daily_a = {day: 0.001 for day in range(0, 100)}
        daily_b = {day: 0.0 for day in range(0, 100)}
        stats = spread_stats(daily_a, daily_b, 90, 99)
        assert stats is not None
        self.assertEqual(stats["aligned_days"], 10)


class BasisStatsTests(unittest.TestCase):
    def test_basis_flat(self) -> None:
        closes_a = {day: 100.0 for day in range(0, 5)}
        closes_b = {day: 100.0 for day in range(0, 5)}
        stats = basis_stats(closes_a, closes_b, 0, 4)
        assert stats is not None
        self.assertEqual(stats["mean_basis_bps"], 0.0)
        self.assertEqual(stats["max_abs_basis_bps"], 0.0)

    def test_basis_deviation(self) -> None:
        closes_a = {0: 101.0, 1: 100.0}
        closes_b = {0: 100.0, 1: 100.0}
        stats = basis_stats(closes_a, closes_b, 0, 1)
        assert stats is not None
        self.assertAlmostEqual(stats["max_abs_basis_bps"], 100.0, places=1)

    def test_insufficient_days(self) -> None:
        self.assertIsNone(basis_stats({0: 1.0}, {0: 1.0}, 0, 0))


class LegAnnualizedTests(unittest.TestCase):
    def test_leg_annualized(self) -> None:
        daily = {day: 0.001 for day in range(0, 30)}
        self.assertAlmostEqual(leg_annualized_pct(daily, 0, 29), 36.5, places=1)

    def test_leg_insufficient(self) -> None:
        self.assertIsNone(leg_annualized_pct({0: 0.001}, 0, 0))


class PairAnalysisTests(unittest.TestCase):
    def test_non_binance_filter_and_full_costs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            evidence = Path(temp_dir) / "evidence"
            evidence.mkdir(parents=True)
            evidence.joinpath("mexc_spot_exchangeinfo.json").write_text(
                json.dumps(
                    {
                        "symbols": [
                            {"symbol": "AAAUSDT", "status": "1"},
                            {"symbol": "BBBUSDT", "status": "1"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            universe = []
            for exchange in ("mexc", "gateio"):
                for symbol, non_binance in (("AAA_USDT", True), ("BBB_USDT", False)):
                    universe.append(
                        {
                            "exchange": exchange,
                            "symbol": symbol,
                            "base": symbol.replace("_USDT", ""),
                            "volume_24h_quote": 1_000_000.0,
                            "non_binance_baseline": non_binance,
                        }
                    )
                    funding_dir = root / exchange / "funding"
                    kline_dir = root / exchange / "klines"
                    funding_dir.mkdir(parents=True, exist_ok=True)
                    kline_dir.mkdir(parents=True, exist_ok=True)
                    rate = 0.001 if exchange == "gateio" else 0.0002
                    funding_dir.joinpath(f"{symbol}.json").write_text(
                        json.dumps(
                            {
                                "rows": [
                                    {"ts": day * 86400, "funding_rate": rate}
                                    for day in range(1, 11)
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
                    kline_dir.joinpath(f"{symbol}.json").write_text(
                        json.dumps(
                            {
                                "rows": [
                                    {"ts": day * 86400, "close": 100.0}
                                    for day in range(1, 11)
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
            root.mkdir(parents=True, exist_ok=True)
            root.joinpath("manifest.json").write_text(
                json.dumps(
                    {
                        "params": {"end_sec": 11 * 86400},
                        "universe": universe,
                    }
                ),
                encoding="utf-8",
            )

            report = analyze_pairs(
                root,
                evidence,
                window_days=20,
                min_aligned_days=2,
            )

            self.assertEqual(report["schema"], "funding_pairs_v2")
            self.assertEqual(report["params"]["analysis_as_of_ts"], 11 * 86400)
            self.assertEqual(report["params"]["analysis_as_of_source"], "manifest.params.end_sec")
            self.assertEqual(report["shared_symbols_before_non_binance_filter"], 2)
            self.assertEqual(report["shared_symbols_total"], 1)
            self.assertEqual(report["pairs"][0]["symbol"], "AAA_USDT")
            economics = report["pairs"][0]["economics"]
            self.assertGreater(economics["cycle_cost"]["total_bps"], 0.0)
            self.assertLess(
                economics["net_abs_annualized_after_costs_pct"],
                economics["gross_abs_annualized_pct"],
            )


if __name__ == "__main__":
    unittest.main()
