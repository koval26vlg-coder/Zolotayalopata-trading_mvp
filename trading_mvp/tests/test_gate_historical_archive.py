from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_archive import (  # noqa: E402
    ARCHIVE_BASE_URL,
    build_archive_recovery_preflight,
    build_gate_archive_url,
    build_gate_spot_archive_url,
    month_keys_for_range,
    parse_gate_archive_candlestick,
    parse_gate_archive_funding_apply,
    parse_gate_archive_mark_price,
    aggregate_gate_archive_mark_prices,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_recovery_inputs(root: Path, *, mexc_survivors: int) -> tuple[Path, Path]:
    statuses = []
    for index in range(8):
        canonical_id = f"coingecko:asset-{index}"
        base = f"A{index}"
        for series in ("trade", "mark", "index"):
            statuses.append(
                {
                    "canonical_asset_id": canonical_id,
                    "base": base,
                    "venue": "mexc",
                    "symbol": f"{base}_USDT",
                    "series": series,
                    "status": "available" if index < mexc_survivors else "missing",
                    "rows": 288 if index < mexc_survivors else 0,
                    "error": None,
                }
            )
            statuses.append(
                {
                    "canonical_asset_id": canonical_id,
                    "base": base,
                    "venue": "gateio",
                    "symbol": f"{base}_USDT",
                    "series": series,
                    "status": "retention_limited",
                    "rows": 0,
                    "error": "maximum_recent_points=10000",
                }
            )
    universe = {
        "schema": "trading_mvp_historical_basis_universe_availability_v1",
        "generated_at_utc": "2026-07-15T00:00:00+00:00",
        "run_id": "basis-universe-fixture",
        "final": True,
        "decision": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "assets": [],
        "asset_count": 0,
        "probed_candidate_count": 8,
        "rejections_by_reason": {"history_boundary_missing": 8},
        "history_probe": {
            "history_days": 220,
            "boundary_start_sec": 1_765_097_100,
            "boundary_end_sec": 1_765_183_200,
            "required_series": ["trade", "mark", "index"],
            "required_series_count_per_asset": 6,
            "statuses": statuses,
        },
        "selection_policy": {},
        "source_provenance": {},
        "runtime_sec": 1.0,
        "max_runtime_sec": 60,
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "live_orders": False,
            "api_keys": False,
        },
        "next_allowed_command": "close-hypothesis-insufficient-universe",
        "universe_hash": _sha256_json([]),
    }
    universe["artifact_hash"] = _sha256_json(
        {
            key: value
            for key, value in universe.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
        }
    )
    universe_path = root / "universe.json"
    universe_path.write_text(json.dumps(universe), encoding="utf-8")
    closure = {
        "schema": "trading_mvp_historical_basis_retention_closure_v1",
        "hypothesis_id": "cross_venue_perp_basis_convergence_history_v1",
        "final": True,
        "verdict": "INSUFFICIENT_DATA",
        "edge_evaluated": False,
        "pnl_read": False,
        "original_artifact": {
            "path": str(universe_path.resolve()),
            "file_sha256": _sha256_file(universe_path),
            "internal_artifact_hash": universe["artifact_hash"],
        },
        "frozen_contract": {
            "interval": "5m",
            "required_history_days": 220,
            "warmup_days": 20,
            "train_days": 100,
            "oos_days": 100,
            "strategy_change_allowed": False,
        },
    }
    closure_path = root / "closure.json"
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    return universe_path, closure_path


class GateHistoricalArchiveFormatTests(unittest.TestCase):
    def test_official_archive_urls_and_month_range_are_deterministic(self) -> None:
        self.assertEqual(
            build_gate_archive_url("mark_prices", "BTC_USDT", "202606"),
            f"{ARCHIVE_BASE_URL}/futures_usdt/mark_prices/202606/BTC_USDT-202606.csv.gz",
        )
        self.assertEqual(
            month_keys_for_range(1_764_547_200, 1_770_336_000),
            ["202512", "202601", "202602"],
        )
        with self.assertRaisesRegex(ValueError, "unsupported archive type"):
            build_gate_archive_url("trades", "BTC_USDT", "202606")

    def test_spot_archive_url_uses_the_official_layout(self) -> None:
        self.assertEqual(
            build_gate_spot_archive_url("candlesticks_1h", "AERO_USDT", "202512"),
            f"{ARCHIVE_BASE_URL}/spot/candlesticks_1h/202512/AERO_USDT-202512.csv.gz",
        )

    def test_parsers_match_gate_archive_rows(self) -> None:
        candle = parse_gate_archive_candlestick(
            "1780272000,16479862,73856,74058.1,73615.5,73648.8"
        )
        self.assertEqual(candle["ts"], 1_780_272_000)
        self.assertEqual(candle["volume_contracts"], 16_479_862.0)
        self.assertEqual(candle["open"], 73_648.8)
        self.assertEqual(candle["high"], 74_058.1)
        self.assertEqual(candle["low"], 73_615.5)
        self.assertEqual(candle["close"], 73_856.0)

        mark = parse_gate_archive_mark_price(
            "1680307218.246630,28471.95,28470.84,28457.0"
        )
        self.assertEqual(mark["index_price"], 28_471.95)
        self.assertEqual(mark["mark_price"], 28_470.84)
        self.assertEqual(mark["last_price"], 28_457.0)

        funding = parse_gate_archive_funding_apply("1780272001,0.000081")
        self.assertEqual(funding, {"ts": 1_780_272_001.0, "funding_rate": 0.000081})

    def test_mark_and_index_ticks_aggregate_to_closed_five_minute_ohlc(self) -> None:
        rows = [
            parse_gate_archive_mark_price("100.0,10,20,30"),
            parse_gate_archive_mark_price("200.0,12,18,31"),
            parse_gate_archive_mark_price("299.9,11,22,32"),
            parse_gate_archive_mark_price("300.0,15,25,35"),
            parse_gate_archive_mark_price("599.9,14,24,34"),
        ]
        result = aggregate_gate_archive_mark_prices(
            rows,
            start_sec=0,
            end_sec=600,
            interval_sec=300,
        )

        self.assertEqual(
            result["index"],
            [
                {
                    "ts": 0.0,
                    "open": 10.0,
                    "high": 12.0,
                    "low": 10.0,
                    "close": 11.0,
                    "volume_base": 0.0,
                    "volume_quote": 0.0,
                },
                {
                    "ts": 300.0,
                    "open": 15.0,
                    "high": 15.0,
                    "low": 14.0,
                    "close": 14.0,
                    "volume_base": 0.0,
                    "volume_quote": 0.0,
                },
            ],
        )
        self.assertEqual(result["mark"][0]["open"], 20.0)
        self.assertEqual(result["mark"][0]["high"], 22.0)
        self.assertEqual(result["mark"][0]["low"], 18.0)
        self.assertEqual(result["mark"][0]["close"], 22.0)


class GateHistoricalArchiveRecoveryPreflightTests(unittest.TestCase):
    def test_rejects_before_network_when_mexc_upper_bound_is_below_eight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path, closure_path = _write_recovery_inputs(root, mexc_survivors=7)
            result = build_archive_recovery_preflight(universe_path, closure_path)

        self.assertEqual(result["verdict"], "INSUFFICIENT_EXECUTABLE_UNIVERSE")
        self.assertEqual(result["mexc_history_upper_bound_assets"], 7)
        self.assertEqual(result["minimum_required_assets"], 8)
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["next_allowed_command"], "none_archive_collect_forbidden")
        self.assertFalse(result["data_access_audit"]["returns_read"])
        self.assertFalse(result["data_access_audit"]["oos_read"])
        self.assertFalse(result["data_access_audit"]["pnl_computed"])

    def test_eight_mexc_survivors_allow_only_planonly_source_amendment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path, closure_path = _write_recovery_inputs(root, mexc_survivors=8)
            result = build_archive_recovery_preflight(universe_path, closure_path)

        self.assertEqual(result["verdict"], "ARCHIVE_SOURCE_AMENDMENT_PLANONLY_REQUIRED")
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(
            result["next_allowed_command"],
            "fast-edge-basis-gate-archive-source-planonly",
        )

    def test_source_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path, closure_path = _write_recovery_inputs(root, mexc_survivors=8)
            universe_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source artifact hash mismatch"):
                build_archive_recovery_preflight(universe_path, closure_path)


if __name__ == "__main__":
    unittest.main()
