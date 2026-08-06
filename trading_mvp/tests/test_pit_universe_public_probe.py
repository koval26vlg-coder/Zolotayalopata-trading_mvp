from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_universe_public_probe import (  # noqa: E402
    ACCEPTED_DECISION,
    PLAN_DECISION,
    REJECTED_DECISION,
    build_plan_report,
    gate_ticker_map,
    mexc_ticker_map,
    parse_binance_spot_symbols,
    parse_gate_contract_rows,
    parse_mexc_contract_rows,
    annotate_binance_spot_membership,
    summarize_mexc_depth_coverage,
    summarize_rows,
)
import pit_universe_public_probe as probe_module  # noqa: E402


def mexc_contract_payload() -> dict[str, object]:
    return {
        "success": True,
        "data": [
            {
                "symbol": "HYPE_USDT",
                "baseCoin": "HYPE",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "state": 0,
                "apiAllowed": True,
                "contractSize": "0.1",
                "minVol": "1",
                "maxVol": "100000",
                "priceUnit": "0.001",
                "volUnit": "1",
            },
            {
                "symbol": "OLD_USDT",
                "baseCoin": "OLD",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "state": 3,
                "apiAllowed": False,
            },
            {
                "symbol": "BTC_USD",
                "baseCoin": "BTC",
                "quoteCoin": "USD",
                "settleCoin": "USD",
                "state": 0,
            },
        ],
    }


def gate_contract_payload() -> list[dict[str, object]]:
    return [
        {
            "name": "HYPE_USDT",
            "status": "trading",
            "quanto_multiplier": "0.01",
            "order_size_min": "1",
            "order_size_max": "100000",
            "order_price_round": "0.001",
            "funding_interval": 28800,
            "funding_next_apply": 1_800_000_000,
            "funding_rate": "0.0002",
        },
        {"name": "OLD_USDT", "status": "delisting"},
        {"name": "BTC_USD", "status": "trading"},
    ]


class PitUniversePublicProbeTests(unittest.TestCase):
    def test_plan_report_never_starts_network_or_collect(self) -> None:
        report = build_plan_report(output_path=Path("probe.json"), min_contracts_per_exchange=10)

        self.assertEqual(report["decision"], PLAN_DECISION)
        self.assertFalse(report["would_start"])
        self.assertFalse(report["live_orders"])
        self.assertFalse(report["api_keys"])
        self.assertFalse(report["collect_allowed_now"])
        self.assertFalse(report["replay_allowed_now"])

    def test_ticker_maps_normalize_symbol_keys(self) -> None:
        mexc = mexc_ticker_map({"data": [{"symbol": "hype_usdt", "amount24": "123"}]})
        gate = gate_ticker_map([{"contract": "hype_usdt", "volume_24h_settle": "456"}])

        self.assertIn("HYPE_USDT", mexc)
        self.assertIn("HYPE_USDT", gate)

    def test_parse_mexc_contract_rows_preserves_inactive_rows(self) -> None:
        rows = parse_mexc_contract_rows(
            mexc_contract_payload(),
            {"HYPE_USDT": {"amount24": "1000"}, "OLD_USDT": {"amount24": "10"}},
            "2026-07-09T00:00:00+00:00",
        )

        self.assertEqual(len(rows), 2)
        hype = rows[0]
        old = rows[1]
        self.assertEqual(hype["exchange"], "mexc")
        self.assertEqual(hype["base"], "HYPE")
        self.assertTrue(hype["listed_now"])
        self.assertFalse(hype["inactive_or_delisted"])
        self.assertEqual(hype["volume_24h_quote"], 1000.0)
        self.assertEqual(hype["contract_multiplier"], 0.1)
        self.assertEqual(hype["minimum_order_size"], 1.0)
        self.assertEqual(hype["bid_price"], None)
        self.assertEqual(hype["ask_price"], None)
        self.assertIsNone(hype["first_seen_ts"])
        self.assertFalse(old["listed_now"])
        self.assertTrue(old["inactive_or_delisted"])

    def test_parse_gate_contract_rows_preserves_inactive_rows(self) -> None:
        rows = parse_gate_contract_rows(
            gate_contract_payload(),
            {"HYPE_USDT": {"volume_24h_settle": "1000"}, "OLD_USDT": {"volume_24h_quote": "10"}},
            "2026-07-09T00:00:00+00:00",
        )

        self.assertEqual(len(rows), 2)
        hype = rows[0]
        old = rows[1]
        self.assertEqual(hype["exchange"], "gateio")
        self.assertEqual(hype["base"], "HYPE")
        self.assertTrue(hype["listed_now"])
        self.assertFalse(hype["inactive_or_delisted"])
        self.assertEqual(hype["volume_24h_quote"], 1000.0)
        self.assertEqual(hype["contract_multiplier"], 0.01)
        self.assertEqual(hype["funding_rate"], 0.0002)
        self.assertEqual(hype["funding_interval_sec"], 28800)
        self.assertEqual(old["status"], "delisting")
        self.assertTrue(old["inactive_or_delisted"])

    def test_parsers_calculate_ticker_bbo_spread_proxy(self) -> None:
        mexc_rows = parse_mexc_contract_rows(
            mexc_contract_payload(),
            {
                "HYPE_USDT": {
                    "amount24": "1000",
                    "bid1": "9.99",
                    "ask1": "10.01",
                    "fundingRate": "0.0003",
                    "fairPrice": "10.00",
                    "indexPrice": "9.98",
                }
            },
            "2026-07-09T00:00:00+00:00",
        )
        gate_rows = parse_gate_contract_rows(
            gate_contract_payload(),
            {
                "HYPE_USDT": {
                    "volume_24h_settle": "1000",
                    "highest_bid": "9.99",
                    "highest_size": "25",
                    "lowest_ask": "10.01",
                    "lowest_size": "30",
                    "funding_rate": "0.0004",
                    "mark_price": "10.00",
                    "index_price": "9.98",
                }
            },
            "2026-07-09T00:00:00+00:00",
        )

        for row in (mexc_rows[0], gate_rows[0]):
            self.assertAlmostEqual(row["mid_price"], 10.0)
            self.assertAlmostEqual(row["spread_bps"], 20.0)
            self.assertEqual(row["liquidity_proxy_source"], "ticker_bbo_and_24h_quote_volume")
        self.assertEqual(mexc_rows[0]["funding_rate"], 0.0003)
        self.assertEqual(mexc_rows[0]["mark_price"], 10.0)
        self.assertEqual(gate_rows[0]["funding_rate"], 0.0004)
        self.assertEqual(gate_rows[0]["bid_size_contracts"], 25.0)
        self.assertEqual(gate_rows[0]["ask_size_contracts"], 30.0)

    def test_binance_reference_marks_but_does_not_drop_contract_rows(self) -> None:
        symbols = parse_binance_spot_symbols(
            {
                "symbols": [
                    {"symbol": "HYPEUSDT", "baseAsset": "HYPE", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
                    {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT", "status": "BREAK", "isSpotTradingAllowed": True},
                ]
            }
        )
        rows = parse_mexc_contract_rows(
            mexc_contract_payload(),
            {"HYPE_USDT": {"amount24": "1000"}, "OLD_USDT": {"amount24": "10"}},
            "2026-07-09T00:00:00+00:00",
        )

        annotated = annotate_binance_spot_membership(rows, symbols, "2026-07-09T00:00:01+00:00")

        self.assertEqual(len(annotated), 2)
        self.assertTrue(annotated[0]["binance_spot_listed"])
        self.assertTrue(annotated[0]["excluded_by_binance_spot"])
        self.assertFalse(annotated[0]["eligible_non_binance_spot"])
        self.assertFalse(annotated[1]["binance_spot_listed"])
        self.assertTrue(annotated[1]["eligible_non_binance_spot"])

    def test_mexc_depth_enrichment_targets_only_dual_venue_non_binance_contracts(self) -> None:
        enrich = getattr(probe_module, "enrich_mexc_depth", None)
        self.assertIsNotNone(enrich)
        assert enrich is not None
        rows = [
            {
                "exchange": "mexc",
                "symbol": "HYPE_USDT",
                "base": "HYPE",
                "quote": "USDT",
                "listed_now": True,
                "eligible_non_binance_spot": True,
                "bid_price": 9.98,
                "ask_price": 10.02,
            },
            {
                "exchange": "gateio",
                "symbol": "HYPE_USDT",
                "base": "HYPE",
                "quote": "USDT",
                "listed_now": True,
                "eligible_non_binance_spot": True,
                "bid_price": 9.99,
                "ask_price": 10.01,
            },
            {
                "exchange": "mexc",
                "symbol": "SOLO_USDT",
                "base": "SOLO",
                "quote": "USDT",
                "listed_now": True,
                "eligible_non_binance_spot": True,
                "bid_price": 1.0,
                "ask_price": 1.01,
            },
        ]
        requested: list[str] = []

        def fetch_depth(symbol: str) -> dict[str, object]:
            requested.append(symbol)
            return {
                "success": True,
                "data": {
                    "bids": [["9.99", "25", 1]],
                    "asks": [["10.01", "30", 1]],
                    "timestamp": 1_800_000_000_000,
                },
            }

        enriched, errors = enrich(rows, fetch_depth=fetch_depth, pace_sec=0.0)

        self.assertEqual(requested, ["HYPE_USDT"])
        self.assertEqual(errors, {})
        hype = next(row for row in enriched if row["exchange"] == "mexc" and row["base"] == "HYPE")
        solo = next(row for row in enriched if row["exchange"] == "mexc" and row["base"] == "SOLO")
        self.assertEqual(hype["bid_price"], 9.99)
        self.assertEqual(hype["ask_price"], 10.01)
        self.assertEqual(hype["bid_size_contracts"], 25.0)
        self.assertEqual(hype["ask_size_contracts"], 30.0)
        self.assertEqual(hype["liquidity_proxy_source"], "mexc_rest_depth_l1")
        self.assertEqual(hype["depth_snapshot_ts_ms"], 1_800_000_000_000)
        self.assertIsNone(solo.get("bid_size_contracts"))

    def test_mexc_depth_enrichment_stops_at_runtime_budget(self) -> None:
        enrich = getattr(probe_module, "enrich_mexc_depth")
        rows = [
            {
                "exchange": "mexc",
                "symbol": "HYPE_USDT",
                "base": "HYPE",
                "listed_now": True,
                "eligible_non_binance_spot": True,
            },
            {
                "exchange": "gateio",
                "symbol": "HYPE_USDT",
                "base": "HYPE",
                "listed_now": True,
                "eligible_non_binance_spot": True,
            },
        ]

        enriched, errors = enrich(
            rows,
            fetch_depth=lambda _symbol: self.fail("depth request must not run after budget exhaustion"),
            pace_sec=0.0,
            max_runtime_sec=0.0,
        )

        self.assertEqual(len(enriched), 2)
        self.assertIn("depth_enrichment_budget_exhausted", errors["HYPE_USDT"])

    def test_mexc_depth_enrichment_pipelines_latency_with_bounded_workers(self) -> None:
        enrich = getattr(probe_module, "enrich_mexc_depth")
        rows: list[dict[str, object]] = []
        for index in range(8):
            base = f"COIN{index}"
            rows.extend(
                [
                    {
                        "exchange": "mexc",
                        "symbol": f"{base}_USDT",
                        "base": base,
                        "listed_now": True,
                        "eligible_non_binance_spot": True,
                    },
                    {
                        "exchange": "gateio",
                        "symbol": f"{base}_USDT",
                        "base": base,
                        "listed_now": True,
                        "eligible_non_binance_spot": True,
                    },
                ]
            )

        lock = threading.Lock()
        active = 0
        max_active = 0

        def fetch_depth(_symbol: str) -> dict[str, object]:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.03)
                return {
                    "success": True,
                    "data": {
                        "bids": [["9.99", "25", 1]],
                        "asks": [["10.01", "30", 1]],
                        "timestamp": 1_800_000_000_000,
                    },
                }
            finally:
                with lock:
                    active -= 1

        enriched, errors = enrich(
            rows,
            fetch_depth=fetch_depth,
            pace_sec=0.0,
            max_runtime_sec=1.0,
            max_workers=4,
        )

        self.assertEqual(errors, {})
        self.assertGreater(max_active, 1)
        self.assertLessEqual(max_active, 4)
        mexc_rows = [row for row in enriched if row["exchange"] == "mexc"]
        self.assertEqual(len(mexc_rows), 8)
        self.assertTrue(all(row["bid_size_contracts"] == 25.0 for row in mexc_rows))
        self.assertTrue(all(row["ask_size_contracts"] == 30.0 for row in mexc_rows))

    def test_mexc_depth_default_rate_policy_is_conservative_and_reported(self) -> None:
        self.assertEqual(probe_module.MEXC_DEPTH_REQUEST_INTERVAL_SEC, 0.25)
        self.assertEqual(probe_module.MEXC_DEPTH_MAX_WORKERS, 3)

        class FailingSession:
            trust_env = False

            def get(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError("offline fixture")

        with (
            patch.object(probe_module.requests, "Session", return_value=FailingSession()),
            patch.object(probe_module, "summarize_rows", return_value={"accepted": True}),
            patch.object(
                probe_module,
                "summarize_mexc_depth_coverage",
                return_value={
                    "targets": 1,
                    "complete": 1,
                    "missing": 0,
                    "coverage": 1.0,
                    "minimum_required_coverage": 0.95,
                },
            ),
        ):
            report = probe_module.run_public_probe(
                output_path=None,
                min_contracts_per_exchange=1,
                timeout_sec=1,
                include_mexc_depth=False,
            )

        self.assertEqual(report["params"]["mexc_depth_request_interval_sec"], 0.25)
        self.assertEqual(report["params"]["mexc_depth_max_workers"], 3)

    def test_summarize_rows_requires_min_contracts_and_volume(self) -> None:
        rows = []
        rows.extend(
            parse_mexc_contract_rows(
                mexc_contract_payload(),
                {"HYPE_USDT": {"amount24": "1000"}, "OLD_USDT": {"amount24": "10"}},
                "2026-07-09T00:00:00+00:00",
            )
        )
        rows.extend(
            parse_gate_contract_rows(
                gate_contract_payload(),
                {"HYPE_USDT": {"volume_24h_settle": "1000"}, "OLD_USDT": {"volume_24h_quote": "10"}},
                "2026-07-09T00:00:00+00:00",
            )
        )

        accepted = summarize_rows(rows, min_contracts_per_exchange=2)
        rejected = summarize_rows(rows, min_contracts_per_exchange=3)

        self.assertEqual(accepted["decision"], ACCEPTED_DECISION)
        self.assertEqual(rejected["decision"], REJECTED_DECISION)
        self.assertTrue(accepted["exchanges"]["mexc"]["pass_min_contracts"])
        self.assertFalse(rejected["exchanges"]["mexc"]["pass_min_contracts"])

    def test_mexc_depth_summary_reports_dual_venue_target_coverage(self) -> None:
        rows = [
            {
                "exchange": "mexc",
                "base": "FULL",
                "listed_now": True,
                "eligible_non_binance_spot": True,
                "bid_size_contracts": 10.0,
                "ask_size_contracts": 12.0,
            },
            {
                "exchange": "gateio",
                "base": "FULL",
                "listed_now": True,
                "eligible_non_binance_spot": True,
            },
            {
                "exchange": "mexc",
                "base": "MISSING",
                "listed_now": True,
                "eligible_non_binance_spot": True,
                "bid_size_contracts": 10.0,
                "ask_size_contracts": None,
            },
            {
                "exchange": "gateio",
                "base": "MISSING",
                "listed_now": True,
                "eligible_non_binance_spot": True,
            },
        ]

        summary = summarize_mexc_depth_coverage(rows)

        self.assertEqual(summary["targets"], 2)
        self.assertEqual(summary["complete"], 1)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["coverage"], 0.5)


if __name__ == "__main__":
    unittest.main()
