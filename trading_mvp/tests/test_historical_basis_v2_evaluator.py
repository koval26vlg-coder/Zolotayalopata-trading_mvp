from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2 import (  # noqa: E402
    DAY_SEC,
    HOUR_SEC,
    BasisBar,
    build_historical_basis_v2_plan,
    main as core_main,
)
from historical_basis_code_snapshot import create_basis_code_snapshot  # noqa: E402
from historical_basis_v2_evaluator import (  # noqa: E402
    QUALITY_SCHEMA,
    main as evaluator_main,
    quality_semantic_hash,
    run_hash_bound_evaluation,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asset(index: int) -> dict[str, object]:
    base = f"A{index:02d}"
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": 179,
        "binance_spot": False,
        "categories": [],
        "availability_rank": index,
    }


def _bar(ts: int, base: str, spread_bps: float, cheap_venue: str) -> BasisBar:
    index = 100.0
    high_mark = index * (1.0 + spread_bps / 10_000.0)
    mexc_mark, gate_mark = (
        (index, high_mark) if cheap_venue == "mexc" else (high_mark, index)
    )
    return BasisBar(
        ts=ts,
        base=base,
        mexc_trade_open=100.0,
        mexc_trade_close=100.0,
        mexc_mark_close=mexc_mark,
        mexc_index_close=index,
        mexc_volume_quote=2_000_000.0,
        gateio_trade_open=100.0,
        gateio_trade_close=100.0,
        gateio_mark_close=gate_mark,
        gateio_index_close=index,
        gateio_volume_quote=2_000_000.0,
    )


def _feasible_train_bars() -> list[BasisBar]:
    train_start = 14 * DAY_SEC
    bars: list[BasisBar] = []
    for index in range(20):
        day = index // 2
        slot = index % 2
        base = f"A{index % 8:02d}"
        cheap = "mexc" if index % 2 == 0 else "gateio"
        signal_ts = train_start + day * DAY_SEC + (slot * 6 + 1) * HOUR_SEC
        bars.extend(
            [
                _bar(signal_ts - HOUR_SEC, base, 100.0, cheap),
                _bar(signal_ts, base, 130.0, cheap),
                _bar(signal_ts + HOUR_SEC, base, 130.0, cheap),
                _bar(signal_ts + 2 * HOUR_SEC, base, 10.0, cheap),
                _bar(signal_ts + 3 * HOUR_SEC, base, 10.0, cheap),
            ]
        )
    return sorted(bars, key=lambda row: (row.ts, row.base))


def _write_jsonl(path: Path, rows: list[object]) -> None:
    text = "".join(
        json.dumps(row if isinstance(row, dict) else asdict(row), sort_keys=True) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8")


def _build_fixture(
    root: Path,
    *,
    train_bars: list[BasisBar],
    create_oos: bool,
) -> tuple[dict[str, object], Path, Path]:
    plan_path = root / "plan.json"
    plan = build_historical_basis_v2_plan(
        [_asset(index) for index in range(8)],
        output_path=plan_path,
        window_end_ts=179 * DAY_SEC,
        frozen_at_utc="2026-07-16T00:00:00+00:00",
    )
    candles_path = root / "normalized-candles.jsonl"
    funding_path = root / "funding-events.jsonl"
    train_path = root / "normalized-candles.train.jsonl"
    oos_path = root / "normalized-candles.oos.jsonl"
    _write_jsonl(train_path, train_bars)
    funding_path.write_text("", encoding="utf-8")
    if create_oos:
        _write_jsonl(candles_path, train_bars)
        oos_path.write_text("", encoding="utf-8")
    quality: dict[str, object] = {
        "schema": QUALITY_SCHEMA,
        "verdict": "QUALITY_ACCEPTED_NOT_EVALUATED",
        "plan_hash": plan["plan_hash"],
        "input_file_merkle_sha256": "fixture-input-merkle",
        "primary_assets": [f"A{index:02d}" for index in range(8)],
        "reserve_assets": [],
        "surviving_asset_count": 8,
        "train_row_count": len(train_bars),
        "oos_row_count": 0,
        "funding_event_count": 0,
        "funding_event_merkle_sha256": hashlib.sha256(b"").hexdigest(),
        "output_artifacts": {
            "candles": {
                "path": str(candles_path),
                "sha256": _sha256(candles_path) if create_oos else "0" * 64,
                "rows": len(train_bars),
                "schema": "trading_mvp_historical_basis_v2_normalized_candles_v2",
            },
            "funding": {
                "path": str(funding_path),
                "sha256": _sha256(funding_path),
                "rows": 0,
                "schema": "trading_mvp_historical_basis_v2_funding_events_v2",
            },
            "train": {
                "path": str(train_path),
                "sha256": _sha256(train_path),
                "rows": len(train_bars),
                "range": "[start,end)",
                "start_sec": 14 * DAY_SEC,
                "end_sec": 99 * DAY_SEC,
            },
            "oos": {
                "path": str(oos_path),
                "sha256": _sha256(oos_path) if create_oos else "1" * 64,
                "rows": 0,
                "range": "[start,end)",
                "start_sec": 99 * DAY_SEC,
                "end_sec": 179 * DAY_SEC,
                "sealed": True,
            },
            "report": {
                "path": str(root / "quality.json"),
                "sha256": None,
                "sha256_scope": "canonical_report_payload_with_report_sha256_null",
            },
        },
    }
    quality_hash = quality_semantic_hash(quality)
    quality["output_artifacts"]["report"]["sha256"] = quality_hash  # type: ignore[index]
    quality["report_payload_sha256"] = quality_hash
    quality_path = root / "quality.json"
    quality_path.write_text(json.dumps(quality, sort_keys=True), encoding="utf-8")
    return plan, plan_path, quality_path


class HistoricalBasisV2OwnedEvaluatorTests(unittest.TestCase):
    def test_evaluator_rejects_runtime_snapshot_different_from_frozen_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen_source = root / "frozen-src"
            frozen_source.mkdir()
            (frozen_source / "historical_basis_v2.py").write_text(
                "FROZEN = True\n", encoding="utf-8"
            )
            snapshot = create_basis_code_snapshot(frozen_source, root / "snapshots")
            plan_path = root / "plan.json"
            plan = build_historical_basis_v2_plan(
                [_asset(index) for index in range(8)],
                output_path=plan_path,
                window_end_ts=179 * DAY_SEC,
                frozen_at_utc="2026-07-16T00:00:00+00:00",
                code_snapshot_hash=str(snapshot["code_snapshot_hash"]),
                code_snapshot_manifest=str(snapshot["manifest_path"]),
            )

            with self.assertRaisesRegex(
                ValueError, "frozen plan requires immutable code snapshot execution"
            ):
                run_hash_bound_evaluation(
                    plan_path=plan_path,
                    quality_report_path=root / "missing-quality.json",
                    output_path=root / "result.json",
                    stage="train_feasibility",
                    expected_plan_hash=str(plan["plan_hash"]),
                    max_runtime_sec=60,
                )

    def test_train_feasibility_does_not_open_or_hash_oos_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=_feasible_train_bars(),
                create_oos=False,
            )
            result = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "feasibility.json",
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            self.assertEqual(result["verdict"], "FEASIBLE_FOR_OOS")
            self.assertFalse(result["oos_read"])
            self.assertEqual(result["data_access_audit"]["oos_files_opened"], False)
            self.assertEqual(result["data_access_audit"]["oos_rows_read"], 0)
            self.assertEqual(result["oos_seal"]["bars_sha256"], "1" * 64)
            self.assertEqual(
                result["oos_seal"]["funding_sha256"],
                hashlib.sha256(b"").hexdigest(),
            )

    def test_full_evaluation_rejects_unaccepted_feasibility_before_oos_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=[],
                create_oos=False,
            )
            feasibility_path = root / "feasibility.json"
            run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=feasibility_path,
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            with self.assertRaisesRegex(ValueError, "not FEASIBLE_FOR_OOS"):
                run_hash_bound_evaluation(
                    plan_path=plan_path,
                    quality_report_path=quality_path,
                    output_path=root / "full.json",
                    stage="full_evaluation",
                    feasibility_path=feasibility_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    max_runtime_sec=60,
                )

    def test_full_evaluation_requires_hash_bound_feasibility_and_reads_sealed_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=_feasible_train_bars(),
                create_oos=True,
            )
            feasibility_path = root / "feasibility.json"
            feasibility = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=feasibility_path,
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            self.assertEqual(feasibility["verdict"], "FEASIBLE_FOR_OOS")
            result = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "full.json",
                stage="full_evaluation",
                feasibility_path=feasibility_path,
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
            self.assertEqual(
                result["rejection_reasons"],
                ["oos_independent_episodes_below_40"],
            )
            self.assertTrue(result["oos_read"])
            self.assertTrue(result["data_access_audit"]["oos_files_opened"])

    def test_feasibility_artifact_is_bound_to_unchanged_quality_and_oos_seal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=_feasible_train_bars(),
                create_oos=True,
            )
            feasibility_path = root / "feasibility.json"
            run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=feasibility_path,
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            quality["output_artifacts"]["oos"]["sha256"] = "f" * 64
            quality_hash = quality_semantic_hash(quality)
            quality["output_artifacts"]["report"]["sha256"] = quality_hash
            quality["report_payload_sha256"] = quality_hash
            quality_path.write_text(json.dumps(quality, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "feasibility quality provenance mismatch"):
                run_hash_bound_evaluation(
                    plan_path=plan_path,
                    quality_report_path=quality_path,
                    output_path=root / "full.json",
                    stage="full_evaluation",
                    feasibility_path=feasibility_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    max_runtime_sec=60,
                )

    def test_quality_v2_funding_path_is_derived_and_hash_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=[],
                create_oos=True,
            )
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            funding_path = Path(quality["output_artifacts"]["funding"]["path"])
            funding_path.write_text('{"tampered":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "funding ledger hash mismatch"):
                run_hash_bound_evaluation(
                    plan_path=plan_path,
                    quality_report_path=quality_path,
                    output_path=root / "feasibility.json",
                    stage="train_feasibility",
                    expected_plan_hash=str(plan["plan_hash"]),
                    max_runtime_sec=60,
                )

    def test_deterministic_result_hash_ignores_runtime_and_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=_feasible_train_bars(),
                create_oos=False,
            )
            first = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "first.json",
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            second = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "second.json",
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            self.assertEqual(
                first["deterministic_result_hash"],
                second["deterministic_result_hash"],
            )

    def test_full_result_hash_depends_on_feasibility_content_not_file_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=_feasible_train_bars(),
                create_oos=True,
            )
            feasibility_path = root / "feasibility.json"
            run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=feasibility_path,
                stage="train_feasibility",
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            copied_feasibility = root / "copied-feasibility.json"
            shutil.copyfile(feasibility_path, copied_feasibility)
            first = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "full-first.json",
                stage="full_evaluation",
                feasibility_path=feasibility_path,
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            second = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "full-second.json",
                stage="full_evaluation",
                feasibility_path=copied_feasibility,
                expected_plan_hash=str(plan["plan_hash"]),
                max_runtime_sec=60,
            )
            self.assertEqual(
                first["deterministic_result_hash"],
                second["deterministic_result_hash"],
            )

    def test_core_evaluate_subcommand_accepts_explicit_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, quality_path = _build_fixture(
                root,
                train_bars=[],
                create_oos=False,
            )
            output = root / "cli-feasibility.json"
            with redirect_stdout(io.StringIO()):
                status = core_main(
                    [
                        "evaluate",
                        "--plan",
                        str(plan_path),
                        "--quality-report",
                        str(quality_path),
                        "--output",
                        str(output),
                        "--stage",
                        "train_feasibility",
                        "--expected-plan-hash",
                        str(plan["plan_hash"]),
                        "--max-runtime-sec",
                        "60",
                    ]
                )
            self.assertEqual(status, 0)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["stage"],
                "train_feasibility",
            )

    def test_evaluator_cli_allows_feasibility_only_for_full_evaluation(self) -> None:
        common = [
            "--plan",
            "missing-plan.json",
            "--quality-report",
            "missing-quality.json",
            "--output",
            "missing-output.json",
        ]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                evaluator_main(
                    [
                        *common,
                        "--stage",
                        "train_feasibility",
                        "--feasibility",
                        "not-allowed.json",
                    ]
                )
            with self.assertRaises(SystemExit):
                evaluator_main([*common, "--stage", "full_evaluation"])


if __name__ == "__main__":
    unittest.main()
