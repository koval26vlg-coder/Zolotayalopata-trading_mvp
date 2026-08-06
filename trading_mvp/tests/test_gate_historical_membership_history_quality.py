from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_membership_history_collector import (  # noqa: E402
    MANIFEST_SCHEMA,
    READY_FOR_QUALITY_DECISION,
    _manifest_hash,
    validate_gzip_file,
)
from gate_historical_membership_history_plan import build_history_plan, sha256_json  # noqa: E402
from gate_historical_membership_history_quality import (  # noqa: E402
    ACCEPTED_DECISION,
    build_history_quality,
    normalize_candlestick_archives,
    normalize_funding_archives,
    partition_rows_by_embargo,
)


DAY_SEC = 86_400
HOUR_SEC = 3_600


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_gzip(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _probe_hash(report: dict) -> str:
    return sha256_json(
        {
            key: value
            for key, value in report.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}
        }
    )


def _build_fixture(root: Path, *, asset_count: int = 20) -> tuple[Path, dict, Path, dict]:
    end_sec = 1_781_913_600
    listed_from = end_sec - 2 * DAY_SEC
    daily_path = root / "daily.json"
    registry_path = root / "registry.csv"
    probe_path = root / "probe.json"
    plan_path = root / "plan.json"
    _write_json(
        daily_path,
        {
            "schema": "daily_collect_v1",
            "run_id": "daily_fixture",
            "params": {
                "exchanges": ["mexc", "gateio"],
                "start_sec": end_sec - 220 * DAY_SEC,
                "end_sec": end_sec + 5,
            },
        },
    )
    symbols = [f"Q{index:02d}" for index in range(asset_count)]
    with registry_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "name", "symbol", "coin_id"])
        writer.writeheader()
        for index, symbol in enumerate(symbols, 1):
            writer.writerow(
                {
                    "rank": index,
                    "name": f"Quality Asset {index}",
                    "symbol": symbol,
                    "coin_id": f"quality-asset-{index}",
                }
            )
    rows = [
        {
            "exchange": "gateio",
            "symbol": f"{symbol}_USDT",
            "base": symbol,
            "quote": "USDT",
            "instrument_type": "linear_perpetual",
            "contract_type": "crypto",
            "lifecycle_status": "trading",
            "listed_from_ts": listed_from,
            "listed_to_ts": None,
            "active_at_snapshot": True,
            "contract_multiplier": 0.01,
            "funding_interval_sec": 28_800,
            "order_size_min_contracts": 1.0,
            "order_size_max_contracts": 1_000_000.0,
        }
        for symbol in symbols
    ]
    probe = {
        "schema": "trading_mvp_gate_historical_membership_probe_v2",
        "generated_at_utc": "2026-07-17T03:00:00Z",
        "run_id": "probe_fixture",
        "plan_hash": "b" * 64,
        "final": True,
        "decision": "GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_ACCEPTED_READY_FOR_BACKFILL_PLANONLY",
        "accepted": True,
        "runtime_sec": 1.0,
        "quality": {"accepted": True},
        "rows": rows,
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
        },
    }
    probe["artifact_hash"] = _probe_hash(probe)
    _write_json(probe_path, probe)
    plan = build_history_plan(
        probe_report_path=probe_path,
        expected_probe_plan_hash=probe["plan_hash"],
        expected_probe_artifact_hash=probe["artifact_hash"],
        daily_manifest_path=daily_path,
        coin_registry_path=registry_path,
        output_path=plan_path,
        run_id="quality_history_fixture",
        max_runtime_sec=120,
        generated_at_utc="2026-07-17T04:00:00Z",
    )
    files: list[dict] = []
    for task in plan["archive_tasks"]:
        symbol = task["symbol"]
        archive_type = task["archive_type"]
        target = root / "raw" / archive_type / f"{symbol}.csv.gz"
        if archive_type == "candlesticks_1h":
            lines = [
                f"{listed_from + index * HOUR_SEC},100,{10 + index / 1000:.6f},{11 + index / 1000:.6f},{9 + index / 1000:.6f},{9.5 + index / 1000:.6f}"
                for index in range(48)
            ]
        else:
            lines = [f"{listed_from + index * 28_800},0.0001" for index in range(6)]
        _write_gzip(target, lines)
        details = validate_gzip_file(target)
        files.append(
            {
                "cache_key": task["cache_key"],
                "symbol": symbol,
                "canonical_asset_id": task["canonical_asset_id"],
                "archive_type": archive_type,
                "year_month": task["year_month"],
                "url": task["url"],
                "path": str(target),
                "status": "downloaded",
                "http_status": 200,
                **details,
            }
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at_utc": "2026-07-17T04:01:00Z",
        "run_id": plan["run_id"],
        "plan_path": str(plan_path),
        "plan_sha256": "unused-by-quality-fixture",
        "plan_hash": plan["plan_hash"],
        "input_merkle_sha256": plan["input_merkle_sha256"],
        "output_root": str(root / "raw"),
        "final": True,
        "decision": READY_FOR_QUALITY_DECISION,
        "cache_reused": False,
        "runtime_sec": 1.0,
        "summary": {
            "total_tasks": len(files),
            "completed_tasks": len(files),
            "downloaded": len(files),
            "cached": 0,
            "missing": 0,
            "error": 0,
            "errors": 0,
        },
        "files": files,
        "research_only": True,
        "public_data_only": True,
    }
    manifest["artifact_hash"] = _manifest_hash(manifest)
    manifest_path = root / "collect-manifest.json"
    _write_json(manifest_path, manifest)
    return plan_path, plan, manifest_path, manifest


class GateMembershipHistoryQualityTests(unittest.TestCase):
    def test_partition_rows_physically_separates_train_and_oos(self) -> None:
        rows = [
            {"ts": 10, "value": "warmup"},
            {"ts": 20, "value": "train"},
            {"ts": 30, "value": "oos-boundary"},
            {"ts": 39, "value": "oos"},
            {"ts": 40, "value": "outside"},
        ]

        train, oos = partition_rows_by_embargo(
            rows,
            train_view_start_sec=10,
            oos_start_sec=30,
            history_end_sec=40,
        )

        self.assertEqual([row["value"] for row in train], ["warmup", "train"])
        self.assertEqual([row["value"] for row in oos], ["oos-boundary", "oos"])
        self.assertTrue(all(int(row["ts"]) < 30 for row in train))
        self.assertTrue(all(int(row["ts"]) >= 30 for row in oos))

    def test_quote_volume_uses_contract_multiplier_and_daily_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candles.csv.gz"
            _write_gzip(
                path,
                [
                    "1780002000,100,10,11,9,9.5",
                    "1780005600,200,12,13,11,11.5",
                ],
            )
            start = 1_780_002_000
            rows, metrics, reasons = normalize_candlestick_archives(
                [path],
                contract_multiplier=0.01,
                start_sec=start,
                end_sec=start + 2 * HOUR_SEC,
            )
            self.assertEqual(reasons, [])
            self.assertEqual(metrics["hourly_coverage"], 1.0)
            self.assertAlmostEqual(rows[0]["volume_base"], 3.0)
            self.assertAlmostEqual(rows[0]["volume_quote"], 34.0)

    def test_duplicate_candle_and_funding_timestamps_fail_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candle = root / "candle.gz"
            funding = root / "funding.gz"
            _write_gzip(candle, ["1780002000,100,10,11,9,9", "1780002000,100,10,11,9,9"])
            _write_gzip(funding, ["1780002000,0.0001", "1780002000,0.0002"])
            _, _, candle_reasons = normalize_candlestick_archives(
                [candle],
                contract_multiplier=0.01,
                start_sec=1_780_002_000,
                end_sec=1_780_005_600,
            )
            _, _, funding_reasons = normalize_funding_archives(
                [funding],
                start_sec=1_780_002_000,
                end_sec=1_780_030_800,
                funding_interval_sec=28_800,
            )
            self.assertIn("duplicate_candlestick_timestamps", candle_reasons)
            self.assertIn("duplicate_funding_timestamps", funding_reasons)

    def test_end_to_end_quality_writes_physical_train_and_sealed_oos_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, manifest_path, manifest = _build_fixture(root)
            result = build_history_quality(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_root=root / "normalized",
                report_path=root / "quality.json",
                max_runtime_sec=120,
            )
            self.assertEqual(result["decision"], ACCEPTED_DECISION)
            self.assertEqual(result["accepted_assets"], 20)
            self.assertFalse(result["oos_allowed"])
            self.assertFalse(result["replay_allowed"])
            normalized = json.loads((root / "normalized" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(normalized["point_in_time_universe"])
            self.assertEqual(len(normalized["universe"]), 20)
            self.assertEqual(result["train_manifest_hash"], normalized["split_manifests"]["train"]["artifact_hash"])
            self.assertEqual(result["oos_commitment_hash"], normalized["split_manifests"]["oos"]["artifact_hash"])
            train_manifest = json.loads(Path(result["train_manifest_path"]).read_text(encoding="utf-8"))
            oos_manifest = json.loads(Path(result["oos_manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(train_manifest["stage"], "train_view")
            self.assertEqual(oos_manifest["stage"], "sealed_oos")
            self.assertFalse(train_manifest["oos_paths_present"])
            self.assertNotIn("collect_manifest_path", train_manifest["input_provenance"])
            self.assertTrue(oos_manifest["sealed"])
            oos_start = int(normalized["split_contract"]["oos"]["start_sec"])
            for record in train_manifest["normalized_files"]:
                payload = json.loads(Path(record["kline_path"]).read_text(encoding="utf-8"))
                self.assertTrue(all(int(row["ts"]) < oos_start for row in payload["rows"]))
            for record in oos_manifest["normalized_files"]:
                payload = json.loads(Path(record["kline_path"]).read_text(encoding="utf-8"))
                self.assertTrue(all(int(row["ts"]) >= oos_start for row in payload["rows"]))
            cached = build_history_quality(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_root=root / "normalized",
                report_path=root / "quality.json",
                max_runtime_sec=120,
            )
            self.assertTrue(cached["cache_reused"])
            tampered_kline = Path(train_manifest["normalized_files"][0]["kline_path"])
            tampered_kline.write_text("{}", encoding="utf-8")
            rebuilt = build_history_quality(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_root=root / "normalized",
                report_path=root / "quality.json",
                max_runtime_sec=120,
            )
            self.assertFalse(rebuilt["cache_reused"])

    def test_collector_artifact_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, manifest_path, manifest = _build_fixture(root)
            manifest["summary"]["downloaded"] -= 1
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "hash-valid"):
                build_history_quality(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    collect_manifest_path=manifest_path,
                    expected_collect_artifact_hash=manifest["artifact_hash"],
                    output_root=root / "normalized",
                    report_path=root / "quality.json",
                    max_runtime_sec=120,
                )


if __name__ == "__main__":
    unittest.main()
