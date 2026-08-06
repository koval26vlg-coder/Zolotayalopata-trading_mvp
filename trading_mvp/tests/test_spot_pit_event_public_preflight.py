from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spot_pit_event_public_preflight import (  # noqa: E402
    BINANCE_INFO,
    COINPAPRIKA_TICKERS,
    GATE_PAIRS,
    GATE_TICKERS,
    MEXC_24H,
    MEXC_BOOK,
    MEXC_INFO,
    build_preflight,
    run_preflight,
)


def _payloads() -> dict[str, object]:
    bases = [f"B{index:02d}" for index in range(20)]
    return {
        MEXC_INFO: {
            "symbols": [
                {"symbol": f"{base}USDT", "baseAsset": base, "quoteAsset": "USDT", "status": "1"}
                for base in bases
            ]
        },
        MEXC_BOOK: [
            {"symbol": f"{base}USDT", "bidPrice": "99", "askPrice": "100", "bidQty": "10", "askQty": "11"}
            for base in bases
        ],
        MEXC_24H: [
            {"symbol": f"{base}USDT", "lastPrice": "99.5", "quoteVolume": "1000000"}
            for base in bases
        ],
        GATE_PAIRS: [
            {"id": f"{base}_USDT", "base": base, "quote": "USDT", "trade_status": "tradable"}
            for base in bases
        ],
        GATE_TICKERS: [
            {
                "currency_pair": f"{base}_USDT",
                "highest_bid": "99",
                "lowest_ask": "100",
                "last": "99.5",
                "quote_volume": "1000000",
            }
            for base in bases
        ],
        BINANCE_INFO: {"symbols": []},
        COINPAPRIKA_TICKERS: [
            {
                "rank": index + 1,
                "symbol": base,
                "name": f"Coin {base}",
                "id": base.lower(),
                "quotes": {"USD": {"market_cap": 1000000 - index, "price": 1}},
            }
            for index, base in enumerate(bases)
        ],
    }


def _plan(path: Path) -> str:
    payload = {
        "schema": "spot_pit_event_forward_plan_v1",
        "research_only": True,
        "strategy_accepted": False,
        "universe": {"max_initial_bases": 100},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SpotPitEventPublicPreflightTests(unittest.TestCase):
    def test_accepts_complete_public_bulk_schemas(self) -> None:
        payloads = _payloads()

        def fetch(url: str) -> tuple[object, float]:
            return payloads[url], 0.01

        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            plan_hash = _plan(plan_path)
            report = build_preflight(plan_path, expected_plan_sha256=plan_hash, fetcher=fetch)

        self.assertTrue(report["accepted"])
        self.assertEqual(report["coverage"]["frozen_candidates"], 20)
        self.assertEqual(report["coverage"]["two_venue_candidates"], 20)
        self.assertFalse(report["collect_allowed_now"])
        self.assertFalse(report["live_orders"])
        self.assertFalse(report["api_keys"])

    def test_endpoint_failure_rejects_fail_closed(self) -> None:
        payloads = _payloads()

        def fetch(url: str) -> tuple[object, float]:
            if url == GATE_TICKERS:
                raise RuntimeError("gate unavailable")
            return payloads[url], 0.01

        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            _plan(plan_path)
            report = build_preflight(plan_path, fetcher=fetch)

        self.assertFalse(report["accepted"])
        self.assertIn("gate_tickers", report["errors"])
        self.assertFalse(report["checks"]["all_public_endpoints_succeeded"])

    def test_plan_hash_mismatch_and_output_write(self) -> None:
        payloads = _payloads()

        def fetch(url: str) -> tuple[object, float]:
            return payloads[url], 0.01

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan_hash = _plan(plan_path)
            with self.assertRaisesRegex(ValueError, "plan sha256 mismatch"):
                build_preflight(plan_path, expected_plan_sha256="0" * 64, fetcher=fetch)
            output = root / "preflight.json"
            report = run_preflight(plan_path, output, expected_plan_sha256=plan_hash, fetcher=fetch)
            stored = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(stored["decision"], report["decision"])
        self.assertFalse(stored["would_start_collect"])


if __name__ == "__main__":
    unittest.main()
