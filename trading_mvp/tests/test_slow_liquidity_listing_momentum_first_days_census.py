from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
import slow_liquidity_listing_momentum_first_days_census as census  # noqa: E402


HOUR = 3600
PROXY_TS = 1_700_000_640 - (1_700_000_640 % HOUR)


def synthetic_rows(
    base: str,
    exchange: str = "mexc",
    n_bars: int = 72,
    open_price: float = 1.0,
    drift: float = 0.0,
) -> list[dict]:
    rows = []
    price = open_price
    for index in range(n_bars):
        close = price * (1.0 + drift)
        rows.append(
            {
                "run_id": "synthetic",
                "exchange": exchange,
                "base": base,
                "symbol": f"{base}USDT",
                "granularity": "1h",
                "ts": PROXY_TS + index * HOUR,
                "open": price,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 10.0 + index,
                "proxy_event_ts": PROXY_TS,
                "window_role": "first_days",
            }
        )
        price = close
    return rows


def synthetic_bindings(
    jobs: list[dict], rows: list[dict]
) -> dict:
    return {
        "plan": {"plan_hash": "synthetic"},
        "manifest": {
            "run_id": "synthetic",
            "status": "COMPLETED",
            "plan_hash": "synthetic",
            "finished_at_utc": "2026-08-16T18:54:53Z",
            "rows_written": len(rows),
            "jobs": jobs,
        },
        "rows": rows,
        "output_sha256": "0" * 64,
    }


class ComputeWindowStatsTests(unittest.TestCase):
    def test_stats_of_flat_window(self) -> None:
        stats = census.compute_window_stats(synthetic_rows("AAA", drift=0.0))
        self.assertEqual(stats["n_bars"], 72)
        self.assertAlmostEqual(stats["ret_72h"], 0.0)
        self.assertAlmostEqual(stats["ret_24h"], 0.0)
        self.assertAlmostEqual(stats["max_runup"], 0.01, places=6)
        self.assertAlmostEqual(stats["max_drawdown"], -0.01, places=6)
        self.assertGreaterEqual(stats["logret_1h_std"], 0.0)
        self.assertAlmostEqual(stats["base_volume_sum"], sum(10.0 + i for i in range(72)))

    def test_stats_of_trending_window(self) -> None:
        stats = census.compute_window_stats(synthetic_rows("BBB", drift=0.01))
        self.assertAlmostEqual(stats["ret_72h"], 1.01**72 - 1, places=4)
        self.assertAlmostEqual(stats["ret_24h"], 1.01**24 - 1, places=4)
        # constant per-bar drift means constant log returns: zero dispersion
        self.assertAlmostEqual(stats["logret_1h_std"], 0.0, places=8)

    def test_stats_of_volatile_window(self) -> None:
        rows = synthetic_rows("CCC", n_bars=6)
        closes = [1.0, 1.1, 0.9, 1.2, 0.8, 1.15]
        for row, close in zip(rows, closes):
            row["close"] = close
        stats = census.compute_window_stats(rows)
        self.assertGreater(stats["logret_1h_std"], 0.0)

    def test_empty_window(self) -> None:
        self.assertEqual(census.compute_window_stats([]), {"n_bars": 0})


class BuildCensusPayloadTests(unittest.TestCase):
    def test_primary_flagging_and_reconciliation(self) -> None:
        jobs = [
            {"exchange": "mexc", "base": "AAA", "proxy_ts": PROXY_TS, "flags": []},
            {
                "exchange": "gateio",
                "base": "BBB",
                "proxy_ts": PROXY_TS,
                "flags": ["request_error"],
            },
            {
                "exchange": "mexc",
                "base": "CCC",
                "proxy_ts": PROXY_TS,
                "flags": ["history_truncated"],
            },
            {
                "exchange": "mexc",
                "base": "DDD",
                "proxy_ts": PROXY_TS,
                "flags": ["no_data"],
            },
        ]
        rows = synthetic_rows("AAA") + synthetic_rows(
            "CCC", n_bars=20
        )
        payload = census.build_census_payload(synthetic_bindings(jobs, rows))
        census.validate_census_payload(payload)
        self.assertEqual(payload["window_counts"]["total_windows"], 4)
        self.assertEqual(payload["window_counts"]["primary_windows"], 1)
        self.assertEqual(
            payload["window_counts"]["flag_reconciliation"],
            {"clean": 1, "request_error": 1, "history_truncated": 1, "no_data": 1},
        )
        self.assertEqual(payload["acceptance_decision"], "NONE_DESCRIPTIVE_ONLY")
        by_base = {w["base"]: w for w in payload["windows"]}
        self.assertTrue(by_base["AAA"]["primary"])
        self.assertFalse(by_base["CCC"]["primary"])
        self.assertEqual(by_base["DDD"]["stats"]["n_bars"], 0)
        self.assertEqual(payload["primary_stats_all"]["windows"], 1)

    def test_year_bucketing(self) -> None:
        import datetime as dt

        old_ts = int(
            dt.datetime(2018, 6, 1, tzinfo=dt.timezone.utc).timestamp()
        )
        jobs = [
            {"exchange": "mexc", "base": "OLD", "proxy_ts": old_ts, "flags": []},
        ]
        rows = synthetic_rows("OLD")
        payload = census.build_census_payload(synthetic_bindings(jobs, rows))
        self.assertEqual(
            payload["windows"][0]["listing_year_bucket"], "le_2019"
        )
        self.assertIn(
            "le_2019", payload["primary_stats_by_listing_year_bucket"]
        )

    def test_determinism(self) -> None:
        jobs = [{"exchange": "mexc", "base": "AAA", "proxy_ts": PROXY_TS, "flags": []}]
        rows = synthetic_rows("AAA")
        first = census.build_census_payload(synthetic_bindings(jobs, rows))
        second = census.build_census_payload(synthetic_bindings(jobs, rows))
        self.assertEqual(first["census_hash"], second["census_hash"])

    def test_acceptance_decision_in_payload_is_rejected(self) -> None:
        jobs = [{"exchange": "mexc", "base": "AAA", "proxy_ts": PROXY_TS, "flags": []}]
        payload = census.build_census_payload(synthetic_bindings(jobs, synthetic_rows("AAA")))
        payload["acceptance_decision"] = "ACCEPT"
        payload["census_hash"] = canonical_hash(payload)
        with self.assertRaisesRegex(census.FirstDaysCensusError, "acceptance"):
            census.validate_census_payload(payload)


class RealDataCensusTests(unittest.TestCase):
    def test_real_collect_census_builds_and_reconciles(self) -> None:
        if not census.OUTPUT_JSONL.is_file():
            self.skipTest("real collect output not present on this machine")
        bindings = census.load_collect_bindings()
        payload = census.build_census_payload(bindings)
        census.validate_census_payload(payload)
        counts = payload["window_counts"]
        self.assertEqual(counts["total_windows"], 795)
        self.assertEqual(counts["primary_windows"], 363)
        self.assertEqual(counts["primary_by_venue"], {"gateio": 5, "mexc": 358})
        self.assertEqual(counts["flag_reconciliation"]["request_error"], 426)
        self.assertEqual(counts["flag_reconciliation"]["no_data"], 3)
        self.assertEqual(counts["flag_reconciliation"]["history_truncated"], 3)
        self.assertEqual(counts["flag_reconciliation"]["short_window"], 3)

    def test_real_census_on_disk_matches_rebuild(self) -> None:
        if not census.CENSUS_PATH.is_file():
            self.skipTest("census artifact not yet written")
        on_disk = json.loads(census.CENSUS_PATH.read_text(encoding="utf-8"))
        rebuilt = census.build_census_payload(census.load_collect_bindings())
        self.assertEqual(on_disk["census_hash"], rebuilt["census_hash"])


if __name__ == "__main__":
    unittest.main()
