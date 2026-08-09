from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
TRADING_ROOT = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import gate_membership_momentum_v2_execution_probe as probe  # noqa: E402
import gate_membership_momentum_v2_execution_probe_runtime as probe_runtime  # noqa: E402
import gate_membership_momentum_v2_execution_selection as selection  # noqa: E402
import gate_membership_momentum_v2_paper_plan as paper_plan  # noqa: E402
import gate_historical_membership_v3_history_plan as v3_history_plan  # noqa: E402
from gate_membership_momentum import DAY_SEC  # noqa: E402
from test_gate_membership_momentum_v2_execution_selection import _snapshot  # noqa: E402
from test_gate_membership_momentum_v2_execution_probe_runtime import (  # noqa: E402
    _selection as _execution_selection,
    _window_plan as _execution_window_plan,
)


STATE_MODULE_AVAILABLE = importlib.util.find_spec(
    "gate_membership_momentum_v2_paper_state"
) is not None
paper_state = (
    importlib.import_module("gate_membership_momentum_v2_paper_state")
    if STATE_MODULE_AVAILABLE
    else None
)


TEST_WINDOW_DURATION_SEC = 15
TEST_MINIMUM_VALID_SNAPSHOTS = 3


def _write_execution_probe_samples(plan: dict) -> None:
    window = plan["window_contract"]
    expected_cycles = int(window["expected_cycles"])
    interval_sec = int(window["interval_sec"])
    start_ts = int(window["start_ts"])
    samples_path = Path(plan["output_contract"]["samples_path"])
    with samples_path.open("x", encoding="utf-8") as handle:
        for cycle in range(1, expected_cycles + 1):
            timestamp = start_ts + (cycle - 1) * interval_sec
            for position in plan["selected_positions"]:
                handle.write(
                    json.dumps(
                        {
                            "schema": probe_runtime.SAMPLE_SCHEMA,
                            "window_plan_hash": plan["plan_hash"],
                            "selection_hash": plan["selection_authorization"][
                                "artifact_hash"
                            ],
                            "window_index": int(window["index"]),
                            "cycle": cycle,
                            "scheduled_ts": timestamp,
                            **position,
                            "request_started_ts": timestamp,
                            "received_ts": timestamp + 0.1,
                            "exchange_ts": timestamp,
                            "timestamp_skew_ms": 0.0,
                            "bids": [[100.0, 100_000.0]],
                            "asks": [[100.0, 100_000.0]],
                            "collection_error": None,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )


def _accepted_execution_report(root: Path) -> tuple[Path, dict]:
    probe_path, probe_plan, selection_path, selection_result = _execution_selection(root)
    manifests: list[Path] = []
    for window_index in range(probe.WINDOW_COUNT):
        plan_path, window_plan = _execution_window_plan(
            root,
            probe_path=probe_path,
            probe_plan=probe_plan,
            selection_path=selection_path,
            selection_result=selection_result,
            window_index=window_index,
        )
        _write_execution_probe_samples(window_plan)
        expected_cycles = int(window_plan["window_contract"]["expected_cycles"])
        probe_runtime.finalize_execution_probe_window(
            plan_path=plan_path,
            expected_plan_hash=window_plan["plan_hash"],
            completed_cycles=expected_cycles,
            errors=[],
            critical_errors=[],
            runtime_sec=float(window_plan["window_contract"]["duration_sec"]),
        )
        manifests.append(Path(window_plan["output_contract"]["manifest_path"]))
    report_path = root / "execution-report.json"
    report = probe_runtime.evaluate_execution_probe_windows(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=probe_plan["plan_hash"],
        selection_path=selection_path,
        expected_selection_hash=selection_result["artifact_hash"],
        manifest_paths=manifests,
        output_path=report_path,
    )
    return report_path, report


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _paper_chain(root: Path) -> tuple[Path, dict, Path, dict]:
    report_root = root / "accepted"
    report_root.mkdir()
    report_path, report = _accepted_execution_report(report_root)
    plan_path = root / "paper-plan.json"
    plan = paper_plan.build_paper_plan(
        execution_report_path=report_path,
        expected_execution_report_hash=report["deterministic_result_hash"],
        output_path=plan_path,
        run_id="membership-momentum-v2-paper-state",
        generated_at_utc="2026-07-17T13:00:00Z",
    )
    approval_path = root / "paper-approval.json"
    approval = paper_state.create_paper_approval(
        plan_path=plan_path,
        expected_plan_hash=plan["plan_hash"],
        output_path=approval_path,
        confirmed_paper_forward=True,
        approved_at_utc="2026-07-17T13:05:00Z",
    )
    return plan_path, plan, approval_path, approval


def _future_selection(
    root: Path,
    *,
    paper: dict,
    event_index: int,
) -> tuple[Path, dict]:
    event_root = root / f"event-{event_index:02d}"
    event_root.mkdir()
    original_probe_path = Path(
        paper["execution_report_authorization"]["path"]
    ).expanduser().resolve()
    execution_report = json.loads(original_probe_path.read_text(encoding="utf-8"))
    base_probe_path = Path(execution_report["probe_plan"]["path"])
    base_probe = probe.validate_execution_probe_plan(
        base_probe_path,
        execution_report["probe_plan"]["plan_hash"],
    )
    historical = base_probe["historical_authorization"]
    signal_day = int(paper["paper_contract"]["first_paper_signal_day"]) + (
        event_index * int(paper["paper_contract"]["event_cadence_days"])
    )
    probe_path = event_root / "probe-plan.json"
    future_probe = probe.build_execution_probe_plan(
        oos_plan_path=historical["oos_plan_path"],
        expected_oos_plan_hash=historical["oos_plan_hash"],
        oos_result_path=historical["oos_result_path"],
        expected_oos_result_hash=historical["oos_result_hash"],
        output_path=probe_path,
        run_id=f"paper-event-{event_index:02d}",
        not_before_day=signal_day,
        generated_at_utc="2026-07-17T13:10:00Z",
    )
    snapshot_path, snapshot = _snapshot(event_root, future_probe)
    selected_path = event_root / "selection.json"
    selected = selection.build_selection_artifact(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=future_probe["plan_hash"],
        market_snapshot_manifest_path=snapshot_path,
        expected_market_snapshot_hash=snapshot["artifact_hash"],
        output_path=selected_path,
        generated_at_utc=_iso(
            int(future_probe["target_event_contract"]["target_signal_close_ts"])
            + 120
        ),
    )
    return selected_path, selected


def _write_paper_raw_manifest(
    root: Path,
    *,
    plan: dict,
    selected: dict,
    source_type: str,
    coverage: float = 0.90,
    include_manual_pnl: bool = False,
    execution_ts_offset_sec: int = 0,
) -> tuple[Path, dict, Path]:
    if source_type == "funding_settlements":
        raise AssertionError("funding fixtures must use the history-derived adapter")
    entry_ts = int(selected["target_event_contract"]["target_entry_ts"]) + 900
    exit_ts = entry_ts + int(plan["paper_contract"]["hold_days"]) * DAY_SEC
    rows = []
    for row in selected["selected_positions"]:
        identity = {
            "canonical_asset_id": row["canonical_asset_id"],
            "symbol": row["symbol"],
            "base": row["base"],
            "side": str(row["side"]),
        }
        is_entry = source_type == "entry_execution"
        source_row = {
            **identity,
            "execution_ts": (
                entry_ts if is_entry else exit_ts
            )
            + int(execution_ts_offset_sec),
            "executable_price": (
                100.0
                if is_entry
                else (101.0 if identity["side"] == "long" else 99.0)
            ),
            "execution_metrics": {
                "valid_snapshots": 200,
                "coverage": coverage,
                "p95_impact_bps": 5.0,
                "capacity_quote": 1_000.0,
                "max_timestamp_skew_ms": 100.0,
                "max_quote_age_ms": 1_000.0,
                "critical_error_count": 0,
            },
        }
        if include_manual_pnl:
            source_row["net_pnl_quote"] = 999_999.0
        rows.append(source_row)
    raw_path = root / f"{source_type}.raw.json"
    funding_coverage = 1.0 if source_type == "funding_settlements" else None
    raw_path.write_text(
        json.dumps(
            {
                "schema": paper_state.PAPER_RAW_INPUT_SCHEMA,
                "source_type": source_type,
                "paper_plan_hash": plan["plan_hash"],
                "selection_hash": selected["artifact_hash"],
                "signal_day": int(
                    selected["target_event_contract"]["target_signal_day"]
                ),
                "public_data_only": True,
                "live_orders": False,
                "private_api_keys": False,
                "leverage_or_margin": False,
                "rows": rows,
                "funding_settlement_coverage": funding_coverage,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    raw_hash = v3_history_plan.sha256_file(raw_path)
    for row in rows:
        metrics = row.get("execution_metrics")
        if isinstance(metrics, dict):
            metrics["evidence_hash"] = raw_hash
    raw_body = {
        "schema": paper_state.PAPER_RAW_SOURCE_SCHEMA,
        "final": True,
        "decision": paper_state.PAPER_RAW_SOURCE_READY_DECISION,
        "source_type": source_type,
        "paper_plan_hash": plan["plan_hash"],
        "selection_hash": selected["artifact_hash"],
        "signal_day": int(selected["target_event_contract"]["target_signal_day"]),
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "input_artifacts": [
            {"path": str(raw_path.resolve()), "file_sha256": raw_hash}
        ],
        "rows": rows,
        "funding_settlement_coverage": (
            funding_coverage
        ),
    }
    raw_manifest = {
        **raw_body,
        "generated_at_utc": "2026-07-17T13:18:00Z",
        "artifact_hash": paper_state.paper_raw_source_hash(raw_body),
        "frozen_contract": raw_body,
    }
    raw_manifest_path = root / f"{source_type}.raw-manifest.json"
    raw_manifest_path.write_text(
        json.dumps(raw_manifest, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    return raw_manifest_path, raw_manifest, raw_path


def _write_paper_source(
    root: Path,
    *,
    plan: dict,
    selected: dict,
    source_type: str,
    coverage: float = 0.90,
    include_manual_pnl: bool = False,
    execution_ts_offset_sec: int = 0,
) -> tuple[Path, dict, Path]:
    raw_manifest_path, raw_manifest, raw_path = _write_paper_raw_manifest(
        root,
        plan=plan,
        selected=selected,
        source_type=source_type,
        coverage=coverage,
        include_manual_pnl=include_manual_pnl,
        execution_ts_offset_sec=execution_ts_offset_sec,
    )
    source_path = root / f"{source_type}.json"
    artifact = paper_state.build_paper_source_artifact(
        raw_manifest_path=raw_manifest_path,
        expected_raw_manifest_hash=raw_manifest["artifact_hash"],
        output_path=source_path,
        generated_at_utc="2026-07-17T13:18:30Z",
    )
    return source_path, artifact, raw_path


def _write_paper_funding_source(
    root: Path,
    *,
    selected: dict,
    entry_source_path: Path,
    entry_source: dict,
    exit_source_path: Path,
    exit_source: dict,
    missing_settlement: bool = False,
) -> tuple[Path, dict, Path]:
    histories = []
    first_settlement = int(selected["target_event_contract"]["target_entry_ts"]) + (
        8 * 60 * 60
    )
    for selected_row in selected["selected_positions"]:
        rows = [
            {
                "ts": first_settlement + index * 8 * 60 * 60,
                "funding_rate": 0.0,
            }
            for index in range(21)
        ]
        if missing_settlement:
            rows.pop(10)
        history_path = root / f"{selected_row['symbol']}.funding.json"
        history_path.write_text(
            json.dumps(
                {
                    "schema": "trading_mvp_funding_settlements_v1",
                    "exchange": "gateio",
                    "symbol": selected_row["symbol"],
                    "rows": rows,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        histories.append(history_path)
    raw_path = root / "funding_settlements.raw.json"
    raw_manifest_path = root / "funding_settlements.raw-manifest.json"
    raw_manifest = paper_state.build_paper_funding_raw_source_manifest(
        entry_source_path=entry_source_path,
        expected_entry_source_hash=entry_source["artifact_hash"],
        exit_source_path=exit_source_path,
        expected_exit_source_hash=exit_source["artifact_hash"],
        funding_history_paths=histories,
        raw_input_path=raw_path,
        raw_manifest_path=raw_manifest_path,
        generated_at_utc="2026-07-17T13:18:15Z",
    )
    source_path = root / "funding_settlements.json"
    source = paper_state.build_paper_source_artifact(
        raw_manifest_path=raw_manifest_path,
        expected_raw_manifest_hash=raw_manifest["artifact_hash"],
        output_path=source_path,
        generated_at_utc="2026-07-17T13:18:30Z",
    )
    return source_path, source, raw_path


def _write_paper_boundary_manifests(
    root: Path,
    *,
    plan_path: Path,
    plan: dict,
    approval_path: Path,
    selected_path: Path,
    selected: dict,
    boundary: str,
) -> tuple[list[Path], list[Path], list[dict]]:
    manifest_paths: list[Path] = []
    sample_paths: list[Path] = []
    window_plans: list[dict] = []
    for window_index in range(3):
        window_root = root / f"{boundary}-window-{window_index}"
        window_root.mkdir(parents=True)
        window_plan_path = window_root / "plan.json"
        samples_path = window_root / "samples.jsonl"
        manifest_path = window_root / "manifest.json"
        window_plan = probe_runtime.build_paper_boundary_window_collect_plan(
            paper_plan_path=plan_path,
            expected_paper_plan_hash=plan["plan_hash"],
            approval_path=approval_path,
            selection_path=selected_path,
            expected_selection_hash=selected["artifact_hash"],
            boundary=boundary,
            output_path=window_plan_path,
            samples_path=samples_path,
            manifest_path=manifest_path,
            run_id=f"paper-{boundary}-{window_index}",
            window_index=window_index,
            max_runtime_sec=1_800,
            workers=2,
            generated_at_utc="2026-07-17T13:16:00Z",
        )
        start_ts = int(window_plan["window_contract"]["start_ts"])
        interval_sec = int(window_plan["window_contract"]["interval_sec"])
        expected_cycles = int(window_plan["window_contract"]["expected_cycles"])
        with samples_path.open("x", encoding="utf-8") as handle:
            for cycle in range(1, expected_cycles + 1):
                exchange_ts = start_ts + (cycle - 1) * interval_sec + 1
                for position in window_plan["selected_positions"]:
                    if boundary == "exit" and position["side"] == "long":
                        bids, asks = [[110.0, 100_000.0]], [[110.2, 100_000.0]]
                    elif boundary == "exit" and position["side"] == "short":
                        bids, asks = [[89.8, 100_000.0]], [[90.0, 100_000.0]]
                    else:
                        bids, asks = [[99.9, 100_000.0]], [[100.1, 100_000.0]]
                    handle.write(
                        json.dumps(
                            {
                                "schema": probe_runtime.SAMPLE_SCHEMA,
                                "window_plan_hash": window_plan["plan_hash"],
                                "selection_hash": selected["artifact_hash"],
                                "window_index": window_index,
                                "cycle": cycle,
                                "scheduled_ts": start_ts + (cycle - 1) * interval_sec,
                                **position,
                                "request_started_ts": exchange_ts - 0.1,
                                "received_ts": exchange_ts + 0.1,
                                "exchange_ts": exchange_ts,
                                "timestamp_skew_ms": 0.0,
                                "bids": bids,
                                "asks": asks,
                                "collection_error": None,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
        manifest = probe_runtime.finalize_execution_probe_window(
            plan_path=window_plan_path,
            expected_plan_hash=window_plan["plan_hash"],
            completed_cycles=expected_cycles,
            errors=[],
            critical_errors=[],
            runtime_sec=1_200.0,
        )
        self_hash = manifest["deterministic_result_hash"]
        assert self_hash
        manifest_paths.append(manifest_path)
        sample_paths.append(samples_path)
        window_plans.append(window_plan)
    return manifest_paths, sample_paths, window_plans


def _paper_evidence(
    *,
    plan_path: Path,
    plan: dict,
    approval_path: Path,
    selected_path: Path,
    selected: dict,
) -> tuple[Path, dict, list[Path]]:
    entry_depth_root = selected_path.parent / "entry-depth-evidence"
    exit_depth_root = selected_path.parent / "exit-depth-evidence"
    entry_depth_root.mkdir()
    exit_depth_root.mkdir()
    entry_manifests, _entry_samples, _entry_plans = _write_paper_boundary_manifests(
        entry_depth_root,
        plan_path=plan_path,
        plan=plan,
        approval_path=approval_path,
        selected_path=selected_path,
        selected=selected,
        boundary="entry",
    )
    entry_raw = entry_depth_root / "entry_execution.raw.json"
    entry_raw_manifest_path = entry_depth_root / "entry_execution.raw-manifest.json"
    entry_raw_manifest = paper_state.build_paper_execution_raw_source_manifest(
        paper_plan_path=plan_path,
        expected_paper_plan_hash=plan["plan_hash"],
        approval_path=approval_path,
        selection_path=selected_path,
        expected_selection_hash=selected["artifact_hash"],
        boundary="entry",
        window_manifest_paths=entry_manifests,
        raw_input_path=entry_raw,
        raw_manifest_path=entry_raw_manifest_path,
        generated_at_utc="2026-07-17T13:18:00Z",
    )
    entry_path = entry_depth_root / "entry_execution.json"
    entry = paper_state.build_paper_source_artifact(
        raw_manifest_path=entry_raw_manifest_path,
        expected_raw_manifest_hash=entry_raw_manifest["artifact_hash"],
        output_path=entry_path,
        generated_at_utc="2026-07-17T13:18:30Z",
    )
    exit_manifests, _exit_samples, _exit_plans = _write_paper_boundary_manifests(
        exit_depth_root,
        plan_path=plan_path,
        plan=plan,
        approval_path=approval_path,
        selected_path=selected_path,
        selected=selected,
        boundary="exit",
    )
    exit_raw = exit_depth_root / "exit_execution.raw.json"
    exit_raw_manifest_path = exit_depth_root / "exit_execution.raw-manifest.json"
    exit_raw_manifest = paper_state.build_paper_execution_raw_source_manifest(
        paper_plan_path=plan_path,
        expected_paper_plan_hash=plan["plan_hash"],
        approval_path=approval_path,
        selection_path=selected_path,
        expected_selection_hash=selected["artifact_hash"],
        boundary="exit",
        window_manifest_paths=exit_manifests,
        raw_input_path=exit_raw,
        raw_manifest_path=exit_raw_manifest_path,
        generated_at_utc="2026-07-24T13:18:00Z",
    )
    exit_path = exit_depth_root / "exit_execution.json"
    exit_source = paper_state.build_paper_source_artifact(
        raw_manifest_path=exit_raw_manifest_path,
        expected_raw_manifest_hash=exit_raw_manifest["artifact_hash"],
        output_path=exit_path,
        generated_at_utc="2026-07-24T13:18:30Z",
    )
    funding_path, _funding, funding_raw = _write_paper_funding_source(
        selected_path.parent,
        selected=selected,
        entry_source_path=entry_path,
        entry_source=entry,
        exit_source_path=exit_path,
        exit_source=exit_source,
    )
    source_paths = [entry_path, exit_path, funding_path]
    raw_paths = [entry_raw, exit_raw, funding_raw]
    evidence_path = selected_path.parent / "paper-evidence.json"
    evidence = paper_state.build_paper_evidence_artifact(
        plan_path=plan_path,
        expected_plan_hash=plan["plan_hash"],
        approval_path=approval_path,
        selection_path=selected_path,
        expected_selection_hash=selected["artifact_hash"],
        source_paths=source_paths,
        output_path=evidence_path,
        generated_at_utc="2026-07-17T13:19:00Z",
    )
    return evidence_path, evidence, raw_paths


class GateMembershipMomentumV2PaperStateModuleTests(unittest.TestCase):
    def test_paper_state_module_exists(self) -> None:
        self.assertTrue(
            STATE_MODULE_AVAILABLE,
            "momentum-v2 paper approval/state module is missing",
        )


@unittest.skipUnless(STATE_MODULE_AVAILABLE, "paper state module is not implemented yet")
class GateMembershipMomentumV2PaperStateTests(unittest.TestCase):
    def setUp(self) -> None:
        # Exact production-contract values are covered by execution-probe tests.
        # Paper-state tests keep the same three-window shape with a small fixture.
        for patcher in (
            mock.patch.object(probe, "WINDOW_DURATION_SEC", TEST_WINDOW_DURATION_SEC),
            mock.patch.object(
                probe,
                "MINIMUM_VALID_SNAPSHOTS_PER_ASSET_PER_WINDOW",
                TEST_MINIMUM_VALID_SNAPSHOTS,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        # The accepted report is immutable within a test. Raw and sample files
        # remain uncached so the provenance-tampering assertions still run live.
        original_report_validator = paper_plan._validate_execution_report
        report_cache: dict[tuple[str, str], tuple[str, tuple]] = {}

        def cached_report_validator(path: str | Path, expected_hash: str) -> tuple:
            resolved = Path(path).expanduser().resolve()
            key = (str(resolved), str(expected_hash))
            file_hash = v3_history_plan.sha256_file(resolved)
            cached = report_cache.get(key)
            if cached is not None and cached[0] == file_hash:
                return cached[1]
            validated = original_report_validator(resolved, expected_hash)
            report_cache[key] = (file_hash, validated)
            return validated

        report_patcher = mock.patch.object(
            paper_plan,
            "_validate_execution_report",
            side_effect=cached_report_validator,
        )
        report_patcher.start()
        self.addCleanup(report_patcher.stop)

    def test_approval_requires_exact_hash_and_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_root = root / "accepted"
            report_root.mkdir()
            report_path, report = _accepted_execution_report(report_root)
            plan_path = root / "paper-plan.json"
            plan = paper_plan.build_paper_plan(
                execution_report_path=report_path,
                expected_execution_report_hash=report["deterministic_result_hash"],
                output_path=plan_path,
                run_id="approval-boundary",
            )
            with self.assertRaisesRegex(ValueError, "explicit"):
                paper_state.create_paper_approval(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    output_path=root / "approval.json",
                    confirmed_paper_forward=False,
                )
            with self.assertRaisesRegex(ValueError, "hash"):
                paper_state.create_paper_approval(
                    plan_path=plan_path,
                    expected_plan_hash="0" * 64,
                    output_path=root / "approval.json",
                    confirmed_paper_forward=True,
                )

    def test_event_rejects_manual_pnl_and_unbound_execution_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)
            manual_manifest_path, manual_manifest, _raw = _write_paper_raw_manifest(
                selected_path.parent,
                plan=plan,
                selected=selected,
                source_type="entry_execution",
                include_manual_pnl=True,
            )
            with self.assertRaisesRegex(ValueError, "manual PnL"):
                paper_state.build_paper_source_artifact(
                    raw_manifest_path=manual_manifest_path,
                    expected_raw_manifest_hash=manual_manifest["artifact_hash"],
                    output_path=selected_path.parent / "manual-source.json",
                )
            exit_path, exit_source, _raw = _write_paper_source(
                selected_path.parent,
                plan=plan,
                selected=selected,
                source_type="exit_execution",
            )
            low_quality_path, low_quality, _raw = _write_paper_source(
                selected_path.parent,
                plan=plan,
                selected=selected,
                source_type="entry_execution",
                coverage=0.1,
            )
            funding_path, _funding, _raw = _write_paper_funding_source(
                selected_path.parent,
                selected=selected,
                entry_source_path=low_quality_path,
                entry_source=low_quality,
                exit_source_path=exit_path,
                exit_source=exit_source,
            )
            with self.assertRaisesRegex(ValueError, "depth-window derivation"):
                paper_state.build_paper_evidence_artifact(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    approval_path=approval_path,
                    selection_path=selected_path,
                    expected_selection_hash=selected["artifact_hash"],
                    source_paths=[low_quality_path, exit_path, funding_path],
                    output_path=None,
                )

    def test_source_rejects_rehashed_rows_not_derived_from_raw_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _plan_path, plan, _approval_path, _approval = _paper_chain(root)
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)
            source_path, _source, _raw_path = _write_paper_source(
                selected_path.parent,
                plan=plan,
                selected=selected,
                source_type="entry_execution",
            )
            tampered = json.loads(source_path.read_text(encoding="utf-8"))
            tampered["rows"][0]["executable_price"] = 1_000_000.0
            tampered["frozen_contract"]["rows"][0]["executable_price"] = 1_000_000.0
            tampered["artifact_hash"] = paper_state.paper_source_hash(
                tampered["frozen_contract"]
            )
            source_path.write_text(
                json.dumps(tampered, sort_keys=True, allow_nan=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "raw manifest derivation"):
                paper_state.validate_paper_source_artifact(source_path)

    def test_funding_adapter_is_history_derived_and_transitively_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _plan_path, plan, _approval_path, _approval = _paper_chain(root)
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)
            source_root = selected_path.parent / "funding-adapter"
            source_root.mkdir()
            entry_path, entry, _raw = _write_paper_source(
                source_root,
                plan=plan,
                selected=selected,
                source_type="entry_execution",
            )
            exit_path, exit_source, _raw = _write_paper_source(
                source_root,
                plan=plan,
                selected=selected,
                source_type="exit_execution",
            )
            funding_path, funding, _raw = _write_paper_funding_source(
                source_root,
                selected=selected,
                entry_source_path=entry_path,
                entry_source=entry,
                exit_source_path=exit_path,
                exit_source=exit_source,
            )
            self.assertEqual(funding["funding_settlement_coverage"], 1.0)
            self.assertEqual(len(funding["rows"][0]["settlements"]), 21)
            history_path = sorted(source_root.glob("*.funding.json"))[0]
            history = json.loads(history_path.read_text(encoding="utf-8"))
            history["rows"][0]["funding_rate"] = 0.123
            history_path.write_text(json.dumps(history, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "funding history file hash mismatch"):
                paper_state.validate_paper_source_artifact(funding_path)

    def test_execution_adapter_derives_three_windows_price_and_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)

            entry_root = selected_path.parent / "entry-depth"
            entry_root.mkdir()
            entry_manifests, entry_samples, entry_plans = _write_paper_boundary_manifests(
                entry_root,
                plan_path=plan_path,
                plan=plan,
                approval_path=approval_path,
                selected_path=selected_path,
                selected=selected,
                boundary="entry",
            )
            entry_raw_path = entry_root / "entry.raw.json"
            entry_raw_manifest_path = entry_root / "entry.raw-manifest.json"
            entry_raw_manifest = paper_state.build_paper_execution_raw_source_manifest(
                paper_plan_path=plan_path,
                expected_paper_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                selection_path=selected_path,
                expected_selection_hash=selected["artifact_hash"],
                boundary="entry",
                window_manifest_paths=entry_manifests,
                raw_input_path=entry_raw_path,
                raw_manifest_path=entry_raw_manifest_path,
                generated_at_utc="2026-07-17T13:18:00Z",
            )
            entry_source_path = entry_root / "entry-source.json"
            entry_source = paper_state.build_paper_source_artifact(
                raw_manifest_path=entry_raw_manifest_path,
                expected_raw_manifest_hash=entry_raw_manifest["artifact_hash"],
                output_path=entry_source_path,
                generated_at_utc="2026-07-17T13:18:30Z",
            )
            self.assertEqual(entry_source["source_type"], "entry_execution")
            expected_entry_ts = int(entry_plans[0]["window_contract"]["start_ts"]) + 1
            for row in entry_source["rows"]:
                self.assertEqual(row["execution_ts"], expected_entry_ts)
                self.assertEqual(row["execution_metrics"]["window_count"], 3)
                expected_price = 100.1 if row["side"] == "long" else 99.9
                self.assertAlmostEqual(row["executable_price"], expected_price)

            exit_root = selected_path.parent / "exit-depth"
            exit_root.mkdir()
            exit_manifests, _exit_samples, exit_plans = _write_paper_boundary_manifests(
                exit_root,
                plan_path=plan_path,
                plan=plan,
                approval_path=approval_path,
                selected_path=selected_path,
                selected=selected,
                boundary="exit",
            )
            hold_sec = int(plan["paper_contract"]["hold_days"]) * DAY_SEC
            self.assertEqual(
                int(exit_plans[0]["window_contract"]["start_ts"])
                - int(entry_plans[0]["window_contract"]["start_ts"]),
                hold_sec,
            )
            exit_raw_path = exit_root / "exit.raw.json"
            exit_raw_manifest_path = exit_root / "exit.raw-manifest.json"
            exit_raw_manifest = paper_state.build_paper_execution_raw_source_manifest(
                paper_plan_path=plan_path,
                expected_paper_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                selection_path=selected_path,
                expected_selection_hash=selected["artifact_hash"],
                boundary="exit",
                window_manifest_paths=exit_manifests,
                raw_input_path=exit_raw_path,
                raw_manifest_path=exit_raw_manifest_path,
                generated_at_utc="2026-07-24T13:18:00Z",
            )
            exit_source_path = exit_root / "exit-source.json"
            exit_source = paper_state.build_paper_source_artifact(
                raw_manifest_path=exit_raw_manifest_path,
                expected_raw_manifest_hash=exit_raw_manifest["artifact_hash"],
                output_path=exit_source_path,
                generated_at_utc="2026-07-24T13:18:30Z",
            )
            funding_path, _funding, _funding_raw = _write_paper_funding_source(
                selected_path.parent,
                selected=selected,
                entry_source_path=entry_source_path,
                entry_source=entry_source,
                exit_source_path=exit_source_path,
                exit_source=exit_source,
            )
            evidence = paper_state.build_paper_evidence_artifact(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                selection_path=selected_path,
                expected_selection_hash=selected["artifact_hash"],
                source_paths=[entry_source_path, exit_source_path, funding_path],
                output_path=None,
            )
            self.assertEqual(len(evidence["positions"]), len(selected["selected_positions"]))

            first_sample = entry_samples[0]
            original = first_sample.read_text(encoding="utf-8")
            first_sample.write_text(original.replace("100.1", "100.2", 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "raw sample hash mismatch"):
                paper_state.validate_paper_source_artifact(entry_source_path)

    def test_execution_adapter_requires_all_three_frozen_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)
            depth_root = selected_path.parent / "incomplete-depth"
            depth_root.mkdir()
            manifests, _samples, _plans = _write_paper_boundary_manifests(
                depth_root,
                plan_path=plan_path,
                plan=plan,
                approval_path=approval_path,
                selected_path=selected_path,
                selected=selected,
                boundary="entry",
            )
            with self.assertRaisesRegex(ValueError, "exactly three"):
                paper_state.build_paper_execution_raw_source_manifest(
                    paper_plan_path=plan_path,
                    expected_paper_plan_hash=plan["plan_hash"],
                    approval_path=approval_path,
                    selection_path=selected_path,
                    expected_selection_hash=selected["artifact_hash"],
                    boundary="entry",
                    window_manifest_paths=manifests[:2],
                    raw_input_path=depth_root / "raw.json",
                    raw_manifest_path=depth_root / "raw-manifest.json",
                )

    def test_evidence_rejects_unbound_execution_and_funding_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)

            bad_exit_root = selected_path.parent / "bad-exit"
            bad_exit_root.mkdir()
            entry_path, entry, _raw = _write_paper_source(
                bad_exit_root,
                plan=plan,
                selected=selected,
                source_type="entry_execution",
            )
            exit_path, exit_source, _raw = _write_paper_source(
                bad_exit_root,
                plan=plan,
                selected=selected,
                source_type="exit_execution",
                execution_ts_offset_sec=-DAY_SEC,
            )
            funding_path, _funding, _raw = _write_paper_funding_source(
                bad_exit_root,
                selected=selected,
                entry_source_path=entry_path,
                entry_source=entry,
                exit_source_path=exit_path,
                exit_source=exit_source,
            )
            with self.assertRaisesRegex(ValueError, "depth-window derivation"):
                paper_state.build_paper_evidence_artifact(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    approval_path=approval_path,
                    selection_path=selected_path,
                    expected_selection_hash=selected["artifact_hash"],
                    source_paths=[entry_path, exit_path, funding_path],
                    output_path=None,
                )

            bad_funding_root = selected_path.parent / "bad-funding"
            bad_funding_root.mkdir()
            entry_path, entry, _raw = _write_paper_source(
                bad_funding_root,
                plan=plan,
                selected=selected,
                source_type="entry_execution",
            )
            exit_path, exit_source, _raw = _write_paper_source(
                bad_funding_root,
                plan=plan,
                selected=selected,
                source_type="exit_execution",
            )
            with self.assertRaisesRegex(ValueError, "coverage"):
                _write_paper_funding_source(
                    bad_funding_root,
                    selected=selected,
                    entry_source_path=entry_path,
                    entry_source=entry,
                    exit_source_path=exit_path,
                    exit_source=exit_source,
                    missing_settlement=True,
                )

    def test_initialize_apply_and_reconcile_one_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, approval = _paper_chain(root)
            ledger_path = root / "paper-ledger.jsonl"
            state_path = root / "paper-state.json"
            state = paper_state.initialize_paper_state(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                ledger_path=ledger_path,
                state_path=state_path,
                generated_at_utc="2026-07-17T13:15:00Z",
            )
            self.assertEqual(state["status"], paper_state.PAPER_ACTIVE_DECISION)
            self.assertEqual(state["approval_id"], approval["approval_id"])
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)
            evidence_path, evidence, _raw_paths = _paper_evidence(
                plan_path=plan_path,
                plan=plan,
                approval_path=approval_path,
                selected_path=selected_path,
                selected=selected,
            )
            event_path = root / "paper-event.json"
            event = paper_state.build_paper_event(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                selection_path=selected_path,
                expected_selection_hash=selected["artifact_hash"],
                evidence_path=evidence_path,
                expected_evidence_hash=evidence["artifact_hash"],
                output_path=event_path,
                generated_at_utc="2026-07-17T13:20:00Z",
            )
            updated = paper_state.apply_paper_event(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                event_path=event_path,
                expected_event_hash=event["event_hash"],
                ledger_path=ledger_path,
                state_path=state_path,
            )
            self.assertEqual(updated["independent_paper_event_count"], 1)
            self.assertGreater(updated["paper_total_net_pnl_quote"], 0.0)
            self.assertGreater(updated["stress_net_pnl_quote"], 0.0)
            self.assertIn("entry_ts", event["positions"][0])
            self.assertIn("exit_ts", event["positions"][0])
            self.assertEqual(event["positions"][0]["funding_settlement_count"], 21)
            reconciliation = paper_state.reconcile_paper_state(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                ledger_path=ledger_path,
                state_path=state_path,
            )
            self.assertTrue(reconciliation["matched"])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                paper_state.apply_paper_event(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    approval_path=approval_path,
                    event_path=event_path,
                    expected_event_hash=event["event_hash"],
                    ledger_path=ledger_path,
                    state_path=state_path,
                )

    def test_fifteen_positive_events_reach_live_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            ledger_path = root / "paper-ledger.jsonl"
            state_path = root / "paper-state.json"
            paper_state.initialize_paper_state(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                ledger_path=ledger_path,
                state_path=state_path,
            )
            state = None
            evidence_by_path: dict[str, dict] = {}

            def synthetic_evidence(selected: dict, approval: dict, event_index: int) -> dict:
                event_probe_path = Path(selected["probe_plan_authorization"]["path"])
                event_probe = probe.validate_execution_probe_plan(
                    event_probe_path,
                    selected["probe_plan_authorization"]["plan_hash"],
                )
                first_window = event_probe["execution_contract"]["windows"][0]
                entry_ts = int(first_window["start_ts"]) + 1
                exit_ts = entry_ts + int(plan["paper_contract"]["hold_days"]) * DAY_SEC
                settlements = [
                    {"ts": entry_ts + (index + 1) * 8 * 60 * 60, "funding_rate": 0.0}
                    for index in range(20)
                ]
                execution = {
                    "valid_snapshots": 180,
                    "coverage": 0.9,
                    "p95_impact_bps": 5.0,
                    "capacity_quote": 500.0,
                    "max_timestamp_skew_ms": 100.0,
                    "max_quote_age_ms": 100.0,
                    "critical_error_count": 0,
                    "window_count": 3,
                    "evidence_hash": v3_history_plan.sha256_json(
                        {"synthetic_execution_event": event_index}
                    ),
                }
                positions = []
                for row in selected["selected_positions"]:
                    side = str(row["side"])
                    positions.append(
                        {
                            "canonical_asset_id": row["canonical_asset_id"],
                            "symbol": row["symbol"],
                            "base": row["base"],
                            "side": side,
                            "entry_ts": entry_ts,
                            "exit_ts": exit_ts,
                            "entry_price": 100.0,
                            "exit_price": 120.0 if side == "long" else 80.0,
                            "funding_rate_sum": 0.0,
                            "funding_interval_sec": 8 * 60 * 60,
                            "funding_expected_settlement_count": 20,
                            "funding_settlement_count": 20,
                            "funding_settlement_coverage": 1.0,
                            "funding_settlements": settlements,
                            "entry_execution": execution,
                            "exit_execution": execution,
                        }
                    )
                artifact_hash = v3_history_plan.sha256_json(
                    {"synthetic_paper_evidence_event": event_index}
                )
                return {
                    "artifact_hash": artifact_hash,
                    "paper_plan_authorization": {"plan_hash": plan["plan_hash"]},
                    "approval_authorization": {"approval_id": approval["approval_id"]},
                    "selection_authorization": {"artifact_hash": selected["artifact_hash"]},
                    "funding_settlement_coverage": 1.0,
                    "positions": positions,
                }

            with mock.patch.object(
                paper_state,
                "validate_paper_evidence_artifact",
                side_effect=lambda path, _expected=None: evidence_by_path[
                    str(Path(path).resolve())
                ],
            ):
                for event_index in range(15):
                    selected_path, selected = _future_selection(
                        root,
                        paper=plan,
                        event_index=event_index,
                    )
                    evidence_path = root / f"synthetic-evidence-{event_index:02d}.json"
                    evidence_path.write_text("{}", encoding="utf-8")
                    evidence = synthetic_evidence(selected, _approval, event_index)
                    evidence_by_path[str(evidence_path.resolve())] = evidence
                    event_path = root / f"paper-event-{event_index:02d}.json"
                    event = paper_state.build_paper_event(
                        plan_path=plan_path,
                        expected_plan_hash=plan["plan_hash"],
                        approval_path=approval_path,
                        selection_path=selected_path,
                        expected_selection_hash=selected["artifact_hash"],
                        evidence_path=evidence_path,
                        expected_evidence_hash=evidence["artifact_hash"],
                        output_path=event_path,
                    )
                    state = paper_state.apply_paper_event(
                        plan_path=plan_path,
                        expected_plan_hash=plan["plan_hash"],
                        approval_path=approval_path,
                        event_path=event_path,
                        expected_event_hash=event["event_hash"],
                        ledger_path=ledger_path,
                        state_path=state_path,
                    )
            assert state is not None
            self.assertEqual(state["status"], paper_state.LIVE_REVIEW_ELIGIBLE_DECISION)
            self.assertEqual(state["independent_paper_event_count"], 15)
            self.assertLessEqual(state["maximum_single_event_positive_pnl_share"], 0.25)
            self.assertFalse(state["live_orders"])
            self.assertFalse(state["private_api_keys"])
            self.assertEqual(state["maximum_authority"], "LIVE_REVIEW_ELIGIBLE")
            self.assertEqual(state["next_allowed_command"], "request-separate-live-review")

    def test_tampered_state_and_ledger_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            ledger_path = root / "paper-ledger.jsonl"
            state_path = root / "paper-state.json"
            paper_state.initialize_paper_state(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                ledger_path=ledger_path,
                state_path=state_path,
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["paper_total_net_pnl_quote"] = 1_000_000.0
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "state hash"):
                paper_state.reconcile_paper_state(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    approval_path=approval_path,
                    ledger_path=ledger_path,
                    state_path=state_path,
                )

    def test_reconciliation_rejects_mutated_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, approval_path, _approval = _paper_chain(root)
            ledger_path = root / "paper-ledger.jsonl"
            state_path = root / "paper-state.json"
            paper_state.initialize_paper_state(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                ledger_path=ledger_path,
                state_path=state_path,
            )
            selected_path, selected = _future_selection(root, paper=plan, event_index=0)
            evidence_path, evidence, raw_paths = _paper_evidence(
                plan_path=plan_path,
                plan=plan,
                approval_path=approval_path,
                selected_path=selected_path,
                selected=selected,
            )
            event_path = root / "paper-event.json"
            event = paper_state.build_paper_event(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                selection_path=selected_path,
                expected_selection_hash=selected["artifact_hash"],
                evidence_path=evidence_path,
                expected_evidence_hash=evidence["artifact_hash"],
                output_path=event_path,
            )
            paper_state.apply_paper_event(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                approval_path=approval_path,
                event_path=event_path,
                expected_event_hash=event["event_hash"],
                ledger_path=ledger_path,
                state_path=state_path,
            )
            raw_paths[0].write_text('{"tampered":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source provenance"):
                paper_state.reconcile_paper_state(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    approval_path=approval_path,
                    ledger_path=ledger_path,
                    state_path=state_path,
                )

    def test_run_mvp_exposes_paper_state_routes(self) -> None:
        wrapper = (TRADING_ROOT / "run_mvp.ps1").read_text(encoding="utf-8-sig")
        for action in (
            "fast-edge-membership-momentum-v2-paper-approve",
            "fast-edge-membership-momentum-v2-paper-init",
            "fast-edge-membership-momentum-v2-paper-execution-window-plan",
            "fast-edge-membership-momentum-v2-paper-execution-raw",
            "fast-edge-membership-momentum-v2-paper-funding-raw",
            "fast-edge-membership-momentum-v2-paper-source",
            "fast-edge-membership-momentum-v2-paper-evidence",
            "fast-edge-membership-momentum-v2-paper-event",
            "fast-edge-membership-momentum-v2-paper-apply",
            "fast-edge-membership-momentum-v2-paper-status",
        ):
            self.assertIn(f'"{action}"', wrapper)
        self.assertIn("gate_membership_momentum_v2_paper_state.py", wrapper)
        self.assertIn("ExpectedEvidenceHash", wrapper)
        self.assertIn("ExpectedRawManifestHash", wrapper)
        self.assertIn("ExpectedEntrySourceHash", wrapper)
        self.assertIn("ExpectedExitSourceHash", wrapper)
        self.assertIn("FundingHistoryPaths", wrapper)
        self.assertIn("PaperBoundary", wrapper)
        self.assertIn("plan-paper-window", wrapper)
        self.assertIn("build-execution-raw", wrapper)


if __name__ == "__main__":
    unittest.main()
