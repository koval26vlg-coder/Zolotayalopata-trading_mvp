from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN = (
    ROOT
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
)
LAUNCHER = ROOT / "tools" / "start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
PRODUCTION_RECEIPT = (
    ROOT
    / "docs"
    / "agent-log"
    / "approvals"
    / "2026-08-13-slow-liquidity-history-recollect-pagecap-provenance-slotintegrity-v6-approval.json"
)
PRODUCTION_LAUNCH_RECORD = (
    ROOT
    / "docs"
    / "agent-log"
    / "run-gates"
    / "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6.launch.json"
)
GLOBAL_WRITER_CLAIM = ROOT / "docs" / "agent-log" / "active-market-data-writer-claim.json"
ACTIVE_RUN_GATE_CHECKER = ROOT / "tools" / "check_active_run_gate.ps1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _logical_plan_hash(plan: dict[str, object]) -> str:
    canonical_plan = copy.deepcopy(plan)
    canonical_plan.pop("plan_hash", None)
    canonical = json.dumps(
        canonical_plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(canonical)


class SlowLiquidityRecollectLaunchWindowTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.pwsh = shutil.which("pwsh")
        if not self.pwsh:
            self.skipTest("pwsh is not available")
        self.production_artifacts_before = {
            path: path.read_bytes() if path.is_file() else None
            for path in (
                PRODUCTION_RECEIPT,
                PRODUCTION_LAUNCH_RECORD,
                GLOBAL_WRITER_CLAIM,
            )
        }
        self.base_plan = json.loads(PLAN.read_text(encoding="utf-8"))

    def _run_preflight(
        self,
        temporary_root: Path,
        scenario: str,
        *,
        not_before: datetime,
        latest_start: datetime,
        hard_deadline: datetime,
    ) -> tuple[dict[str, object], dict[str, Path]]:
        scenario_root = temporary_root / scenario
        output_path = scenario_root / "output"
        receipt_path = scenario_root / "approval.json"
        launch_record_path = scenario_root / "launch.json"
        plan_path = scenario_root / "plan.json"
        scenario_root.mkdir(parents=True)

        plan = copy.deepcopy(self.base_plan)
        execution = plan["execution"]
        execution["output_path"] = str(output_path)
        execution["output_jsonl"] = str(output_path / "ohlcv.jsonl")
        execution["manifest_path"] = str(output_path / "manifest.json")
        execution["stdout_path"] = str(output_path / "stdout.log")
        execution["stderr_path"] = str(output_path / "stderr.log")
        execution["launch_record_path"] = str(launch_record_path)
        execution["not_before_local"] = not_before.isoformat(timespec="seconds")
        execution["latest_start_local"] = latest_start.isoformat(timespec="seconds")
        execution["hard_deadline_local"] = hard_deadline.isoformat(timespec="seconds")
        plan["approval_receipt"]["path"] = str(receipt_path)
        for binding in plan["implementation"]["files"]:
            if binding["role"] == "active_run_gate_checker":
                binding["path"] = str(ACTIVE_RUN_GATE_CHECKER)
            implementation_path = Path(binding["path"])
            self.assertTrue(implementation_path.is_file(), binding["path"])
            binding["sha256"] = _sha256_bytes(implementation_path.read_bytes())
        plan["plan_hash"] = _logical_plan_hash(plan)

        plan_bytes = (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        plan_path.write_bytes(plan_bytes)
        plan_file_sha256 = _sha256_bytes(plan_bytes)

        result = subprocess.run(
            [
                self.pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(LAUNCHER),
                "-PlanPath",
                str(plan_path),
                "-ExpectedPlanHash",
                plan["plan_hash"],
                "-ExpectedPlanFileSha256",
                plan_file_sha256,
                "-PreflightOnly",
                "-Json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        paths = {
            "output": output_path,
            "receipt": receipt_path,
            "launch_record": launch_record_path,
        }
        for label, path in paths.items():
            self.assertFalse(path.exists(), f"{label} was created by preflight: {path}")
        for path, before in self.production_artifacts_before.items():
            if before is None:
                self.assertFalse(path.exists(), f"production artifact was created: {path}")
            else:
                self.assertEqual(
                    path.read_bytes(),
                    before,
                    f"production artifact changed: {path}",
                )
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["approval_receipt_present"])
        self.assertIn("exact_approval_receipt_missing", payload["reasons"])
        return payload, paths

    def test_preflight_enforces_every_launch_window_boundary_without_side_effects(self) -> None:
        now = datetime.now().astimezone()
        scenarios = {
            "not_open": {
                "not_before": now + timedelta(hours=1),
                "latest_start": now + timedelta(hours=2),
                "hard_deadline": now + timedelta(hours=3),
                "required": {"launch_window_not_open"},
                "forbidden": {
                    "latest_start_passed",
                    "full_runtime_exceeds_hard_deadline",
                },
            },
            "latest_start_passed": {
                "not_before": now - timedelta(hours=3),
                "latest_start": now - timedelta(hours=1),
                "hard_deadline": now + timedelta(hours=1),
                "required": {"latest_start_passed"},
                "forbidden": {
                    "launch_window_not_open",
                    "full_runtime_exceeds_hard_deadline",
                },
            },
            "runtime_does_not_fit": {
                "not_before": now - timedelta(hours=1),
                "latest_start": now + timedelta(hours=1),
                "hard_deadline": now + timedelta(minutes=5),
                "required": {"full_runtime_exceeds_hard_deadline"},
                "forbidden": {"launch_window_not_open", "latest_start_passed"},
            },
            "open": {
                "not_before": now - timedelta(hours=1),
                "latest_start": now + timedelta(minutes=30),
                "hard_deadline": now + timedelta(hours=1),
                "required": set(),
                "forbidden": {
                    "launch_window_not_open",
                    "latest_start_passed",
                    "full_runtime_exceeds_hard_deadline",
                },
            },
        }

        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            for name, scenario in scenarios.items():
                with self.subTest(name=name):
                    payload, _ = self._run_preflight(
                        temporary_root,
                        name,
                        not_before=scenario["not_before"],
                        latest_start=scenario["latest_start"],
                        hard_deadline=scenario["hard_deadline"],
                    )
                    reasons = set(payload["reasons"])
                    self.assertTrue(scenario["required"].issubset(reasons), reasons)
                    self.assertTrue(scenario["forbidden"].isdisjoint(reasons), reasons)


if __name__ == "__main__":
    unittest.main()
