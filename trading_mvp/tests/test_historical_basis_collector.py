from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_collector import (  # noqa: E402
    GateHistoricalBasisClient,
    HistoricalDataRetentionError,
    MexcHistoricalBasisClient,
    cache_key,
    collect_historical_basis,
    strict_merge_rows,
)


def _mexc_payload(start: int, count: int) -> dict[str, object]:
    times = [start + index * 300 for index in range(count)]
    return {
        "success": True,
        "data": {
            "time": times,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": [100.5] * count,
            "vol": [10.0] * count,
            "amount": [1005.0] * count,
        },
    }


def _gate_payload(start: int, count: int) -> list[dict[str, str]]:
    return [
        {
            "t": str(start + index * 300),
            "o": "100",
            "h": "101",
            "l": "99",
            "c": "100.5",
            "v": "10",
            "sum": "1005",
        }
        for index in range(count)
    ]


class _MexcFixtureClient(MexcHistoricalBasisClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, params: dict[str, object] | None = None) -> object:
        params = dict(params or {})
        self.calls.append((path, params))
        start = int(params["start"])
        end = int(params["end"])
        count = (end - start) // 300 + 1
        return _mexc_payload(start, count)


class _GateFixtureClient(GateHistoricalBasisClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, params: dict[str, object] | None = None) -> object:
        params = dict(params or {})
        self.calls.append((path, params))
        start = int(params["from"])
        end = int(params["to"])
        count = (end - start) // 300 + 1
        return _gate_payload(start, count)


class HistoricalSeriesClientTests(unittest.TestCase):
    def test_gate_classifies_recent_point_retention_limit(self) -> None:
        response = Mock()
        response.json.return_value = {
            "label": "INVALID_PARAM_VALUE",
            "message": "Candlestick too long ago. Maximum 10000 points recently are allowed",
        }
        error = requests.HTTPError("400 Client Error")
        error.response = response
        response.raise_for_status.side_effect = error
        client = GateHistoricalBasisClient(requests_per_sec=1000.0)
        client.session.get = Mock(return_value=response)

        with patch("funding.time.sleep", return_value=None):
            with self.assertRaisesRegex(HistoricalDataRetentionError, "maximum_recent_points=10000"):
                client.fetch_5m_series("HYPE_USDT", "trade", 100, 200)

    def test_mexc_and_gate_clients_have_independent_request_buckets(self) -> None:
        mexc = MexcHistoricalBasisClient(requests_per_sec=1000.0)
        gate = GateHistoricalBasisClient(requests_per_sec=1000.0)
        self.assertIsNot(mexc._request_bucket, gate._request_bucket)
        self.assertEqual(mexc._request_bucket.rate_per_sec, 1000.0)
        self.assertEqual(gate._request_bucket.rate_per_sec, 1000.0)

    def test_mexc_maps_trade_mark_index_and_paginates(self) -> None:
        client = _MexcFixtureClient()
        end = 300 * 2500
        rows = client.fetch_5m_series("AAA_USDT", "mark", 0, end)
        self.assertEqual(len(rows), 2501)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(client.calls[0][0].endswith("/kline/fair_price/AAA_USDT"))
        self.assertEqual(client.calls[0][1]["interval"], "Min5")

        client.calls.clear()
        client.fetch_5m_series("AAA_USDT", "index", 0, 300)
        self.assertTrue(client.calls[0][0].endswith("/kline/index_price/AAA_USDT"))
        client.calls.clear()
        client.fetch_5m_series("AAA_USDT", "trade", 0, 300)
        self.assertTrue(client.calls[0][0].endswith("/kline/AAA_USDT"))

    def test_gate_maps_mark_and_index_contract_prefixes(self) -> None:
        client = _GateFixtureClient()
        client.fetch_5m_series("AAA_USDT", "mark", 0, 300)
        self.assertEqual(client.calls[0][0], "/futures/usdt/candlesticks")
        self.assertEqual(client.calls[0][1]["contract"], "mark_AAA_USDT")
        self.assertEqual(client.calls[0][1]["interval"], "5m")
        client.calls.clear()
        client.fetch_5m_series("AAA_USDT", "index", 0, 300)
        self.assertEqual(client.calls[0][1]["contract"], "index_AAA_USDT")

    def test_conflicting_duplicate_timestamp_is_rejected(self) -> None:
        left = [{"ts": 100.0, "close": 1.0}]
        right = [{"ts": 100.0, "close": 2.0}]
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            strict_merge_rows(left, right)

    def test_cache_key_binds_plan_series_and_range(self) -> None:
        first = cache_key("plan-a", "mexc", "AAA_USDT", "mark", 100, 200)
        self.assertNotEqual(first, cache_key("plan-b", "mexc", "AAA_USDT", "mark", 100, 200))
        self.assertNotEqual(first, cache_key("plan-a", "mexc", "AAA_USDT", "index", 100, 200))
        self.assertNotEqual(first, cache_key("plan-a", "mexc", "AAA_USDT", "mark", 100, 201))


class _CollectFixtureClient:
    def __init__(self, exchange: str, *, fail: bool = False) -> None:
        self.exchange_id = exchange
        self.fail = fail
        self.calls = 0

    def fetch_5m_series(self, symbol: str, series: str, start_sec: int, end_sec: int):
        self.calls += 1
        if self.fail:
            raise RuntimeError("network fixture failure")
        return [
            {
                "ts": float(start_sec + index * 300),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume_base": 10.0,
                "volume_quote": 1005.0,
            }
            for index in range(3)
        ]

    def fetch_funding_range(self, symbol: str, start_sec: int, end_sec: int):
        self.calls += 1
        if self.fail:
            raise RuntimeError("network fixture failure")
        return [{"ts": float(start_sec), "funding_rate": 0.0001}]


def _plan(path: Path) -> dict[str, object]:
    plan = {
        "schema": "trading_mvp_historical_basis_plan_v1",
        "plan_hash": "fixture-plan-hash",
        "sample_plan": {"interval": "5m", "total_closed_days": 220},
        "runtime": {"history_collect_max_runtime_sec": 7200},
        "universe": {
            "candidates": [
                {
                    "canonical_asset_id": "asset:aaa",
                    "base": "AAA",
                    "mexc_symbol": "AAA_USDT",
                    "gateio_symbol": "AAA_USDT",
                }
            ]
        },
    }
    path.write_text(json.dumps(plan), encoding="utf-8")
    return plan


class HistoricalCollectorTests(unittest.TestCase):
    def test_resume_reuses_original_default_range_instead_of_rolling_forward(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = _plan(plan_path)
            with patch("historical_basis_collector._closed_range", return_value=(0, 600)):
                first = collect_historical_basis(
                    plan,
                    plan_path=plan_path,
                    output_root=root / "out",
                    clients={
                        "mexc": _CollectFixtureClient("mexc"),
                        "gateio": _CollectFixtureClient("gateio", fail=True),
                    },
                    max_runtime_sec=60,
                    run_id="resume-range",
                )
            self.assertFalse(first["final"])

            with patch("historical_basis_collector._closed_range", return_value=(300, 900)):
                resumed = collect_historical_basis(
                    plan,
                    plan_path=plan_path,
                    output_root=root / "out",
                    clients={
                        "mexc": _CollectFixtureClient("mexc"),
                        "gateio": _CollectFixtureClient("gateio"),
                    },
                    max_runtime_sec=60,
                    run_id="resume-range",
                    resume=True,
                )
            self.assertTrue(resumed["final"])
            self.assertEqual((resumed["start_sec"], resumed["end_sec"]), (0, 600))

    def test_second_identical_collect_uses_valid_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = _plan(plan_path)
            clients = {
                "mexc": _CollectFixtureClient("mexc"),
                "gateio": _CollectFixtureClient("gateio"),
            }
            first = collect_historical_basis(
                plan,
                plan_path=plan_path,
                output_root=root / "out",
                clients=clients,
                start_sec=0,
                end_sec=600,
                max_runtime_sec=60,
                run_id="first",
                active_gate_path=root / "active-run-gate.json",
            )
            calls_after_first = sum(client.calls for client in clients.values())
            second = collect_historical_basis(
                plan,
                plan_path=plan_path,
                output_root=root / "out",
                clients=clients,
                start_sec=0,
                end_sec=600,
                max_runtime_sec=60,
                run_id="second",
            )
            self.assertTrue(first["final"])
            self.assertTrue(second["final"])
            self.assertEqual(sum(client.calls for client in clients.values()), calls_after_first)
            self.assertEqual(second["cache_hits"], 8)
            gate = json.loads((root / "active-run-gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(gate["locks"], ["market_data_writer"])
            self.assertEqual(gate["owner_output_prefix"], first["output_prefix"])
            pointer = json.loads((root / "current-run.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["run_id"], "first")
            self.assertEqual(pointer["status"], "READY_FOR_POSTPROCESS")
            launch = Path(pointer["launch_record_path"])
            self.assertTrue(launch.is_file())
            self.assertEqual(json.loads(launch.read_text(encoding="utf-8"))["run_id"], "first")

    def test_network_failure_is_stopped_incomplete_not_partial_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = _plan(plan_path)
            result = collect_historical_basis(
                plan,
                plan_path=plan_path,
                output_root=root / "out",
                clients={
                    "mexc": _CollectFixtureClient("mexc"),
                    "gateio": _CollectFixtureClient("gateio", fail=True),
                },
                start_sec=0,
                end_sec=600,
                max_runtime_sec=60,
                run_id="failed",
            )
            self.assertFalse(result["final"])
            self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
            self.assertGreater(result["error_count"], 0)
            self.assertNotIn("ACCEPT", result["decision"])

            resumed = collect_historical_basis(
                plan,
                plan_path=plan_path,
                output_root=root / "out",
                clients={
                    "mexc": _CollectFixtureClient("mexc"),
                    "gateio": _CollectFixtureClient("gateio"),
                },
                start_sec=0,
                end_sec=600,
                max_runtime_sec=60,
                run_id="failed",
                resume=True,
            )
            self.assertTrue(resumed["final"])
            self.assertEqual(resumed["status"], "READY_FOR_POSTPROCESS")


if __name__ == "__main__":
    unittest.main()
