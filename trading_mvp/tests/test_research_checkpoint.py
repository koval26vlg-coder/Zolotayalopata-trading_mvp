import copy
import json
import sys
import tempfile
import shutil
import subprocess
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from autopilot_guard import evaluate_autopilot_state
from one_week_edge_sprint_readiness import (CURRENT_PERMISSION_FIELDS, POINTER_SCHEMA,
    READINESS_SCHEMA, READINESS_HASH_METHOD, resolve_current_sprint_readiness,
    CurrentSprintReadinessError)
from premarket_forward_depth_quality import canonical, digest, ref, SCHEMA
from research_checkpoint import STATUS, DECISION


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pointer = self.root / "docs/agent-log/one-week-edge-sprint-readiness-pointer.json"
        self.report_path = self.pointer.parent / "readiness/reconciled.json"
        self.gate = self.pointer.parent / "gate.json"
        self.writer = self.pointer.parent / "writer.json"
        self.captures = self.root / "captures"
        self.captures.mkdir()
        self.raw = self.captures / "event.jsonl"
        self.raw.write_text('{"rows":10}\n', encoding="utf-8")
        self.write(self.gate, {"status": "READY_FOR_POSTPROCESS", "replay_allowed": False})
        self.plan_path = self.root / "plan.json"
        plan = {"outcome_contract": {"minimum_events_before_any_claim": 12, "acceptance_capable": False}}
        plan["plan_hash"] = canonical(plan, "plan_hash")
        self.write(self.plan_path, plan)
        inputs = [ref(self.raw), ref(self.plan_path)]
        self.audit = {"schema": SCHEMA, "plan_hash": plan["plan_hash"],
                      "inputs": inputs, "input_manifest_hash": canonical({"files": inputs}, "unused"),
                      "capture_directory": str(self.captures),
                      "events": [{"path": str(self.raw), "candidate": True}],
                      "summary": {"current_plan_structural_candidates": 1,
                          "minimum_events_before_any_claim": 12, "mechanism_analysis_performed": False,
                          "pnl_computed": False, "acceptance_capable": False,
                          "complete_statistical_sample_certified": False}}
        self.audit["report_hash"] = canonical(self.audit, "report_hash")
        self.audit_path = self.root / "quality.json"
        self.write(self.audit_path, self.audit)
        self.report = {"schema": READINESS_SCHEMA, "status": STATUS, "project": "trading_mvp",
                       "goal": "One-Week Historical Edge Sprint", "research_only": True,
                       "generated_at_utc": "2026-09-29T00:00:00Z", "readiness_hash_method": READINESS_HASH_METHOD,
                       "permissions": {f: False for f in CURRENT_PERMISSION_FIELDS},
                       "checkpoint": {"primary_branch": "premarket_forward_depth",
                           "schedules_remain_paused": True, "network_launch_authorized": False,
                           "listing_momentum_scope": "EXTERNAL_PROJECT_NO_PARENT_EXECUTION",
                           "legacy_terminal_runs_reopen_allowed": False,
                           "evidence": [], "implementation": [],
                           "quality_report": ref(self.audit_path), "primary_plan": ref(self.plan_path)}}
        self.bind()

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def bind(self):
        self.report["readiness_hash"] = canonical(self.report, "readiness_hash")
        self.write(self.report_path, self.report)
        self.write(self.pointer, {"schema": POINTER_SCHEMA, "status": "ACTIVE", "project": "trading_mvp",
            "updated_at_utc": "2026-09-29T00:00:00Z", "readiness_path": str(self.report_path),
            "readiness_hash": self.report["readiness_hash"], "readiness_file_sha256": digest(self.report_path)})

    def resolve(self):
        return resolve_current_sprint_readiness(self.pointer, gate_path=self.gate,
                 pit_pointer_path=self.root / "unused_pit.json", writer_claim_path=self.writer)

    def state(self, **overrides):
        args = {"policy": {"research_checkpoint": {"enabled": True,
                "readiness_hash": self.report["readiness_hash"], "mode": "OFFLINE_ONLY_SCHEDULES_PAUSED"}},
                "policy_hash": "a" * 64, "gate": {"status": "READY_FOR_POSTPROCESS", "replay_allowed": False},
                "usage": {"decision": "ALLOW_CONTINUE", "remaining_percent": 59},
                "prior_state": {}, "observed_at_utc": "2026-09-29T00:00:00Z",
                "current_sprint_readiness": self.resolve()}
        args.update(overrides)
        return evaluate_autopilot_state(**args)

    def test_valid_checkpoint_does_not_launch(self):
        state = self.state()
        self.assertEqual(state["decision"], DECISION)
        self.assertTrue(state["stop_new_actions"])
        self.assertFalse(state["action_due"])
        self.assertFalse(state["standing_research_authorized"])

    def test_same_count_source_change_invalidates(self):
        self.raw.write_text('{"rows":11}\n', encoding="utf-8")
        with self.assertRaisesRegex(CurrentSprintReadinessError, "source hash mismatch"):
            self.resolve()

    def test_new_capture_invalidates_inventory(self):
        (self.captures / "new.jsonl").write_text('{}', encoding="utf-8")
        with self.assertRaisesRegex(CurrentSprintReadinessError, "inventory changed"):
            self.resolve()

    def test_pointer_hash_mismatch_blocks(self):
        self.report_path.write_text(self.report_path.read_text() + " ", encoding="utf-8")
        with self.assertRaises(CurrentSprintReadinessError):
            self.resolve()

    def test_external_listing_files_are_not_dependencies(self):
        self.write(self.root / "external-listing-state.json", {"state_hash": "changed"})
        self.assertEqual(self.resolve()["status"], "READY")

    def test_writer_claim_blocks_even_when_gate_ready(self):
        self.write(self.writer, {"pid": 123})
        with self.assertRaisesRegex(CurrentSprintReadinessError, "writer claim"):
            self.resolve()

    def test_running_gate_wins(self):
        self.assertEqual(self.state(gate={"status": "RUNNING"})["decision"], "MONITOR_ACTIVE_RUN")

    def test_incomplete_gate_does_not_consume(self):
        self.assertEqual(self.state(gate={"status": "STOPPED_INCOMPLETE"})["decision"], "CRITICAL_STOP_INCOMPLETE")

    def test_quota_wins(self):
        self.assertEqual(self.state(usage={"decision": "PAUSE_WEEKLY_LIMIT"})["decision"], "PAUSE_WEEKLY_LIMIT")

    def test_unavailable_telemetry_wins(self):
        self.assertEqual(self.state(usage={"decision": "PAUSE_USAGE_TELEMETRY_UNAVAILABLE"})["status"], "PAUSED_USAGE_TELEMETRY")

    def test_wrong_policy_binding_blocks(self):
        self.assertEqual(self.state(policy={})["decision"], "CRITICAL_STOP_RESEARCH_CHECKPOINT_POLICY_BINDING")

    def test_permission_escalation_blocks(self):
        self.report["permissions"]["collector_launch_authorized"] = True
        self.bind()
        with self.assertRaises(CurrentSprintReadinessError):
            self.resolve()

    def test_paused_schedule_must_remain_paused(self):
        self.report["checkpoint"]["schedules_remain_paused"] = False
        self.bind()
        with self.assertRaises(CurrentSprintReadinessError):
            self.resolve()

    def test_changed_code_binding_blocks(self):
        code = self.root / "runtime.py"
        code.write_text("original", encoding="utf-8")
        self.report["checkpoint"]["implementation"] = [ref(code)]
        self.bind()
        code.write_text("changed", encoding="utf-8")
        with self.assertRaises(CurrentSprintReadinessError):
            self.resolve()

    def test_unknown_gate_stays_closed(self):
        self.assertEqual(self.state(gate={"status": "UNKNOWN"})["decision"], "CRITICAL_STOP_UNKNOWN_GATE")


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell required for controller smoke tests")
class ControllerSmokeTests(unittest.TestCase):
    def run_controller(self, guard, gate):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools"
            tools.mkdir()
            original = Path(__file__).resolve().parents[2] / "tools/trading_research_checkpoint_status.ps1"
            shutil.copyfile(original, tools / original.name)
            for script, filename, payload in (
                    ("check_trading_mvp_autopilot.ps1", "guard.json", guard),
                    ("check_active_run_gate.ps1", "gate.json", gate)):
                (root / filename).write_text(json.dumps(payload), encoding="utf-8")
                (tools / script).write_text(
                    "param([switch]$Json, [string]$GatePath)\n"
                    f"Get-Content -Raw (Join-Path $PSScriptRoot '../{filename}')\n", encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File",
                str(tools / original.name), "-Json"], capture_output=True, text=True, timeout=20, check=True)
            return json.loads(result.stdout)

    def test_quota_pause_wins_over_running_gate(self):
        result = self.run_controller({"status": "PAUSED_WEEKLY_LIMIT", "decision": "PAUSE_WEEKLY_LIMIT",
            "next_action": "wait_for_weekly_limit_reset", "gate": {"status": "RUNNING"}},
            {"gate_status": "RUNNING", "run_id": "other_writer"})
        self.assertEqual(result["decision"], "PAUSE_WEEKLY_LIMIT")
        self.assertEqual(result["status"], "PAUSED_WEEKLY_LIMIT")
        self.assertFalse(result["collector_launch_authorized"])

    def test_writer_start_between_guard_and_gate_blocks(self):
        result = self.run_controller({"status": "OFFLINE_CHECKPOINT_COMPLETE", "decision": DECISION,
            "next_action": "offline", "gate": {"status": "READY_FOR_POSTPROCESS"}},
            {"gate_status": "RUNNING", "run_id": "other_writer"})
        self.assertEqual(result["decision"], "MONITOR_ACTIVE_RUN")
        self.assertFalse(result["replay_allowed"])


if __name__ == "__main__":
    unittest.main()
