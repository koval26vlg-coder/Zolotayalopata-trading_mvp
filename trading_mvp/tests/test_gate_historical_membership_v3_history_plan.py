from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gate_historical_archive as gate_archive  # noqa: E402
import gate_historical_membership_history_plan as legacy_history_plan  # noqa: E402
import gate_historical_membership_v2_closure as membership_v2_closure  # noqa: E402
import gate_historical_membership_v3 as membership_v3  # noqa: E402
from gate_historical_membership_v3_history_collector import (  # noqa: E402
    READY_FOR_QUALITY_PLAN_DECISION,
    _manifest_hash as v3_collect_manifest_hash,
    collect_history_archives,
)
from gate_historical_membership_v3_history_plan import (  # noqa: E402
    HISTORY_PLAN_DECISION,
    authorize_history_collect,
    build_history_plan,
    select_history_universe,
)
from gate_historical_membership_history_collector import validate_gzip_file  # noqa: E402
from gate_historical_membership_v3_history_quality import (  # noqa: E402
    ACCEPTED_DECISION as V3_QUALITY_ACCEPTED_DECISION,
    PLAN_DECISION as V3_QUALITY_PLAN_DECISION,
    REJECTED_DECISION as V3_QUALITY_REJECTED_DECISION,
    build_quality_plan,
    evaluate_history_quality,
    normalize_candlestick_archives_v3,
)


WINDOW_END = 1_800_000_000
WINDOW_START = WINDOW_END - 220 * 86_400


def _write_gzip(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def _candidate(index: int, cohort: str) -> dict:
    base = f"A{index:02d}"
    active = cohort == "active"
    listed_to = None
    if cohort == "known_end":
        listed_to = WINDOW_END - 15 * 86_400
    return {
        "exchange": "gateio",
        "symbol": f"{base}_USDT",
        "base": base,
        "canonical_asset_id": f"coingecko:asset-{index}",
        "coin_id": f"asset-{index}",
        "listed_from_ts": WINDOW_START - 30 * 86_400,
        "listed_to_ts": listed_to,
        "active_at_snapshot": active,
        "lifecycle_status": "trading" if active else "delisted",
        "contract_multiplier": 0.01,
        "window_overlap_start_sec": WINDOW_START,
        "window_overlap_end_sec": listed_to or WINDOW_END,
    }


def _write_v3_source(root: Path, *, accepted: bool = True) -> tuple[Path, Path, dict, dict]:
    plan_path = root / "v3-source-plan.json"
    report_path = root / "v3-source-report.json"
    candidates = []
    candidates.extend(_candidate(index, "active") for index in range(20))
    candidates.extend(_candidate(20 + index, "missing_end") for index in range(3))
    candidates.append(_candidate(23, "known_end"))
    frozen = {
        "schema": membership_v3.SCHEMA,
        "run_id": "membership_v3_source_fixture",
        "candidate_universe": {
            "minimum_candidates": 8,
            "candidate_count": len(candidates),
            "excluded_count": 0,
            "candidates": candidates,
            "exclusions": [],
        },
        "history_window": {"start_sec": WINDOW_START, "end_sec": WINDOW_END, "days": 220},
        "probe_sample": {
            "active_control": candidates[:10],
            "missing_end_delisted": candidates[20:23],
            "known_end_delisted_control": candidates[23:],
        },
        "probe_tasks": [
            {
                "cohort": "active_control",
                "symbol": "A00_USDT",
                "year_month": "202601",
                "archive_type": "candlesticks_1h",
                "url": "https://example.invalid/A00_USDT-202601.csv.gz",
                "task_hash": "f" * 64,
            }
        ],
        "quality_gates": {
            "minimum_candidates": 8,
            "minimum_cohort_symbol_availability": 0.8,
            "maximum_request_error_rate": 0.05,
            "future_full_history_minimum_delisted_end_coverage": 0.9,
            "future_full_history_minimum_series_coverage": 0.98,
        },
        "runtime_contract": {"max_runtime_sec": 600, "workers": 8},
        "code_provenance": {
            "module_sha256": membership_v3.sha256_file(Path(membership_v3.__file__).resolve()),
            "closure_module_sha256": membership_v3.sha256_file(
                Path(membership_v2_closure.__file__).resolve()
            ),
            "archive_module_sha256": membership_v3.sha256_file(
                Path(gate_archive.__file__).resolve()
            ),
            "history_plan_module_sha256": membership_v3.sha256_file(
                Path(legacy_history_plan.__file__).resolve()
            ),
        },
        "research_contract": {
            "returns_read": False,
            "pnl_read": False,
            "oos_read": False,
            "grid_search": False,
        },
    }
    plan_hash = membership_v3.sha256_json(frozen)
    plan = {
        **frozen,
        "generated_at_utc": "2026-07-17T06:00:00Z",
        "decision": membership_v3.PLAN_DECISION,
        "final": True,
        "plan_hash": plan_hash,
        "frozen_contract": frozen,
        "next_allowed_command": "fast-edge-membership-v3-source-probe",
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    report = {
        "schema": membership_v3.PROBE_SCHEMA,
        "generated_at_utc": "2026-07-17T06:01:00Z",
        "run_id": plan["run_id"],
        "plan_path": str(plan_path.resolve()),
        "plan_hash": plan_hash,
        "final": True,
        "decision": (
            membership_v3.ACCEPTED_PROBE_DECISION
            if accepted
            else membership_v3.REJECTED_PROBE_DECISION
        ),
        "accepted": accepted,
        "cache_reused": False,
        "runtime_sec": 1.0,
        "quality": {
            "accepted": accepted,
            "tasks_expected": 1,
            "tasks_completed": 1,
            "request_error_rate": 0.0,
            "cohorts": {
                "active_control": {
                    "sample_symbols": 1,
                    "available_symbols": 1,
                    "symbol_availability": 1.0,
                    "passed": accepted,
                }
            },
        },
        "results": [],
        "data_access_audit": {
            "archive_payload_read": False,
            "returns_read": False,
            "signals_read": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "next_allowed_command": (
            "fast-edge-membership-v3-history-plan"
            if accepted
            else "none_membership_v3_archive_source_rejected"
        ),
    }
    report["artifact_hash"] = membership_v3.sha256_json(
        {
            key: value
            for key, value in report.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
        }
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return plan_path, report_path, plan, report


def _write_v3_history_collect_fixture(
    root: Path,
) -> tuple[Path, dict, Path, dict]:
    _, report_path, source_plan, report = _write_v3_source(root)
    history_path = root / "history-plan.json"
    history = build_history_plan(
        source_probe_report_path=report_path,
        expected_source_plan_hash=source_plan["plan_hash"],
        expected_source_artifact_hash=report["artifact_hash"],
        output_path=history_path,
        run_id="membership_v3_history_quality_fixture",
        max_runtime_sec=120,
        generated_at_utc="2026-07-17T06:02:00Z",
    )
    assets = {row["symbol"]: row for row in history["universe"]["eligible"]}
    first_task: dict[tuple[str, str], str] = {}
    for task in history["archive_tasks"]:
        first_task.setdefault((task["symbol"], task["archive_type"]), task["cache_key"])

    generated_files: dict[tuple[str, str], tuple[Path, dict]] = {}
    for symbol, asset in assets.items():
        start = int(asset["acquisition_start_sec"])
        resolution = asset["lifecycle_end_resolution"]
        if resolution == "archive_observed_pending":
            end = min(int(asset["acquisition_end_sec"]), start + 60 * 86_400)
        elif asset.get("resolved_lifecycle_end_sec") is not None:
            end = int(asset["resolved_lifecycle_end_sec"])
        else:
            end = int(asset["acquisition_end_sec"])
        candle_path = root / "raw" / "candlesticks_1h" / f"{symbol}.csv.gz"
        candle_lines = [
            f"{timestamp},100,10,11,9,10"
            for timestamp in range(start, end, 3_600)
        ]
        _write_gzip(candle_path, candle_lines)
        generated_files[(symbol, "candlesticks_1h")] = (
            candle_path,
            validate_gzip_file(candle_path),
        )
        funding_path = root / "raw" / "funding_applies" / f"{symbol}.csv.gz"
        funding_lines = [
            f"{timestamp},0.0001"
            for timestamp in range(start, end, 28_800)
        ]
        _write_gzip(funding_path, funding_lines)
        generated_files[(symbol, "funding_applies")] = (
            funding_path,
            validate_gzip_file(funding_path),
        )

    files: list[dict] = []
    downloaded = 0
    missing = 0
    for task in history["archive_tasks"]:
        key = (task["symbol"], task["archive_type"])
        path, details = generated_files[key]
        common = {
            "cache_key": task["cache_key"],
            "symbol": task["symbol"],
            "canonical_asset_id": task["canonical_asset_id"],
            "archive_type": task["archive_type"],
            "year_month": task["year_month"],
            "url": task["url"],
        }
        if task["cache_key"] == first_task[key]:
            downloaded += 1
            files.append(
                {
                    **common,
                    "path": str(path.resolve()),
                    "status": "downloaded",
                    "http_status": 200,
                    **details,
                }
            )
        else:
            missing += 1
            files.append(
                {
                    **common,
                    "path": str((root / "raw" / "missing" / task["cache_key"]).resolve()),
                    "status": "missing",
                    "http_status": 404,
                }
            )
    manifest = {
        "schema": "trading_mvp_gate_historical_membership_v3_history_collect_manifest_v1",
        "generated_at_utc": "2026-07-17T06:03:00Z",
        "run_id": history["run_id"],
        "plan_path": str(history_path.resolve()),
        "plan_sha256": "unused-fixture-plan-sha",
        "plan_hash": history["plan_hash"],
        "input_merkle_sha256": history["input_merkle_sha256"],
        "output_root": str((root / "raw").resolve()),
        "final": True,
        "decision": READY_FOR_QUALITY_PLAN_DECISION,
        "cache_reused": False,
        "runtime_sec": 1.0,
        "summary": {
            "total_tasks": len(files),
            "completed_tasks": len(files),
            "downloaded": downloaded,
            "cached": 0,
            "missing": missing,
            "error": 0,
            "errors": 0,
        },
        "files": files,
        "data_access_audit": {
            "archive_payload_read": True,
            "prices_parsed": False,
            "returns_read": False,
            "signals_read": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "research_only": True,
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "next_allowed_command": "create_hash_bound_membership_v3_history_quality_planonly",
    }
    manifest["artifact_hash"] = v3_collect_manifest_hash(manifest)
    manifest_path = root / "collect-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return history_path, history, manifest_path, manifest


class GateMembershipV3HistoryPlanTests(unittest.TestCase):
    def test_accepted_source_builds_deterministic_payload_only_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report_path, source_plan, report = _write_v3_source(root)
            first = build_history_plan(
                source_probe_report_path=report_path,
                expected_source_plan_hash=source_plan["plan_hash"],
                expected_source_artifact_hash=report["artifact_hash"],
                output_path=root / "history-plan.json",
                run_id="membership_v3_history_fixture",
                max_runtime_sec=7200,
                generated_at_utc="2026-07-17T06:02:00Z",
            )
            second = build_history_plan(
                source_probe_report_path=report_path,
                expected_source_plan_hash=source_plan["plan_hash"],
                expected_source_artifact_hash=report["artifact_hash"],
                output_path=None,
                run_id="membership_v3_history_fixture",
                max_runtime_sec=7200,
                generated_at_utc="2026-07-17T07:02:00Z",
            )

            self.assertEqual(first["decision"], HISTORY_PLAN_DECISION)
            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertFalse(first["network_calls_now"])
            self.assertFalse(first["data_access_audit"]["archive_payload_read"])
            self.assertFalse(first["data_access_audit"]["returns_read"])
            self.assertEqual(first["universe"]["eligible_count"], 24)
            self.assertEqual(first["split_contract"]["warmup"]["days"], 20)
            self.assertEqual(first["split_contract"]["train"]["days"], 100)
            self.assertEqual(first["split_contract"]["oos"]["days"], 100)
            self.assertEqual(first["split_contract"]["oos"]["folds"], 5)
            self.assertIn("quality_module_sha256", first["code_provenance"])
            self.assertEqual({task["archive_type"] for task in first["archive_tasks"]}, {
                "candlesticks_1h",
                "funding_applies",
            })
            pending = next(
                row for row in first["universe"]["eligible"] if row["symbol"] == "A20_USDT"
            )
            self.assertEqual(pending["lifecycle_end_resolution"], "archive_observed_pending")
            self.assertIsNone(pending["resolved_lifecycle_end_sec"])
            self.assertEqual(pending["acquisition_end_sec"], WINDOW_END)
            known = next(
                row for row in first["universe"]["eligible"] if row["symbol"] == "A23_USDT"
            )
            self.assertEqual(known["lifecycle_end_resolution"], "contract_metadata")
            self.assertEqual(known["resolved_lifecycle_end_sec"], WINDOW_END - 15 * 86_400)
            self.assertIn(first["plan_hash"], first["approval_phrase"])
            self.assertTrue((root / "history-plan.json").is_file())

    def test_rejected_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report_path, source_plan, report = _write_v3_source(root, accepted=False)
            with self.assertRaisesRegex(ValueError, "source probe is not accepted and final"):
                build_history_plan(
                    source_probe_report_path=report_path,
                    expected_source_plan_hash=source_plan["plan_hash"],
                    expected_source_artifact_hash=report["artifact_hash"],
                    output_path=None,
                    run_id="rejected",
                )

    def test_source_report_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report_path, source_plan, _ = _write_v3_source(root)
            with self.assertRaisesRegex(ValueError, "source probe artifact hash mismatch"):
                build_history_plan(
                    source_probe_report_path=report_path,
                    expected_source_plan_hash=source_plan["plan_hash"],
                    expected_source_artifact_hash="0" * 64,
                    output_path=None,
                    run_id="hash-mismatch",
                )

    def test_incomplete_accepted_source_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report_path, source_plan, report = _write_v3_source(root)
            report["quality"]["tasks_completed"] = 0
            report["artifact_hash"] = membership_v3.sha256_json(
                {
                    key: value
                    for key, value in report.items()
                    if key
                    not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
                }
            )
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "source probe task coverage is incomplete"):
                build_history_plan(
                    source_probe_report_path=report_path,
                    expected_source_plan_hash=source_plan["plan_hash"],
                    expected_source_artifact_hash=report["artifact_hash"],
                    output_path=None,
                    run_id="incomplete-source",
                )

    def test_authorizer_rejects_tampered_history_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report_path, source_plan, report = _write_v3_source(root)
            history_path = root / "history-plan.json"
            history = build_history_plan(
                source_probe_report_path=report_path,
                expected_source_plan_hash=source_plan["plan_hash"],
                expected_source_artifact_hash=report["artifact_hash"],
                output_path=history_path,
                run_id="history",
            )
            tampered = json.loads(history_path.read_text(encoding="utf-8"))
            tampered["runtime_contract"]["max_runtime_sec"] = 1
            history_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "history plan hash mismatch"):
                authorize_history_collect(history_path, history["plan_hash"])

    def test_inactive_unknown_lifecycle_is_excluded_not_treated_as_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, source_plan, _ = _write_v3_source(root)
            candidate = source_plan["candidate_universe"]["candidates"][0]
            candidate["active_at_snapshot"] = False
            candidate["lifecycle_status"] = "unknown"

            eligible, excluded = select_history_universe(source_plan)

            self.assertNotIn("A00_USDT", {row["symbol"] for row in eligible})
            self.assertIn(
                {"symbol": "A00_USDT", "base": "A00", "reason": "unresolved_lifecycle_status"},
                excluded,
            )


class GateMembershipV3HistoryCollectorTests(unittest.TestCase):
    def test_collector_downloads_frozen_tasks_without_reading_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report_path, source_plan, report = _write_v3_source(root)
            history_path = root / "history-plan.json"
            history = build_history_plan(
                source_probe_report_path=report_path,
                expected_source_plan_hash=source_plan["plan_hash"],
                expected_source_artifact_hash=report["artifact_hash"],
                output_path=history_path,
                run_id="history",
                max_runtime_sec=60,
            )
            payload = gzip.compress(b"1700000000,1\n")
            manifest = collect_history_archives(
                plan_path=history_path,
                expected_plan_hash=history["plan_hash"],
                output_root=root / "raw",
                manifest_path=root / "manifest.json",
                max_runtime_sec=60,
                max_workers=4,
                min_free_bytes=0,
                fetch_override=lambda _task, _timeout: (200, payload, {}),
            )

            self.assertTrue(manifest["final"])
            self.assertEqual(manifest["decision"], READY_FOR_QUALITY_PLAN_DECISION)
            self.assertEqual(manifest["summary"]["completed_tasks"], len(history["archive_tasks"]))
            self.assertFalse(manifest["data_access_audit"]["returns_read"])
            self.assertEqual(
                manifest["next_allowed_command"],
                "create_hash_bound_membership_v3_history_quality_planonly",
            )


class GateMembershipV3HistoryQualityTests(unittest.TestCase):
    def test_quality_plan_is_deterministic_and_does_not_read_archive_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path, history, manifest_path, manifest = _write_v3_history_collect_fixture(root)
            first = build_quality_plan(
                history_plan_path=history_path,
                expected_history_plan_hash=history["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_path=root / "quality-plan.json",
                run_id="membership_v3_quality_fixture",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T06:04:00Z",
            )
            second = build_quality_plan(
                history_plan_path=history_path,
                expected_history_plan_hash=history["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_path=None,
                run_id="membership_v3_quality_fixture",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T07:04:00Z",
            )

            self.assertEqual(first["decision"], V3_QUALITY_PLAN_DECISION)
            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertFalse(first["data_access_audit"]["archive_payload_read"])
            self.assertFalse(first["data_access_audit"]["returns_computed"])
            self.assertEqual(first["next_allowed_command"], "fast-edge-membership-v3-history-quality")

    def test_quality_resolves_archive_end_and_writes_100_day_sealed_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path, history, manifest_path, manifest = _write_v3_history_collect_fixture(root)
            quality_plan_path = root / "quality-plan.json"
            quality_plan = build_quality_plan(
                history_plan_path=history_path,
                expected_history_plan_hash=history["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_path=quality_plan_path,
                run_id="membership_v3_quality_fixture",
                max_runtime_sec=120,
            )
            result = evaluate_history_quality(
                plan_path=quality_plan_path,
                expected_plan_hash=quality_plan["plan_hash"],
                output_root=root / "normalized",
                report_path=root / "quality-report.json",
                max_runtime_sec=120,
            )

            self.assertEqual(result["decision"], V3_QUALITY_ACCEPTED_DECISION)
            self.assertEqual(result["accepted_assets"], 24)
            self.assertEqual(result["delisted_end_coverage"], 1.0)
            self.assertFalse(result["data_access_audit"]["returns_computed"])
            self.assertFalse(result["oos_allowed"])
            self.assertEqual(
                result["next_allowed_command"],
                "create_hash_bound_gate_membership_momentum_v2_train_planonly",
            )
            pending = next(row for row in result["per_asset"] if row["symbol"] == "A20_USDT")
            self.assertEqual(pending["lifecycle_end_resolution"], "archive_observed_end")
            self.assertIsInstance(pending["resolved_lifecycle_end_sec"], int)
            oos_manifest = json.loads(Path(result["oos_manifest_path"]).read_text(encoding="utf-8"))
            train_manifest = json.loads(Path(result["train_manifest_path"]).read_text(encoding="utf-8"))
            self.assertTrue(oos_manifest["sealed"])
            self.assertEqual(
                oos_manifest["range"]["end_sec"] - oos_manifest["range"]["start_sec"],
                100 * 86_400,
            )
            train_known = next(row for row in train_manifest["universe"] if row["symbol"] == "A23_USDT")
            oos_known = next(row for row in oos_manifest["universe"] if row["symbol"] == "A23_USDT")
            self.assertIsNone(train_known["listed_to_ts"])
            self.assertFalse(train_known["is_delisted"])
            self.assertEqual(train_known["lifecycle_end_resolution"], "not_observed_by_train_boundary")
            self.assertEqual(oos_known["listed_to_ts"], WINDOW_END - 15 * 86_400)
            self.assertTrue(oos_known["is_delisted"])

    def test_archive_observed_end_uses_last_closed_hour_without_inventing_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candles.csv.gz"
            start = WINDOW_START
            _write_gzip(
                path,
                [f"{start + index * 3_600},100,10,11,9,10" for index in range(48)],
            )
            rows, metrics, reasons = normalize_candlestick_archives_v3(
                [path],
                contract_multiplier=0.01,
                acquisition_start_sec=start,
                acquisition_end_sec=WINDOW_END,
                lifecycle_end_resolution="archive_observed_pending",
                resolved_lifecycle_end_sec=None,
            )

            self.assertEqual(reasons, [])
            self.assertEqual(metrics["resolved_lifecycle_end_sec"], start + 48 * 3_600)
            self.assertEqual(metrics["hourly_coverage"], 1.0)
            self.assertEqual(len(rows), 3)

    def test_quality_rejects_when_delisted_end_coverage_is_below_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path, history, manifest_path, manifest = _write_v3_history_collect_fixture(root)
            unresolved_symbols = {"A20_USDT", "A21_USDT", "A22_USDT"}
            # Replace the first candle archive for each unresolved delisting with a
            # valid planned 404 record while keeping the collector inventory complete.
            seen: set[str] = set()
            for record in manifest["files"]:
                symbol = record.get("symbol")
                if symbol not in unresolved_symbols or symbol in seen:
                    continue
                if record.get("archive_type") != "candlesticks_1h" or record.get("status") != "downloaded":
                    continue
                seen.add(symbol)
                for key in ("size_bytes", "sha256", "gzip_valid", "gzip_member_count"):
                    record.pop(key, None)
                record["status"] = "missing"
                record["http_status"] = 404
                record["path"] = str((root / "raw" / "missing" / record["cache_key"]).resolve())
            self.assertEqual(seen, unresolved_symbols)
            manifest["summary"]["downloaded"] -= len(seen)
            manifest["summary"]["missing"] += len(seen)
            manifest["artifact_hash"] = v3_collect_manifest_hash(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            quality_plan_path = root / "quality-plan.json"
            quality_plan = build_quality_plan(
                history_plan_path=history_path,
                expected_history_plan_hash=history["plan_hash"],
                collect_manifest_path=manifest_path,
                expected_collect_artifact_hash=manifest["artifact_hash"],
                output_path=quality_plan_path,
                run_id="membership_v3_quality_low_delisted_coverage",
                max_runtime_sec=120,
            )
            result = evaluate_history_quality(
                plan_path=quality_plan_path,
                expected_plan_hash=quality_plan["plan_hash"],
                output_root=root / "normalized",
                report_path=root / "quality-report.json",
                max_runtime_sec=120,
            )

            self.assertEqual(result["decision"], V3_QUALITY_REJECTED_DECISION)
            self.assertEqual(result["accepted_assets"], 21)
            self.assertEqual(result["delisted_end_coverage"], 0.25)
            self.assertIn("delisted_end_coverage_below_0_90", result["rejection_reasons"])
            self.assertEqual(result["next_allowed_command"], "none_membership_v3_history_branch_closed")

    def test_quality_plan_rejects_manifest_path_outside_collector_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path, history, manifest_path, manifest = _write_v3_history_collect_fixture(root)
            record = next(row for row in manifest["files"] if row["status"] == "downloaded")
            record["path"] = str((root.parent / "outside.csv.gz").resolve())
            manifest["artifact_hash"] = v3_collect_manifest_hash(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "outside collector output root"):
                build_quality_plan(
                    history_plan_path=history_path,
                    expected_history_plan_hash=history["plan_hash"],
                    collect_manifest_path=manifest_path,
                    expected_collect_artifact_hash=manifest["artifact_hash"],
                    output_path=None,
                    run_id="outside-root",
                    max_runtime_sec=120,
                )


class GateMembershipV3HistoryWrapperTests(unittest.TestCase):
    def test_run_mvp_exposes_v3_history_plan_and_visible_collect_route(self) -> None:
        root = Path(__file__).resolve().parents[2]
        wrapper = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((root / "trading_mvp" / "run_mvp.ps1"))

        self.assertIn('"fast-edge-membership-v3-history-plan"', wrapper)
        self.assertIn("gate_historical_membership_v3_history_plan.py", wrapper)
        self.assertIn("ExpectedArtifactHash is required for fast-edge-membership-v3-history-plan", wrapper)
        self.assertIn('"fast-edge-membership-v3-history-collect"', wrapper)
        self.assertIn("start_gate_historical_membership_v3_history_collect_visible.ps1", wrapper)
        self.assertIn("Direct membership-v3 history network execution is disabled", wrapper)
        self.assertIn('"fast-edge-membership-v3-history-quality-plan"', wrapper)
        self.assertIn('"fast-edge-membership-v3-history-quality"', wrapper)
        self.assertIn("gate_historical_membership_v3_history_quality.py", wrapper)

    def test_visible_collect_launcher_is_planonly_and_confirmation_gated(self) -> None:
        root = Path(__file__).resolve().parents[2]
        launcher = (
            root / "tools" / "start_gate_historical_membership_v3_history_collect_visible.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("[switch]$PlanOnly", launcher)
        self.assertIn("[switch]$ConfirmedPublicHistoryCollect", launcher)
        self.assertIn("gate_historical_membership_v3_history_plan.py", launcher)
        self.assertIn("gate_historical_membership_v3_history_collector.py", launcher)
        self.assertIn("network_access = $false", launcher)
        self.assertIn("collect_started = $false", launcher)
        self.assertIn("Start-Process", launcher)
        self.assertIn("-WindowStyle Normal", launcher)
        self.assertIn("STOPPED_INCOMPLETE", launcher)


if __name__ == "__main__":
    unittest.main()
