from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_collector import (  # noqa: E402
    GATE_FUNDING_MAX_DAYS,
    GateDailyClient,
    MexcDailyClient,
    SymbolPlan,
    _existing_rows,
    load_non_binance_symbols,
    parse_gate_candles,
    parse_gate_funding,
    parse_mexc_funding_page,
    parse_mexc_kline_payload,
    plan_universe,
)
from funding import FundingContract  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_parse_mexc_kline_payload(self) -> None:
        data = {
            "time": [1700000000, 1699913600],
            "open": [1.0, 0.9],
            "high": [1.2, 1.0],
            "low": [0.8, 0.85],
            "close": [1.1, 0.95],
            "vol": [100, 90],
            "amount": [110.0, 85.5],
        }
        rows = parse_mexc_kline_payload(data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ts"], 1699913600.0)
        self.assertEqual(rows[1]["close"], 1.1)
        self.assertEqual(rows[1]["volume_quote"], 110.0)

    def test_parse_mexc_kline_payload_bad_input(self) -> None:
        self.assertEqual(parse_mexc_kline_payload(None), [])
        self.assertEqual(parse_mexc_kline_payload({"time": [1], "open": []}), [])

    def test_parse_gate_candles(self) -> None:
        payload = [
            {"t": 1700000000, "o": "1.0", "h": "1.2", "l": "0.8", "c": "1.1", "v": 100, "sum": "110.5"},
            {"t": 1699913600, "o": "0.9", "h": "1.0", "l": "0.85", "c": "0.95", "v": 90, "sum": "85.5"},
        ]
        rows = parse_gate_candles(payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ts"], 1699913600.0)
        self.assertEqual(rows[1]["volume_quote"], 110.5)

    def test_parse_mexc_funding_page(self) -> None:
        data = {
            "totalPage": 3,
            "resultList": [
                {"fundingRate": 0.0001, "settleTime": 1700000000000},
                {"fundingRate": "bad", "settleTime": 1700000000000},
            ],
        }
        rows, total_pages = parse_mexc_funding_page(data)
        self.assertEqual(total_pages, 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ts"], 1700000000.0)

    def test_parse_gate_funding(self) -> None:
        rows = parse_gate_funding([{"t": 200, "r": "0.0002"}, {"t": 100, "r": "0.0001"}, {"t": 300}])
        self.assertEqual([row["ts"] for row in rows], [100.0, 200.0])


class FakeMexcClient(MexcDailyClient):
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        super().__init__()
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append({"path": path, "params": params})
        page_num = int((params or {}).get("page_num", 1))
        return {"data": self.pages[page_num - 1]}


class MexcFundingPaginationTests(unittest.TestCase):
    def test_fetch_funding_history_full_paginates_and_dedupes(self) -> None:
        pages = [
            {
                "totalPage": 2,
                "resultList": [
                    {"fundingRate": 0.0001, "settleTime": 2_000_000},
                    {"fundingRate": 0.0002, "settleTime": 1_000_000},
                ],
            },
            {
                "totalPage": 2,
                "resultList": [
                    {"fundingRate": 0.0002, "settleTime": 1_000_000},
                    {"fundingRate": 0.0003, "settleTime": 500_000},
                ],
            },
        ]
        client = FakeMexcClient(pages)
        rows = client.fetch_funding_history_full("BTC_USDT", page_size=2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual([row["ts"] for row in rows], [500.0, 1000.0, 2000.0])

    def test_fetch_funding_history_stops_on_empty_page(self) -> None:
        client = FakeMexcClient([{"totalPage": 5, "resultList": []}])
        rows = client.fetch_funding_history_full("BTC_USDT", page_size=2)
        self.assertEqual(rows, [])
        self.assertEqual(len(client.calls), 1)


class FakeGateClient(GateDailyClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append({"path": path, "params": params})
        return [{"t": 100, "r": "0.0001"}]


class FakeGateCappedClient(GateDailyClient):
    """Первое окно упирается в limit, половины возвращают меньше limit."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append({"path": path, "params": params})
        params = params or {}
        limit = int(params.get("limit", 1000))
        if len(self.calls) == 1:
            return [{"t": 1000 + i, "r": "0.0001"} for i in range(limit)]
        return [{"t": int(params["from"]) + i, "r": "0.0001"} for i in range(3)]


class GateFundingSplitTests(unittest.TestCase):
    def test_capped_window_splits_in_half(self) -> None:
        client = FakeGateCappedClient()
        rows = client.fetch_funding_history_full("XXX_USDT", limit=10)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(rows), 6)
        first, second, third = (call["params"] for call in client.calls)
        self.assertLess(second["to"], third["to"])
        self.assertEqual(second["from"], first["from"])


class GateFundingWindowTests(unittest.TestCase):
    def test_fetch_funding_history_uses_from_to_window(self) -> None:
        client = FakeGateClient()
        client.fetch_funding_history_full("BTC_USDT")
        params = client.calls[0]["params"]
        self.assertIn("from", params)
        self.assertIn("to", params)
        window_days = (params["to"] - params["from"]) / 86400
        self.assertLessEqual(window_days, GATE_FUNDING_MAX_DAYS + 0.01)

    def test_fetch_funding_history_respects_start_sec(self) -> None:
        client = FakeGateClient()
        import time as _time

        start = int(_time.time()) - 10 * 86400
        client.fetch_funding_history_full("BTC_USDT", start_sec=start)
        params = client.calls[0]["params"]
        self.assertEqual(params["from"], start)


class UniverseTests(unittest.TestCase):
    def _contract(self, symbol: str, base: str) -> FundingContract:
        return FundingContract(
            exchange="mexc",
            symbol=symbol,
            base=base,
            quote="USDT",
            status="trading",
        )

    def test_plan_universe_sorts_by_volume_and_tags_baseline(self) -> None:
        contracts = [self._contract("AAA_USDT", "AAA"), self._contract("BBB_USDT", "BBB")]
        tickers = {
            "AAA_USDT": {"amount24": 100.0},
            "BBB_USDT": {"amount24": 500.0},
        }
        plans = plan_universe("mexc", contracts, tickers, {"AAA"}, top=10)
        self.assertEqual([plan.symbol for plan in plans], ["BBB_USDT", "AAA_USDT"])
        self.assertFalse(plans[0].non_binance_baseline)
        self.assertTrue(plans[1].non_binance_baseline)

    def test_plan_universe_top_cap(self) -> None:
        contracts = [self._contract(f"S{i}_USDT", f"S{i}") for i in range(5)]
        plans = plan_universe("mexc", contracts, {}, set(), top=2)
        self.assertEqual(len(plans), 2)

    def test_load_non_binance_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "u.csv"
            csv_path.write_text(
                '"rank","name","symbol","coin_id","market_cap_usd","price_usd"\n'
                '"9","Hyperliquid","HYPE","hype","1","1"\n'
                '"10","Test","","x","1","1"\n',
                encoding="utf-8",
            )
            symbols = load_non_binance_symbols(csv_path)
        self.assertEqual(symbols, {"HYPE"})

    def test_load_non_binance_symbols_missing_file(self) -> None:
        self.assertEqual(load_non_binance_symbols(Path("no_such_file.csv")), set())


class ResumeTests(unittest.TestCase):
    def test_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            self.assertEqual(_existing_rows(path), 0)
            path.write_text(json.dumps({"rows": [1, 2, 3]}), encoding="utf-8")
            self.assertEqual(_existing_rows(path), 3)
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(_existing_rows(path), 0)


class SymbolPlanTests(unittest.TestCase):
    def test_as_dict(self) -> None:
        plan = SymbolPlan(
            exchange="mexc",
            symbol="BTC_USDT",
            base="BTC",
            volume_24h_quote=1.0,
            non_binance_baseline=False,
        )
        self.assertEqual(plan.as_dict()["symbol"], "BTC_USDT")


if __name__ == "__main__":
    unittest.main()
