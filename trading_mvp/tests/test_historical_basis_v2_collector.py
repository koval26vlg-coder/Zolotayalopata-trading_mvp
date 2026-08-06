from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2_collector import (  # noqa: E402
    GateHistoricalBasisV2Client,
    MexcHistoricalBasisV2Client,
    build_arg_parser,
    cache_key,
    collect_historical_basis_v2,
    sha256_file,
    strict_merge_rows,
    validate_candle_rows,
)
from historical_basis_v2 import build_historical_basis_v2_plan_from_preflight  # noqa: E402
from historical_basis_v2_preflight import (  # noqa: E402
    DAY_SEC,
    HOUR_SEC,
    HYPOTHESIS_ID,
    SCHEMA as PREFLIGHT_SCHEMA,
    sha256_json,
)


def _mexc_payload(start: int, count: int) -> dict[str, object]:
    timestamps = [start + index * HOUR_SEC for index in range(count)]
    return {
        "success": True,
        "data": {
            "time": timestamps,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": [100.5] * count,
            "vol": [10.0] * count,
            "amount": [1_005.0] * count,
        },
    }


def _gate_payload(start: int, count: int) -> list[dict[str, str]]:
    return [
        {
            "t": str(start + index * HOUR_SEC),
            "o": "100",
            "h": "101",
            "l": "99",
            "c": "100.5",
            "v": "10",
            "sum": "1005",
        }
        for index in range(count)
    ]


class MexcFixtureClient(MexcHistoricalBasisV2Client):
    def __init__(self) -> None:
        super().__init__(requests_per_sec=1_000.0)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, params: dict[str, object] | None = None) -> object:
        params = dict(params or {})
        self.calls.append((path, params))
        start = int(params["start"])
        end = int(params["end"])
        return _mexc_payload(start, (end - start) // HOUR_SEC + 1)


class GateFixtureClient(GateHistoricalBasisV2Client):
    def __init__(self) -> None:
        super().__init__(requests_per_sec=1_000.0)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, params: dict[str, object] | None = None) -> object:
        params = dict(params or {})
        self.calls.append((path, params))
        start = int(params["from"])
        end = int(params["to"])
        return _gate_payload(start, (end - start) // HOUR_SEC + 1)


class DuplicatePageGateClient(GateHistoricalBasisV2Client):
    def __init__(self) -> None:
        super().__init__(requests_per_sec=1_000.0)

    def _get(self, path: str, params: dict[str, object] | None = None) -> object:
        return _gate_payload(0, 2)


class HistoricalBasisV2ClientTests(unittest.TestCase):
    def test_mexc_uses_min60_and_non_overlapping_strict_pages(self) -> None:
        client = MexcFixtureClient()
        rows = client.fetch_1h_series("AAA_USDT", "mark", 0, 2_501 * HOUR_SEC)

        self.assertEqual(len(rows), 2_501)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0][1]["interval"], "Min60")
        self.assertTrue(client.calls[0][0].endswith("/kline/fair_price/AAA_USDT"))
        self.assertEqual(client.calls[0][1]["start"], 0)
        self.assertEqual(client.calls[1][1]["start"], 2_000 * HOUR_SEC)
        self.assertLess(client.calls[0][1]["end"], client.calls[1][1]["start"])

    def test_gate_uses_1h_and_series_contract_prefixes(self) -> None:
        client = GateFixtureClient()
        rows = client.fetch_1h_series("AAA_USDT", "index", 0, 2_001 * HOUR_SEC)

        self.assertEqual(len(rows), 2_001)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0][0], "/futures/usdt/candlesticks")
        self.assertEqual(client.calls[0][1]["contract"], "index_AAA_USDT")
        self.assertEqual(client.calls[0][1]["interval"], "1h")
        self.assertLess(client.calls[0][1]["to"], client.calls[1][1]["from"])

    def test_duplicate_pages_and_invalid_grid_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate timestamp"):
            DuplicatePageGateClient().fetch_1h_series(
                "AAA_USDT",
                "trade",
                0,
                2_001 * HOUR_SEC,
            )
        with self.assertRaisesRegex(ValueError, "off-grid"):
            validate_candle_rows(
                [
                    {
                        "ts": 1.0,
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "volume_base": 1.0,
                        "volume_quote": 1.0,
                    }
                ],
                start_sec=0,
                end_sec=HOUR_SEC,
                closed_before_sec=HOUR_SEC,
            )

    def test_strict_merge_rejects_even_identical_duplicate_rows(self) -> None:
        row = {"ts": 0.0, "close": 1.0}
        with self.assertRaisesRegex(ValueError, "duplicate timestamp"):
            strict_merge_rows([row], [dict(row)])

    def test_clients_have_independent_per_venue_token_buckets(self) -> None:
        mexc = MexcHistoricalBasisV2Client(requests_per_sec=7.0)
        gate = GateHistoricalBasisV2Client(requests_per_sec=3.0)
        self.assertIsNot(mexc._request_bucket, gate._request_bucket)
        self.assertEqual(mexc._request_bucket.rate_per_sec, 7.0)
        self.assertEqual(gate._request_bucket.rate_per_sec, 3.0)


class CollectFixtureClient:
    public_only = True

    def __init__(self, venue: str, *, error: Exception | None = None) -> None:
        self.exchange_id = venue
        self.error = error
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch_1h_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, float]]:
        self.calls.append((symbol, series, start_sec, end_sec))
        if self.error is not None:
            raise self.error
        return [
            {
                "ts": float(start_sec + index * HOUR_SEC),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume_base": 10.0,
                "volume_quote": 1_005.0,
            }
            for index in range(3)
        ]


def _write_plan(root: Path) -> tuple[dict[str, object], Path]:
    candidates = []
    for index in range(8):
        base = f"A{index}"
        symbol = f"{base}_USDT"
        candidate: dict[str, object] = {
            "canonical_asset_id": f"coingecko:asset-{index}",
            "base": base,
            "mexc_symbol": symbol,
            "gateio_symbol": symbol,
            "lifecycle": {
                "active_from_sec": 0,
                "active_until_sec": 179 * DAY_SEC,
                "mask_interval": "[active_from,active_until)",
            },
            "funding_cache": {},
        }
        for venue in ("mexc", "gateio"):
            funding = root / "daily" / venue / "funding" / f"{symbol}.json"
            funding.parent.mkdir(parents=True, exist_ok=True)
            funding.write_text(
                json.dumps({"exchange": venue, "symbol": symbol, "rows": []}),
                encoding="utf-8",
            )
            candidate["funding_cache"][venue] = {
                "venue": venue,
                "symbol": symbol,
                "path": str(funding),
                "file_sha256": sha256_file(funding),
            }
        candidates.append(candidate)
    preflight: dict[str, object] = {
        "schema": PREFLIGHT_SCHEMA,
        "hypothesis_id": HYPOTHESIS_ID,
        "final": True,
        "status": "PREFLIGHT_ACCEPTED_NOT_COLLECTED",
        "verdict": "PREFLIGHT_ACCEPTED_NOT_COLLECTED",
        "window": {
            "interval": "[start,end)",
            "interval_name": "1h",
            "window_days": 179,
            "window_start_sec": 0,
            "window_end_sec": 179 * DAY_SEC,
            "expected_candle_rows": 179 * 24,
        },
        "universe": {
            "candidate_count": len(candidates),
            "candidates": candidates,
        },
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_metrics_read": False,
        },
    }
    preflight["preflight_hash"] = sha256_json(preflight)
    preflight_path = root / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    path = root / "plan.json"
    plan = build_historical_basis_v2_plan_from_preflight(
        preflight_path,
        path,
        max_runtime_sec=60,
    )
    # The plan intentionally normalizes candidates; acquisition must recover
    # lifecycle and funding references from the hash-bound preflight artifact.
    assert "funding_cache" not in plan["universe"]["candidates"][0]
    return plan, path


class HistoricalBasisV2CollectorTests(unittest.TestCase):
    def test_second_plan_with_same_data_request_reuses_all_candle_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path = _write_plan(root)
            clients = {
                "mexc": CollectFixtureClient("mexc"),
                "gateio": CollectFixtureClient("gateio"),
            }
            first = collect_historical_basis_v2(
                plan,
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=root / "historical-basis-1h-v2",
                clients=clients,
                max_runtime_sec=60,
                run_id="first",
                active_run_gate_path=root / "active-run-gate.json",
            )
            calls_after_first = sum(len(client.calls) for client in clients.values())
            first_cache_hashes = {
                (row["venue"], row["symbol"], row["series"]): row["cache_file_sha256"]
                for row in first["statuses"]
            }
            second_plan_path = root / "plan-second.json"
            second_plan = build_historical_basis_v2_plan_from_preflight(
                root / "preflight.json",
                second_plan_path,
                max_runtime_sec=59,
            )
            self.assertNotEqual(plan["plan_hash"], second_plan["plan_hash"])
            second = collect_historical_basis_v2(
                second_plan,
                plan_path=second_plan_path,
                expected_plan_hash=str(second_plan["plan_hash"]),
                output_root=root / "historical-basis-1h-v2",
                clients=clients,
                max_runtime_sec=60,
                run_id="second",
            )

            self.assertTrue(first["final"])
            self.assertTrue(second["final"])
            self.assertEqual(calls_after_first, 48)
            self.assertEqual(sum(len(client.calls) for client in clients.values()), 48)
            self.assertEqual(second["cache_hits"], 48)
            self.assertEqual(second["expected_items"], 48)
            self.assertEqual(second["plan_hash"], second_plan["plan_hash"])
            self.assertTrue(all(row["series"] in {"trade", "mark", "index"} for row in first["statuses"]))
            self.assertEqual(len(first["funding_cache_references"]), 16)
            self.assertTrue(all("cache_file_sha256" in row for row in first["statuses"]))
            self.assertTrue(all("data_request_hash" in row for row in second["statuses"]))
            self.assertTrue(all(row["cache_reused_across_plan"] for row in second["statuses"]))
            self.assertTrue(
                all(row["cache_origin_plan_hash"] == plan["plan_hash"] for row in second["statuses"])
            )
            self.assertEqual(
                {
                    (row["venue"], row["symbol"], row["series"]): row["cache_file_sha256"]
                    for row in second["statuses"]
                },
                first_cache_hashes,
            )
            gate = json.loads((root / "active-run-gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["status"], "READY_FOR_POSTPROCESS")

    def test_network_timeout_is_stopped_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path = _write_plan(root)
            result = collect_historical_basis_v2(
                plan,
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                output_root=root / "historical-basis-1h-v2",
                clients={
                    "mexc": CollectFixtureClient("mexc"),
                    "gateio": CollectFixtureClient("gateio", error=TimeoutError("fixture timeout")),
                },
                max_runtime_sec=60,
                run_id="timeout",
                active_run_gate_path=root / "active-run-gate.json",
            )

            self.assertFalse(result["final"])
            self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
            self.assertEqual(result["decision"], "HISTORICAL_BASIS_V2_COLLECT_INCOMPLETE")
            self.assertGreater(result["error_count"], 0)
            self.assertEqual(result["next_allowed_command"], "visible-resume-fast-edge-basis-v2-history-collect")
            gate = json.loads((root / "active-run-gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["status"], "STOPPED_INCOMPLETE")
            self.assertIsNone(gate["collector_pid"])
            self.assertEqual(gate["process_ids"], [])

    def test_expected_plan_hash_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path = _write_plan(root)
            with self.assertRaisesRegex(ValueError, "expected plan hash mismatch"):
                collect_historical_basis_v2(
                    plan,
                    plan_path=plan_path,
                    expected_plan_hash="wrong",
                    output_root=root / "out",
                    clients={
                        "mexc": CollectFixtureClient("mexc"),
                        "gateio": CollectFixtureClient("gateio"),
                    },
                    max_runtime_sec=60,
                    run_id="wrong-hash",
                )
            self.assertFalse((root / "out").exists())

    def test_cli_contract_contains_hash_gate_and_run_controls(self) -> None:
        args = build_arg_parser().parse_args(
            [
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "abc",
                "--output-root",
                "out",
                "--max-runtime-sec",
                "5400",
                "--active-run-gate",
                "gate.json",
                "--code-snapshot-hash",
                "code-hash",
                "--code-snapshot-manifest",
                "code.json",
                "--run-id",
                "run-1",
                "--resume",
            ]
        )
        self.assertEqual(args.expected_plan_hash, "abc")
        self.assertEqual(args.active_run_gate, "gate.json")
        self.assertEqual(args.code_snapshot_hash, "code-hash")
        self.assertTrue(args.resume)

    def test_cache_key_is_hourly_request_bound_not_plan_bound(self) -> None:
        first = cache_key("mexc", "AAA_USDT", "mark", 0, HOUR_SEC)
        self.assertEqual(first, cache_key("mexc", "AAA_USDT", "mark", 0, HOUR_SEC))
        self.assertNotEqual(first, cache_key("mexc", "AAA_USDT", "index", 0, HOUR_SEC))
        self.assertNotEqual(first, cache_key("gateio", "AAA_USDT", "mark", 0, HOUR_SEC))
        self.assertNotEqual(first, cache_key("mexc", "AAA_USDT", "mark", HOUR_SEC, 2 * HOUR_SEC))


if __name__ == "__main__":
    unittest.main()
