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
    CACHE_SCHEMA,
    data_request_descriptor,
    sha256_file,
    sha256_json,
)
from historical_basis_v2 import build_historical_basis_v2_plan_from_preflight  # noqa: E402
from historical_basis_v2_preflight import (  # noqa: E402
    DAY_SEC,
    HOUR_SEC,
    HYPOTHESIS_ID,
    SCHEMA as PREFLIGHT_SCHEMA,
)
from historical_basis_v2_quality import (  # noqa: E402
    align_asset_candles,
    audit_candle_series,
    build_arg_parser,
    run_historical_basis_v2_quality,
    select_liquid_assets,
    train_only_seven_day_median_quote_volume,
)


WINDOW_END = 179 * DAY_SEC
TRAIN_START = 14 * DAY_SEC
TRAIN_END = (14 + 85) * DAY_SEC


def _candle(ts: int, *, quote_volume: float = 50_000.0) -> dict[str, float]:
    return {
        "ts": float(ts),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume_base": 10.0,
        "volume_quote": quote_volume,
    }


def _six_series(timestamps: list[int]) -> dict[str, list[dict[str, float]]]:
    return {
        f"{venue}:{series}": [_candle(ts) for ts in timestamps]
        for venue in ("mexc", "gateio")
        for series in ("trade", "mark", "index")
    }


class HistoricalBasisV2QualityMathTests(unittest.TestCase):
    def test_gap_larger_than_three_hours_starts_new_segment_and_lifecycle_masks_rows(self) -> None:
        series = _six_series([0, HOUR_SEC, 4 * HOUR_SEC, 8 * HOUR_SEC])
        candidate = {
            "canonical_asset_id": "coingecko:aaa",
            "base": "AAA",
            "lifecycle": {
                "active_from_sec": HOUR_SEC,
                "active_until_sec": 9 * HOUR_SEC,
            },
        }
        rows = align_asset_candles(
            candidate,
            series,
            start_sec=0,
            end_sec=9 * HOUR_SEC,
            maximum_gap_sec=3 * HOUR_SEC,
        )

        self.assertEqual([row["ts"] for row in rows], [HOUR_SEC, 4 * HOUR_SEC, 8 * HOUR_SEC])
        self.assertEqual([row["segment_id"] for row in rows], [0, 0, 1])
        self.assertFalse(any("funding" in key for row in rows for key in row))

    def test_candle_audit_rejects_duplicate_open_and_off_grid_rows(self) -> None:
        report = audit_candle_series(
            [_candle(0), _candle(0), _candle(HOUR_SEC + 1)],
            start_sec=0,
            end_sec=2 * HOUR_SEC,
            closed_before_sec=HOUR_SEC,
        )
        self.assertFalse(report["accepted"])
        self.assertEqual(report["duplicate_count"], 1)
        self.assertEqual(report["open_bar_count"], 1)
        self.assertEqual(report["off_grid_count"], 1)

    def test_liquidity_uses_train_only_even_when_oos_volume_is_extreme(self) -> None:
        rows = []
        for ts in range(0, 20 * DAY_SEC, HOUR_SEC):
            volume = 10.0 if ts < 14 * DAY_SEC else 1_000_000_000.0
            rows.append(_candle(ts, quote_volume=volume))
        first = train_only_seven_day_median_quote_volume(
            rows,
            train_start_sec=0,
            train_end_sec=14 * DAY_SEC,
        )
        rows[-1]["volume_quote"] = 9_000_000_000_000.0
        second = train_only_seven_day_median_quote_volume(
            rows,
            train_start_sec=0,
            train_end_sec=14 * DAY_SEC,
        )

        self.assertEqual(first, 24 * 10.0)
        self.assertEqual(second, first)
        self.assertLess(first, 1_000_000.0)

    def test_deterministic_primary_and_reserve_selection(self) -> None:
        reports = [
            {
                "canonical_asset_id": f"asset:{index:02d}",
                "base": f"A{index:02d}",
                "quality_accepted": True,
                "train_worse_leg_quote_volume": float(30 - index) * 1_000_000.0,
            }
            for index in range(22)
        ]
        selected = select_liquid_assets(
            reports,
            minimum_quote_volume=1_000_000.0,
            primary_limit=12,
            reserve_limit=8,
        )
        self.assertEqual(len(selected["primary"]), 12)
        self.assertEqual(len(selected["reserve"]), 8)
        self.assertEqual(selected["primary"][0], "asset:00")
        self.assertEqual(selected["reserve"][0], "asset:12")


def _write_cache(
    root: Path,
    *,
    plan_hash: str,
    preflight_hash: str,
    venue: str,
    symbol: str,
    series: str,
    rows: list[dict[str, float]],
) -> Path:
    path = root / venue / symbol / f"{series}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = data_request_descriptor(venue, symbol, series, 0, WINDOW_END)
    payload = {
        "schema": CACHE_SCHEMA,
        "origin_plan_hash": plan_hash,
        "origin_preflight_hash": preflight_hash,
        "data_request_hash": sha256_json(descriptor),
        "data_request": descriptor,
        "venue": venue,
        "symbol": symbol,
        "series": series,
        "interval": "1h",
        "range": "[start,end)",
        "start_sec": 0,
        "end_sec": WINDOW_END,
        "rows_sha256": sha256_json(rows),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path


def _pipeline_fixture(root: Path) -> tuple[dict[str, object], Path, dict[str, object], Path]:
    timestamps = list(range(0, WINDOW_END, HOUR_SEC))
    candidates = []
    funding_references = []
    for index in range(8):
        base = f"A{index}"
        symbol = f"{base}_USDT"
        candidate: dict[str, object] = {
            "canonical_asset_id": f"coingecko:asset-{index:02d}",
            "base": base,
            "mexc_symbol": symbol,
            "gateio_symbol": symbol,
            "lifecycle": {
                "active_from_sec": 0,
                "active_until_sec": WINDOW_END,
                "mask_interval": "[active_from,active_until)",
            },
            "funding_cache": {},
        }
        for venue in ("mexc", "gateio"):
            funding_path = root / "daily" / venue / "funding" / f"{symbol}.json"
            funding_path.parent.mkdir(parents=True, exist_ok=True)
            jitter = 0 if venue == "mexc" else 1
            funding_rows = [
                {
                    "ts": float(ts + jitter),
                    "funding_rate": -0.0001 if event_index % 2 else 0.0001,
                }
                for event_index, ts in enumerate(range(0, WINDOW_END, 4 * HOUR_SEC))
            ]
            funding_path.write_text(
                json.dumps({"exchange": venue, "symbol": symbol, "rows": funding_rows}),
                encoding="utf-8",
            )
            reference = {
                "venue": venue,
                "symbol": symbol,
                "path": str(funding_path),
                "file_sha256": sha256_file(funding_path),
            }
            candidate["funding_cache"][venue] = reference
            funding_references.append(
                {
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": base,
                    **reference,
                    "reused_without_download": True,
                }
            )
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
            "window_end_sec": WINDOW_END,
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
    preflight_hash = str(preflight["preflight_hash"])
    preflight_path = root / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    plan_path = root / "plan.json"
    plan = build_historical_basis_v2_plan_from_preflight(
        preflight_path,
        plan_path,
        max_runtime_sec=60,
    )
    plan_hash = str(plan["plan_hash"])
    cache_origin_plan_hash = sha256_json({"origin": "earlier-plan-with-identical-data-request"})
    assert cache_origin_plan_hash != plan_hash
    assert "funding_cache" not in plan["universe"]["candidates"][0]

    statuses = []
    for index, candidate in enumerate(candidates):
        base = str(candidate["base"])
        symbol = str(candidate["mexc_symbol"])
        for venue in ("mexc", "gateio"):
            for series in ("trade", "mark", "index"):
                hourly_quote = 60_000.0 + index * 1_000.0 if series == "trade" else 0.0
                rows = [_candle(ts, quote_volume=hourly_quote) for ts in timestamps]
                cache_path = _write_cache(
                    root / "cache",
                    plan_hash=cache_origin_plan_hash,
                    preflight_hash=preflight_hash,
                    venue=venue,
                    symbol=symbol,
                    series=series,
                    rows=rows,
                )
                statuses.append(
                    {
                        "canonical_asset_id": candidate["canonical_asset_id"],
                        "base": base,
                        "venue": venue,
                        "symbol": symbol,
                        "series": series,
                        "status": "collected",
                        "rows": len(rows),
                        "cache_path": str(cache_path),
                        "cache_file_sha256": sha256_file(cache_path),
                        "rows_sha256": sha256_json(rows),
                        "data_request_hash": sha256_json(
                            data_request_descriptor(venue, symbol, series, 0, WINDOW_END)
                        ),
                        "cache_origin_plan_hash": cache_origin_plan_hash,
                        "cache_reused_across_plan": True,
                    }
                )

    manifest: dict[str, object] = {
        "schema": "trading_mvp_historical_basis_v2_collect_v2",
        "run_id": "fixture-collect",
        "status": "READY_FOR_POSTPROCESS",
        "decision": "HISTORICAL_BASIS_V2_CANDLES_COLLECTED_NOT_EVALUATED",
        "final": True,
        "plan_path": str(plan_path),
        "plan_hash": plan_hash,
        "expected_plan_hash": plan_hash,
        "preflight_hash": preflight_hash,
        "start_sec": 0,
        "end_sec": WINDOW_END,
        "range": "[start,end)",
        "interval": "1h",
        "daily_or_funding_requests": 0,
        "funding_cache_references": funding_references,
        "statuses": statuses,
    }
    manifest["manifest_hash"] = sha256_json(manifest)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return plan, plan_path, manifest, manifest_path


class HistoricalBasisV2QualityPipelineTests(unittest.TestCase):
    def test_pipeline_writes_separate_candles_funding_train_oos_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, manifest, manifest_path = _pipeline_fixture(root)
            candles_path = root / "normalized-candles.jsonl"
            funding_path = root / "funding-events.jsonl"
            report_path = root / "quality.json"
            result = run_historical_basis_v2_quality(
                plan,
                manifest,
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                manifest_path=manifest_path,
                candles_output=candles_path,
                funding_output=funding_path,
                report_output=report_path,
                max_runtime_sec=60,
            )

            self.assertEqual(result["verdict"], "QUALITY_ACCEPTED_NOT_EVALUATED")
            self.assertEqual(result["surviving_asset_count"], 8)
            self.assertEqual(len(result["primary_assets"]), 8)
            self.assertEqual(result["reserve_assets"], [])
            candle_rows = [json.loads(line) for line in candles_path.read_text(encoding="utf-8").splitlines()]
            funding_rows = [json.loads(line) for line in funding_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(candle_rows), 8 * 179 * 24)
            self.assertFalse(any("funding" in key for row in candle_rows for key in row))
            self.assertEqual(len(funding_rows), 8 * 2 * (179 * 6))
            first_hour = [row for row in funding_rows if 0 <= row["settlement_ts"] < HOUR_SEC]
            self.assertEqual(len(first_hour), 16)
            self.assertEqual({row["venue"] for row in first_hour}, {"mexc", "gateio"})
            self.assertEqual(len({row["event_id"] for row in funding_rows}), len(funding_rows))
            self.assertEqual(result["train_row_count"], 8 * 85 * 24)
            self.assertEqual(result["oos_row_count"], 8 * 80 * 24)
            self.assertEqual(result["funding_event_count"], len(funding_rows))
            self.assertIn("funding_event_merkle_sha256", result)
            for name in ("candles", "funding", "train", "oos", "report"):
                artifact = result["output_artifacts"][name]
                self.assertTrue(Path(artifact["path"]).is_file())
                self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["output_artifacts"]["candles"]["path"], str(candles_path.resolve()))
            self.assertEqual(persisted["output_artifacts"]["funding"]["sha256"], sha256_file(funding_path))
            self.assertFalse(result["data_access_audit"]["returns_read"])
            self.assertFalse(result["data_access_audit"]["pnl_computed"])

    def test_expected_plan_hash_fails_before_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, manifest, manifest_path = _pipeline_fixture(root)
            with self.assertRaisesRegex(ValueError, "expected plan hash mismatch"):
                run_historical_basis_v2_quality(
                    plan,
                    manifest,
                    plan_path=plan_path,
                    expected_plan_hash="wrong",
                    manifest_path=manifest_path,
                    candles_output=root / "candles.jsonl",
                    funding_output=root / "funding.jsonl",
                    report_output=root / "report.json",
                    max_runtime_sec=60,
                )
            self.assertFalse((root / "candles.jsonl").exists())

    def test_cli_contract_names_all_required_inputs_and_outputs(self) -> None:
        args = build_arg_parser().parse_args(
            [
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "abc",
                "--manifest",
                "manifest.json",
                "--candles-output",
                "candles.jsonl",
                "--funding-output",
                "funding.jsonl",
                "--report-output",
                "quality.json",
                "--max-runtime-sec",
                "1800",
            ]
        )
        self.assertEqual(args.expected_plan_hash, "abc")
        self.assertEqual(args.candles_output, "candles.jsonl")
        self.assertEqual(args.funding_output, "funding.jsonl")
        self.assertEqual(args.report_output, "quality.json")


if __name__ == "__main__":
    unittest.main()
