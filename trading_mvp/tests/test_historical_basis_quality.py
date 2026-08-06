from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_edge import sha256_json  # noqa: E402
from historical_basis_quality import (  # noqa: E402
    align_asset_rows,
    audit_candle_series,
    run_historical_basis_quality,
)


def _candle(ts: int, *, close: float = 100.0, volume_quote: float = 500_000.0):
    return {
        "ts": float(ts),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume_base": 10.0,
        "volume_quote": volume_quote,
    }


def _series_map(timestamps: list[int]) -> dict[str, list[dict[str, float]]]:
    result: dict[str, list[dict[str, float]]] = {}
    for venue in ("mexc", "gateio"):
        for series in ("trade", "mark", "index"):
            result[f"{venue}:{series}"] = [
                _candle(ts, close=100.0 + (0.1 if venue == "gateio" else 0.0))
                for ts in timestamps
            ]
    result["mexc:funding"] = [{"ts": float(timestamps[1]), "funding_rate": 0.0001}]
    result["gateio:funding"] = [{"ts": float(timestamps[1]), "funding_rate": 0.0002}]
    return result


class HistoricalBasisQualityMathTests(unittest.TestCase):
    def test_alignment_joins_funding_only_on_exact_settlement_and_splits_gap(self) -> None:
        series = _series_map([0, 300, 1800])
        rows = align_asset_rows("AAA", series, maximum_gap_sec=900)
        self.assertEqual([row["segment_id"] for row in rows], [0, 0, 1])
        self.assertIsNone(rows[0]["mexc_funding_rate"])
        self.assertEqual(rows[1]["mexc_funding_rate"], 0.0001)
        self.assertIsNone(rows[2]["mexc_funding_rate"])

    def test_candle_audit_rejects_duplicates_and_open_bar(self) -> None:
        duplicate = [_candle(0), _candle(0)]
        report = audit_candle_series(duplicate, start_sec=0, end_sec=300, closed_before_sec=600)
        self.assertEqual(report["duplicate_count"], 1)
        self.assertFalse(report["accepted"])
        open_bar = audit_candle_series([_candle(300)], start_sec=300, end_sec=300, closed_before_sec=300)
        self.assertEqual(open_bar["open_bar_count"], 1)
        self.assertFalse(open_bar["accepted"])


def _write_cache(
    root: Path,
    *,
    plan_hash: str,
    venue: str,
    symbol: str,
    series: str,
    rows: list[dict[str, float]],
    start_sec: int,
    end_sec: int,
) -> Path:
    path = root / venue / symbol / f"{series}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "trading_mvp_historical_basis_cache_v1",
        "plan_hash": plan_hash,
        "venue": venue,
        "symbol": symbol,
        "series": series,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "rows_sha256": sha256_json(rows),
        "rows": rows,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fixture(root: Path, asset_count: int, *, break_last: bool = False):
    plan_hash = "fixture-plan"
    candidates = []
    statuses = []
    start_sec, end_sec = 0, 600
    for index in range(asset_count):
        base = f"A{index}"
        candidate = {
            "canonical_asset_id": f"asset:{base.lower()}",
            "base": base,
            "mexc_symbol": f"{base}_USDT",
            "gateio_symbol": f"{base}_USDT",
        }
        candidates.append(candidate)
        series_map = _series_map([0, 300, 600])
        if break_last and index == asset_count - 1:
            series_map["gateio:index"] = series_map["gateio:index"][:1]
        for venue in ("mexc", "gateio"):
            symbol = candidate[f"{venue}_symbol"]
            for series in ("trade", "mark", "index", "funding"):
                rows = series_map[f"{venue}:{series}"]
                path = _write_cache(
                    root / "cache",
                    plan_hash=plan_hash,
                    venue=venue,
                    symbol=symbol,
                    series=series,
                    rows=rows,
                    start_sec=start_sec,
                    end_sec=end_sec,
                )
                statuses.append(
                    {
                        "venue": venue,
                        "symbol": symbol,
                        "series": series,
                        "status": "collected",
                        "rows": len(rows),
                        "cache_path": str(path),
                    }
                )
    plan = {
        "plan_hash": plan_hash,
        "universe": {
            "candidates": candidates,
            "minimum_surviving_assets": 8,
            "primary_limit": 12,
            "reserve_limit": 8,
        },
        "sample_plan": {"warmup_days": 20, "train_days": 100},
        "quality_gates": {
            "minimum_series_coverage": 0.98,
            "minimum_dual_venue_aligned_coverage": 0.95,
            "minimum_funding_coverage": 0.0,
            "maximum_gap_sec": 900,
            "minimum_median_quote_volume": 0.0,
        },
    }
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest = {
        "schema": "trading_mvp_historical_basis_collect_v1",
        "run_id": "fixture-run",
        "final": True,
        "status": "READY_FOR_POSTPROCESS",
        "plan_hash": plan_hash,
        "plan_path": str(plan_path),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "statuses": statuses,
        "input_merkle_sha256": "fixture-input",
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return plan, manifest, manifest_path


class HistoricalBasisQualityPipelineTests(unittest.TestCase):
    def test_quality_accepts_eight_assets_and_writes_normalized_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, manifest, manifest_path = _fixture(root, 8)
            normalized = root / "normalized.jsonl"
            report_path = root / "quality.json"
            result = run_historical_basis_quality(
                plan,
                manifest,
                manifest_path=manifest_path,
                normalized_output=normalized,
                report_output=report_path,
                max_runtime_sec=60,
                now_sec=1200,
            )
            self.assertEqual(result["verdict"], "QUALITY_ACCEPTED_NOT_EVALUATED")
            self.assertEqual(result["surviving_asset_count"], 8)
            self.assertEqual(len(normalized.read_text(encoding="utf-8").splitlines()), 24)
            self.assertEqual(result["primary_assets"], [f"A{i}" for i in range(8)])
            self.assertEqual(result["train_rows"], 24)
            self.assertEqual(result["oos_rows"], 0)
            self.assertTrue(Path(result["train_output"]).exists())
            self.assertTrue(Path(result["oos_output"]).exists())
            self.assertFalse(result["data_access_audit"]["pnl_computed"])
            self.assertIn("code_provenance", result)
            self.assertIn("code_snapshot_hash", result["code_provenance"])

    def test_quality_fails_closed_below_eight_survivors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, manifest, manifest_path = _fixture(root, 8, break_last=True)
            result = run_historical_basis_quality(
                plan,
                manifest,
                manifest_path=manifest_path,
                normalized_output=root / "normalized.jsonl",
                report_output=root / "quality.json",
                max_runtime_sec=60,
                now_sec=1200,
            )
            self.assertEqual(result["verdict"], "INSUFFICIENT_EXECUTABLE_UNIVERSE")
            self.assertEqual(result["surviving_asset_count"], 7)
            self.assertNotIn("ACCEPT_FOR_EXECUTION", result["verdict"])


if __name__ == "__main__":
    unittest.main()
