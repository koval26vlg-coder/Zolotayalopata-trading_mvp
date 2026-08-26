from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE = "trading_mvp.src.listing_expansion_automation_contract"


def content_hash(value):
    payload = {key: item for key, item in value.items() if key != "plan_hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class ExpansionAutomationContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec(MODULE), "immutable wrapper contract is not implemented")
        self.module = importlib.import_module(MODULE)
        self.tmp = tempfile.TemporaryDirectory(prefix="expansion-wrapper-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.git = Path(r"C:\Program Files\Git\cmd\git.exe") if os.name == "nt" else Path("/usr/bin/git")
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.write(".gitattributes", "* -text\n")
        for role, relative in self.module.WRAPPER_ARTIFACTS.items():
            self.write(relative, f"# {role}\n")
        self.write("trading_mvp/src/child_monitor.py", "from child_helper import value\n")
        self.write("trading_mvp/src/child_helper.py", "value = 1\n")
        self.write("tools/child_launcher.ps1", "# fixture child\n")
        self.child_path = self.root / "docs/plans/child-v11.json"
        self.child = {
            "schema": "fixture_child_plan", "plan_id": "expansion_fixture_v11",
            "status": "READY_FOR_VISIBLE_EXPANSION_TICKS", "research_only": True,
            "public_data_only": True, "private_api": False, "live_orders": False,
            "real_capital": False, "leverage_or_margin": False,
            "replay_allowed": False, "evaluator_or_oos_allowed": False,
            "venues": ["binance", "bybit", "okx", "bitget"],
            "acceptance_policy": {"acceptance_decision": "NONE_ACCRUAL_ONLY"},
            "tick": {"max_runtime_sec": 600, "tick_output_root": str(self.root / "fixture-ticks"),
                     "state_path": str(self.root / "fixture-data-state.json"),
                     "terminal_attempts_ledger_path": str(self.root / "fixture-child-attempts.jsonl")},
            "implementation": {"files": [self.binding("expansion_monitor", "trading_mvp/src/child_monitor.py"),
                                           self.binding("visible_tick_launcher", "tools/child_launcher.ps1")]},
        }
        self.save_child()
        self.plan = self.module.build_plan(self.root, self.child_path, generated_at_utc="2026-08-26T00:00:00Z")
        self.plan_path = self.root / self.module.PLAN_RELATIVE_PATH
        self.write(self.module.PLAN_RELATIVE_PATH, json.dumps(self.plan, ensure_ascii=False, indent=2) + "\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "sealed fixture")

    def run_git(self, *args):
        result = subprocess.run([str(self.git), *args], cwd=self.root, capture_output=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")

    def binding(self, role, relative):
        path = self.root / relative
        return {"role": role, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def save_child(self):
        self.child["plan_hash"] = content_hash(self.child)
        self.write(self.child_path.relative_to(self.root), json.dumps(self.child) + "\n")

    def test_valid_committed_plan_preserves_child_and_has_separate_due_state(self):
        result = self.module.validate_plan(self.plan_path, repo_root=self.root)
        self.assertEqual(result, self.plan)
        self.assertNotEqual(self.plan["automation"]["state_path"], self.child["tick"]["state_path"])
        self.assertEqual(self.plan["child_plan"]["plan_hash"], self.child["plan_hash"])
        self.assertEqual(self.plan["acceptance_decision"], "NONE_ACCRUAL_ONLY")
        self.assertFalse(self.plan["live_orders"])
        self.assertEqual(self.plan["plan_hash"], content_hash(self.plan))

    def test_transitive_local_import_is_bound_without_executing_it(self):
        paths = {row["path"] for row in self.plan["implementation"]["files"]}
        helper = str(self.root / "trading_mvp/src/child_helper.py")
        self.assertIn(helper, paths)
        self.write("trading_mvp/src/child_helper.py", "raise RuntimeError('must not import')\n")
        with self.assertRaisesRegex(self.module.AutomationContractError, "implementation|bytes|contract"):
            self.module.validate_plan(self.plan_path, repo_root=self.root)

    def test_rehashed_local_plan_cannot_bypass_committed_identity(self):
        self.plan["generated_at_utc"] = "2026-08-26T01:00:00Z"
        self.plan["plan_hash"] = content_hash(self.plan)
        self.write(self.module.PLAN_RELATIVE_PATH, json.dumps(self.plan) + "\n")
        with self.assertRaisesRegex(self.module.AutomationContractError, "Git|committed"):
            self.module.validate_plan(self.plan_path, repo_root=self.root)

    def test_rehashed_child_privilege_expansion_rejected(self):
        self.child["live_orders"] = True
        self.save_child()
        with self.assertRaisesRegex(self.module.AutomationContractError, "live_orders"):
            self.module.build_plan(self.root, self.child_path, generated_at_utc="2026-08-26T00:00:00Z")

    def test_unknown_venue_or_duplicate_venue_cannot_be_silently_added(self):
        for venues in (["binance", "bybit", "okx", "bitget", "mexc"], ["binance", "bybit", "okx", "okx"]):
            with self.subTest(venues=venues):
                self.child["venues"] = venues
                self.save_child()
                with self.assertRaisesRegex(self.module.AutomationContractError, "venue"):
                    self.module.build_plan(self.root, self.child_path, generated_at_utc="2026-08-26T00:00:00Z")

    def test_child_without_durable_terminal_evidence_is_not_wrapper_ready(self):
        del self.child["tick"]["terminal_attempts_ledger_path"]
        self.save_child()
        with self.assertRaisesRegex(self.module.AutomationContractError, "terminal"):
            self.module.build_plan(self.root, self.child_path, generated_at_utc="2026-08-26T00:00:00Z")

    def test_numeric_boolean_and_unbounded_runtime_rejected(self):
        self.child["public_data_only"] = 1
        self.save_child()
        with self.assertRaisesRegex(self.module.AutomationContractError, "public_data_only"):
            self.module.build_plan(self.root, self.child_path, generated_at_utc="2026-08-26T00:00:00Z")
        self.child["public_data_only"] = True
        self.child["tick"]["max_runtime_sec"] = 86400
        self.save_child()
        with self.assertRaisesRegex(self.module.AutomationContractError, "runtime"):
            self.module.build_plan(self.root, self.child_path, generated_at_utc="2026-08-26T00:00:00Z")

    def test_duplicate_json_keys_are_not_silently_accepted(self):
        self.plan_path.write_text('{"plan_id":"a","plan_id":"b"}', encoding="utf-8")
        with self.assertRaisesRegex(self.module.AutomationContractError, "duplicate"):
            self.module.validate_plan(self.plan_path, repo_root=self.root)

    def test_immutable_write_never_overwrites_changed_existing_plan(self):
        before = self.plan_path.read_bytes()
        changed = dict(self.plan, generated_at_utc="2026-08-26T02:00:00Z")
        with self.assertRaisesRegex(self.module.AutomationContractError, "exists|immutable"):
            self.module.write_immutable_plan(self.plan_path, changed)
        self.assertEqual(self.plan_path.read_bytes(), before)

    def test_initial_freeze_is_exclusive_and_readback_exact(self):
        target = self.root / "new-plan.json"
        self.module.write_immutable_plan(target, self.plan)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), self.plan)
        with self.assertRaises(self.module.AutomationContractError):
            self.module.write_immutable_plan(target, self.plan)


if __name__ == "__main__":
    unittest.main()
