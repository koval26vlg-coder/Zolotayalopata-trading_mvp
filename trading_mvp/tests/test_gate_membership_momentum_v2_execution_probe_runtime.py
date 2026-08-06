from __future__ import annotations

import hashlib
import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from funding import FundingContract  # noqa: E402
import gate_membership_momentum_v2_execution_probe_runtime as runtime  # noqa: E402
import gate_membership_momentum_v2_execution_selection as selection  # noqa: E402
from test_gate_membership_momentum_v2_execution_selection import (  # noqa: E402
    _iso,
    _probe_plan,
    _snapshot,
)


def _selection(root: Path, *, market_count: int = 30) -> tuple[Path, dict, Path, dict]:
    probe_path, probe_plan = _probe_plan(root)
    snapshot_path, snapshot = _snapshot(root, probe_plan, market_count=market_count)
    target_close = int(probe_plan["target_event_contract"]["target_signal_close_ts"])
    path = root / "selection.json"
    result = selection.build_selection_artifact(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=probe_plan["plan_hash"],
        market_snapshot_manifest_path=snapshot_path,
        expected_market_snapshot_hash=snapshot["artifact_hash"],
        output_path=path,
        generated_at_utc=_iso(target_close + 120),
    )
    return probe_path, probe_plan, path, result


def _window_plan(
    root: Path,
    *,
    probe_path: Path,
    probe_plan: dict,
    selection_path: Path,
    selection_result: dict,
    window_index: int,
) -> tuple[Path, dict]:
    plan_path = root / f"window-plan-{window_index}.json"
    result = runtime.build_window_collect_plan(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=probe_plan["plan_hash"],
        selection_path=selection_path,
        expected_selection_hash=selection_result["artifact_hash"],
        output_path=plan_path,
        samples_path=root / f"samples-{window_index}.jsonl",
        manifest_path=root / f"manifest-{window_index}.json",
        run_id=f"momentum-v2-probe-w{window_index}",
        window_index=window_index,
        max_runtime_sec=1800,
        workers=4,
        generated_at_utc="2026-07-17T09:00:00Z",
    )
    return plan_path, result


def _book(*, capacity_quote: float = 2_000.0, impact_bps: float = 0.0) -> tuple[list, list]:
    quantity = capacity_quote / 200.0
    adverse = impact_bps / 10_000.0
    bids = [[100.0, quantity], [100.0 * (1.0 - adverse), quantity]]
    asks = [[100.0, quantity], [100.0 * (1.0 + adverse), quantity]]
    return bids, asks


def _write_samples(
    plan: dict,
    *,
    bad_asset: str | None = None,
    valid_cycles: int = 240,
) -> None:
    rows = []
    window = plan["window_contract"]
    start = int(window["start_ts"])
    for cycle in range(1, 241):
        timestamp = start + (cycle - 1) * 5
        for position in plan["selected_positions"]:
            capacity = 400.0 if position["canonical_asset_id"] == bad_asset else 2_000.0
            bids, asks = _book(capacity_quote=capacity)
            valid_payload = cycle <= valid_cycles
            rows.append(
                {
                    "schema": runtime.SAMPLE_SCHEMA,
                    "window_plan_hash": plan["plan_hash"],
                    "selection_hash": plan["selection_authorization"]["artifact_hash"],
                    "window_index": int(window["index"]),
                    "cycle": cycle,
                    "scheduled_ts": timestamp,
                    "canonical_asset_id": position["canonical_asset_id"],
                    "symbol": position["symbol"],
                    "base": position["base"],
                    "side": position["side"],
                    "request_started_ts": timestamp,
                    "received_ts": timestamp + 0.1,
                    "exchange_ts": timestamp if valid_payload else timestamp - 10.0,
                    "timestamp_skew_ms": 100.0,
                    "bids": bids,
                    "asks": asks,
                    "collection_error": None,
                }
            )
    Path(plan["output_contract"]["samples_path"]).write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, float(seconds))


class GateMembershipMomentumV2ExecutionProbeRuntimeTests(unittest.TestCase):
    def test_window_plan_is_hash_bound_and_requires_ready_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan, selection_path, selection_result = _selection(root)
            self.assertEqual(
                selection_result["next_allowed_command"],
                "fast-edge-membership-momentum-v2-execution-probe-window-plan",
            )
            plan_path, plan = _window_plan(
                root,
                probe_path=probe_path,
                probe_plan=probe_plan,
                selection_path=selection_path,
                selection_result=selection_result,
                window_index=0,
            )
            self.assertEqual(plan["decision"], runtime.WINDOW_PLAN_DECISION)
            self.assertFalse(plan["network_access"])
            self.assertFalse(plan["live_orders"])
            self.assertIn(plan["plan_hash"], plan["approval_phrase"])
            self.assertEqual(
                runtime.validate_window_collect_plan(plan_path, plan["plan_hash"])["plan_hash"],
                plan["plan_hash"],
            )

            rejected_root = root / "rejected"
            rejected_root.mkdir()
            rejected_probe, rejected_probe_plan, rejected_selection, rejected_result = _selection(
                rejected_root, market_count=5
            )
            self.assertEqual(rejected_result["decision"], selection.INSUFFICIENT_UNIVERSE_DECISION)
            with self.assertRaisesRegex(ValueError, "ready causal selection"):
                _window_plan(
                    rejected_root,
                    probe_path=rejected_probe,
                    probe_plan=rejected_probe_plan,
                    selection_path=rejected_selection,
                    selection_result=rejected_result,
                    window_index=0,
                )

    def test_collect_window_uses_public_gate_depth_and_finishes_frozen_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan, selection_path, selection_result = _selection(root)
            plan_path, plan = _window_plan(
                root,
                probe_path=probe_path,
                probe_plan=probe_plan,
                selection_path=selection_path,
                selection_result=selection_result,
                window_index=0,
            )
            clock = _Clock(float(plan["window_contract"]["start_ts"]))
            contracts = [
                FundingContract(
                    exchange="gateio",
                    symbol=row["symbol"],
                    base=row["base"],
                    quote="USDT",
                    status="trading",
                    raw={"name": row["symbol"], "status": "trading", "quanto_multiplier": "1"},
                )
                for row in plan["selected_positions"]
            ]

            def depth(contract: FundingContract, _limit: int) -> dict:
                bids, asks = _book()
                return {
                    "bids": [{"p": price, "s": quantity} for price, quantity in bids],
                    "asks": [{"p": price, "s": quantity} for price, quantity in asks],
                    "current": int(clock.now() * 1000),
                }

            with redirect_stdout(io.StringIO()):
                manifest = runtime.collect_execution_probe_window(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    contract_fetcher=lambda: contracts,
                    depth_fetcher=depth,
                    now_fn=clock.now,
                    monotonic_fn=clock.now,
                    sleep_fn=clock.sleep,
                )
            self.assertTrue(manifest["final"])
            self.assertEqual(manifest["completed_cycles"], 240)
            self.assertEqual(manifest["metrics"]["eligible_assets"], sorted(
                row["canonical_asset_id"] for row in plan["selected_positions"]
            ))
            self.assertEqual(manifest["critical_error_count"], 0)

    def test_three_windows_recompute_raw_depth_and_accept_or_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan, selection_path, selection_result = _selection(root)
            manifests = []
            for window_index in range(3):
                plan_path, plan = _window_plan(
                    root,
                    probe_path=probe_path,
                    probe_plan=probe_plan,
                    selection_path=selection_path,
                    selection_result=selection_result,
                    window_index=window_index,
                )
                _write_samples(plan)
                manifest = runtime.finalize_execution_probe_window(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    completed_cycles=240,
                    errors=[],
                    critical_errors=[],
                    runtime_sec=1200.0,
                )
                manifests.append(Path(plan["output_contract"]["manifest_path"]))
                self.assertTrue(manifest["final"])

            report = runtime.evaluate_execution_probe_windows(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                selection_path=selection_path,
                expected_selection_hash=selection_result["artifact_hash"],
                manifest_paths=manifests,
                output_path=root / "report.json",
            )
            self.assertEqual(report["verdict"], runtime.PAPER_FORWARD_READY_DECISION)
            self.assertEqual(len(report["execution_eligible_assets"]), 10)
            self.assertEqual(
                report["next_allowed_command"],
                "fast-edge-membership-momentum-v2-paper-plan",
            )

            rejected_root = root / "rejected"
            rejected_root.mkdir()
            reject_manifests = []
            bad_asset = selection_result["selected_positions"][0]["canonical_asset_id"]
            for window_index in range(3):
                runtime.build_window_collect_plan(
                    probe_plan_path=probe_path,
                    expected_probe_plan_hash=probe_plan["plan_hash"],
                    selection_path=selection_path,
                    expected_selection_hash=selection_result["artifact_hash"],
                    output_path=rejected_root / f"plan-{window_index}.json",
                    samples_path=rejected_root / f"samples-{window_index}.jsonl",
                    manifest_path=rejected_root / f"manifest-{window_index}.json",
                    run_id=f"reject-w{window_index}",
                    window_index=window_index,
                    max_runtime_sec=1800,
                    workers=4,
                )
                plan_path = rejected_root / f"plan-{window_index}.json"
                plan = runtime.validate_window_collect_plan(plan_path)
                _write_samples(plan, bad_asset=bad_asset)
                runtime.finalize_execution_probe_window(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    completed_cycles=240,
                    errors=[],
                    critical_errors=[],
                    runtime_sec=1200.0,
                )
                reject_manifests.append(rejected_root / f"manifest-{window_index}.json")
            rejected = runtime.evaluate_execution_probe_windows(
                probe_plan_path=probe_path,
                expected_probe_plan_hash=probe_plan["plan_hash"],
                selection_path=selection_path,
                expected_selection_hash=selection_result["artifact_hash"],
                manifest_paths=reject_manifests,
                output_path=rejected_root / "report.json",
            )
            self.assertEqual(rejected["verdict"], runtime.REJECT_DECISION)
            self.assertIn("selected_asset_failed_one_or_more_windows", rejected["rejection_reasons"])

    def test_missed_window_refuses_before_public_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan, selection_path, selection_result = _selection(root)
            plan_path, plan = _window_plan(
                root,
                probe_path=probe_path,
                probe_plan=probe_plan,
                selection_path=selection_path,
                selection_result=selection_result,
                window_index=0,
            )
            calls: list[str] = []
            with self.assertRaisesRegex(ValueError, "window has already ended"):
                runtime.collect_execution_probe_window(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    contract_fetcher=lambda: calls.append("network") or [],
                    depth_fetcher=lambda *_args: {},
                    now_fn=lambda: float(plan["window_contract"]["end_ts"]),
                )
            self.assertEqual(calls, [])

    def test_run_mvp_exposes_visible_collect_and_offline_evaluate_routes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        wrapper = (root / "trading_mvp" / "run_mvp.ps1").read_text(encoding="utf-8-sig")
        visible = root / "tools" / "start_gate_membership_momentum_v2_execution_probe_visible.ps1"
        self.assertIn('"fast-edge-membership-momentum-v2-execution-probe-window-plan"', wrapper)
        self.assertIn('"fast-edge-membership-momentum-v2-execution-probe-collect"', wrapper)
        self.assertIn('"fast-edge-membership-momentum-v2-execution-probe-evaluate"', wrapper)
        self.assertTrue(visible.is_file())
        content = visible.read_text(encoding="utf-8-sig")
        self.assertIn("ConfirmedPublicExecutionProbe", content)
        self.assertIn("-WindowPlanPath", content)

    def test_visible_wrapper_planonly_is_hash_bound_and_read_only(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        repository = Path(__file__).resolve().parents[2]
        visible = repository / "tools" / "start_gate_membership_momentum_v2_execution_probe_visible.ps1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan, selection_path, selection_result = _selection(root)
            window_path, window_plan = _window_plan(
                root,
                probe_path=probe_path,
                probe_plan=probe_plan,
                selection_path=selection_path,
                selection_result=selection_result,
                window_index=0,
            )
            gate_payload = {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "previous",
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "final": True,
            }
            gate = root / "active-run-gate.json"
            current = root / "current-run.json"
            gate.write_text(json.dumps(gate_payload), encoding="utf-8")
            current.write_text(json.dumps(gate_payload), encoding="utf-8")
            gate_hash = hashlib.sha256(gate.read_bytes()).hexdigest()
            current_hash = hashlib.sha256(current.read_bytes()).hexdigest()
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(visible),
                    "-WindowPlanPath",
                    str(window_path),
                    "-ExpectedPlanHash",
                    str(window_plan["plan_hash"]),
                    "-GatePath",
                    str(gate),
                    "-CurrentRunPath",
                    str(current),
                    "-LaunchRecordPath",
                    str(root / "launch.json"),
                    "-LogPath",
                    str(root / "probe.log"),
                    "-HoldOpenSec",
                    "0",
                    "-PlanOnly",
                ],
                cwd=repository,
                env={**os.environ, "TRADING_MVP_PYTHON": sys.executable},
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            preview = json.loads(completed.stdout)
            self.assertEqual(
                preview["decision"],
                "AWAIT_EXPLICIT_HASH_BOUND_EXECUTION_PROBE_APPROVAL",
            )
            self.assertEqual(preview["plan_hash"], window_plan["plan_hash"])
            self.assertFalse(preview["network_access"])
            self.assertFalse(preview["collect_started"])
            self.assertFalse(Path(window_plan["output_contract"]["samples_path"]).exists())
            self.assertFalse(Path(window_plan["output_contract"]["manifest_path"]).exists())
            self.assertFalse((root / "launch.json").exists())
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_hash)
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), current_hash)

    def test_run_mvp_window_plan_route_and_collect_fail_closed(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        repository = Path(__file__).resolve().parents[2]
        run_mvp = repository / "trading_mvp" / "run_mvp.ps1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_path, probe_plan, selection_path, selection_result = _selection(root)
            gate_payload = {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "previous",
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "final": True,
            }
            gate = root / "active-run-gate.json"
            gate.write_text(json.dumps(gate_payload), encoding="utf-8")
            window_path = root / "window-plan.json"
            samples_path = root / "samples.jsonl"
            manifest_path = root / "manifest.json"
            env = {**os.environ, "TRADING_MVP_PYTHON": sys.executable}
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(run_mvp),
                    "-Action",
                    "fast-edge-membership-momentum-v2-execution-probe-window-plan",
                    "-PlanPath",
                    str(probe_path),
                    "-ExpectedPlanHash",
                    str(probe_plan["plan_hash"]),
                    "-EvaluationPath",
                    str(selection_path),
                    "-ExpectedArtifactHash",
                    str(selection_result["artifact_hash"]),
                    "-OutputPath",
                    str(window_path),
                    "-SamplesPath",
                    str(samples_path),
                    "-WindowManifestPath",
                    str(manifest_path),
                    "-RunId",
                    "momentum-v2-route-smoke",
                    "-WindowIndex",
                    "0",
                    "-MaxRuntimeSec",
                    "1800",
                    "-ProbeWorkers",
                    "4",
                    "-ActiveRunGatePath",
                    str(gate),
                ],
                cwd=repository,
                env=env,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            plan = json.loads(completed.stdout)
            self.assertEqual(plan["decision"], runtime.WINDOW_PLAN_DECISION)
            self.assertEqual(plan["probe_plan_authorization"]["plan_hash"], probe_plan["plan_hash"])
            self.assertEqual(
                plan["selection_authorization"]["artifact_hash"],
                selection_result["artifact_hash"],
            )
            self.assertFalse(samples_path.exists())
            self.assertFalse(manifest_path.exists())

            refused = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(run_mvp),
                    "-Action",
                    "fast-edge-membership-momentum-v2-execution-probe-collect",
                    "-PlanPath",
                    str(window_path),
                    "-ExpectedPlanHash",
                    str(plan["plan_hash"]),
                    "-MaxRuntimeSec",
                    "1800",
                    "-ActiveRunGatePath",
                    str(gate),
                ],
                cwd=repository,
                env=env,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("Direct execution-probe network execution is disabled", refused.stderr)
            self.assertIn("-WindowPlanPath", refused.stderr)
            self.assertFalse(samples_path.exists())
            self.assertFalse(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
