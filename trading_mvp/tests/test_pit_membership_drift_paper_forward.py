from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_mvp.tests import test_pit_membership_drift_execution_probe as probe_fixture
from trading_mvp.tests import test_pit_membership_drift_pipeline as pit_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pit_membership_drift_evaluator import (  # noqa: E402
    build_evaluation_input_plan,
    run_oos_evaluation,
    run_train_feasibility,
)
from pit_membership_drift_execution_probe import (  # noqa: E402
    build_execution_probe_plan,
    evaluate_execution_probe,
)
from pit_membership_drift_execution_probe_collector import collect_execution_probe  # noqa: E402
from pit_membership_drift_paper_forward import (  # noqa: E402
    build_paper_forward_plan,
    create_paper_forward_approval,
    evaluate_paper_forward_state,
    validate_paper_forward_plan,
)
import pit_membership_drift_paper_forward as paper_module  # noqa: E402


class PitMembershipDriftPaperForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        root = Path(cls._temp.name)
        fixture = pit_fixture.PitMembershipDriftPipelineTests()
        bank, ledger, contract = fixture._dataset(root, days=160)
        all_lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        cls.historical_lines = all_lines[:120]
        cls.paper_lines = all_lines[120:]
        ledger.write_text("".join(cls.historical_lines), encoding="utf-8")

        train_path = root / "train-plan.json"
        train = build_evaluation_input_plan(
            quality_ledger_path=ledger,
            hypothesis_bank_path=bank,
            hypothesis_id=contract["id"],
            output_path=train_path,
            plan_stage="train_feasibility",
        )
        feasibility_path = root / "feasibility.json"
        feasibility = run_train_feasibility(
            train_path,
            expected_plan_hash=train["plan_hash"],
            output_path=feasibility_path,
        )
        if feasibility["verdict"] != "FEASIBLE_FOR_OOS":
            raise AssertionError(feasibility)
        full_plan_path = root / "full-plan.json"
        full_plan = build_evaluation_input_plan(
            quality_ledger_path=ledger,
            hypothesis_bank_path=bank,
            hypothesis_id=contract["id"],
            output_path=full_plan_path,
            plan_stage="full_evaluation",
            train_plan_path=train_path,
            feasibility_path=feasibility_path,
        )
        historical_evaluation_path = root / "historical-evaluation.json"
        historical = run_oos_evaluation(
            full_plan_path,
            expected_plan_hash=full_plan["plan_hash"],
            feasibility_path=feasibility_path,
            output_path=historical_evaluation_path,
        )
        if historical["verdict"] != "ACCEPT_FOR_SHORT_EXECUTION_PROBE":
            raise AssertionError(historical["verdict"])

        execution_plan_path = root / "execution-plan.json"
        execution_plan = build_execution_probe_plan(historical_evaluation_path, execution_plan_path)
        clock = probe_fixture._FakeClock()
        execution_manifest = collect_execution_probe(
            execution_plan_path,
            root / "execution-runs",
            "paper-ready-probe",
            pair_fetcher=lambda base: probe_fixture._valid_pair(base),
            monotonic_fn=clock.monotonic,
            wall_time_fn=clock.wall_time,
            sleep_fn=clock.sleep,
        )
        execution_evaluation_path = root / "execution-evaluation.json"
        execution = evaluate_execution_probe(
            execution_plan_path,
            root / "execution-runs" / "paper-ready-probe" / "manifest.json",
            execution_evaluation_path,
        )
        if execution["verdict"] != "PAPER_READY":
            raise AssertionError(execution)

        paper_plan_path = root / "paper-plan.json"
        paper_plan = build_paper_forward_plan(execution_evaluation_path, paper_plan_path)
        cls.root = root
        cls.ledger = ledger
        cls.execution_evaluation_path = execution_evaluation_path
        cls.paper_plan_path = paper_plan_path
        cls.paper_plan = paper_plan

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def setUp(self) -> None:
        self.ledger.write_text("".join(self.historical_lines), encoding="utf-8")
        for path in self.root.glob("test-*.json"):
            path.unlink()

    def _approval(self, name: str = "test-approval.json") -> Path:
        target = self.root / name
        create_paper_forward_approval(
            self.paper_plan_path,
            target,
            confirmed_plan_hash=self.paper_plan["plan_hash"],
            confirmed_paper_forward=True,
        )
        return target

    def _append_paper_dates(self, count: int) -> None:
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write("".join(self.paper_lines[:count]))

    def test_plan_seals_boundary_and_requires_explicit_paper_approval(self) -> None:
        validation = validate_paper_forward_plan(
            self.paper_plan_path,
            self.paper_plan["plan_hash"],
        )

        self.assertEqual(self.paper_plan["schema"], "pit_membership_drift_paper_forward_plan_v1")
        self.assertEqual(self.paper_plan["mode"], "PlanOnly")
        self.assertEqual(self.paper_plan["decision"], "PIT_PAPER_FORWARD_PLAN_READY_REQUIRES_EXPLICIT_APPROVAL")
        self.assertEqual(len(self.paper_plan["warmup_certifications"]), 2)
        self.assertEqual(self.paper_plan["acceptance_gates"]["minimum_completed_portfolio_observations"], 15)
        self.assertEqual(self.paper_plan["acceptance_gates"]["minimum_profit_factor"], 1.2)
        self.assertEqual(self.paper_plan["acceptance_gates"]["maximum_incidents"], 1)
        self.assertIn(self.paper_plan["plan_hash"], self.paper_plan["approval_phrase"])
        self.assertTrue(self.paper_plan["requires_explicit_user_approval_for_paper_forward"])
        self.assertFalse(self.paper_plan["paper_forward_started"])
        self.assertFalse(self.paper_plan["network_access"])
        self.assertFalse(self.paper_plan["live_orders"])
        self.assertEqual(validation["historical_dates"], 120)

    def test_run_mvp_owned_probe_can_create_planonly_but_not_start_paper(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        gate_path = self.root / "test-owned-paper-plan-gate.json"
        gate = {
            "schema": "active_run_gate_v2",
            "project": "trading_mvp",
            "run_id": "paper-plan-owned",
            "status": "RUNNING",
            "gate_status": "RUNNING",
            "final": False,
            "monitor_pid": os.getpid(),
            "process_ids": [os.getpid()],
            "next_goal_decision": "PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_RUNNING",
            "replay_allowed": False,
        }
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        gate_before = gate_path.read_bytes()
        output = self.root / "test-owned-paper-plan.json"
        environment = os.environ.copy()
        environment["TRADING_MVP_PYTHON"] = sys.executable

        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "trading_mvp" / "run_mvp.ps1"),
                "-Action",
                "fast-edge-pit-paper-plan",
                "-RunId",
                "paper-plan-owned",
                "-ActiveRunGatePath",
                str(gate_path),
                "-EvaluationPath",
                str(self.execution_evaluation_path),
                "-OutputPath",
                str(output),
                "-MaxRuntimeSec",
                "300",
            ],
            cwd=str(REPO_ROOT),
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=90,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["decision"], "PIT_PAPER_FORWARD_PLAN_READY_REQUIRES_EXPLICIT_APPROVAL")
        self.assertFalse(result["paper_forward_started"])
        self.assertFalse(result["network_access"])
        self.assertFalse(result["live_orders"])
        self.assertEqual(gate_path.read_bytes(), gate_before)

    def test_evaluation_requires_hash_bound_approval(self) -> None:
        self._append_paper_dates(14)

        with self.assertRaisesRegex(ValueError, "approval"):
            evaluate_paper_forward_state(
                self.paper_plan_path,
                self.root / "missing-approval.json",
                self.root / "test-missing-approval-state.json",
            )

    def test_multiday_state_collects_before_fifteen_completed_observations(self) -> None:
        self._append_paper_dates(14)
        result = evaluate_paper_forward_state(
            self.paper_plan_path,
            self._approval("test-collecting-approval.json"),
            self.root / "test-collecting-state.json",
        )

        self.assertEqual(result["status"], "PAPER_COLLECTING")
        self.assertLess(result["metrics"]["completed_portfolio_observations"], 15)
        self.assertGreater(result["metrics"]["completed_portfolio_observations"], 0)
        self.assertFalse(result["live_orders"])

    def test_multiday_state_reaches_live_review_gate_after_fifteen_observations(self) -> None:
        self._append_paper_dates(len(self.paper_lines))
        result = evaluate_paper_forward_state(
            self.paper_plan_path,
            self._approval("test-live-review-approval.json"),
            self.root / "test-live-review-state.json",
        )

        self.assertEqual(result["status"], "LIVE_REVIEW_ELIGIBLE")
        self.assertGreaterEqual(result["metrics"]["completed_portfolio_observations"], 15)
        self.assertGreater(result["metrics"]["net_expectancy_quote"], 0.0)
        self.assertGreaterEqual(result["metrics"]["profit_factor"], 1.2)
        self.assertGreaterEqual(result["metrics"]["stress_reconciliation_net_quote"], 0.0)
        self.assertTrue(result["requires_explicit_user_live_review"])
        self.assertFalse(result["live_orders"])

    def test_more_than_one_quality_incident_rejects_early(self) -> None:
        rows = [json.loads(line) for line in self.paper_lines[:14]]
        for row in rows[:2]:
            body = {key: value for key, value in row.items() if key != "certification_id"}
            body["technical_quality_accepted"] = False
            body["reasons"] = ["fixture_data_quality_incident"]
            body["certification_id"] = pit_fixture._canonical_hash(body)
            row.clear()
            row.update(body)
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))

        result = evaluate_paper_forward_state(
            self.paper_plan_path,
            self._approval("test-incident-approval.json"),
            self.root / "test-incident-state.json",
        )

        self.assertEqual(result["status"], "PAPER_REJECTED")
        self.assertEqual(result["metrics"]["incident_count"], 2)
        self.assertIn("incident_limit_exceeded", result["rejection_reasons"])
        self.assertFalse(result["live_orders"])

    def test_historical_ledger_prefix_tamper_is_rejected(self) -> None:
        data = bytearray(self.ledger.read_bytes())
        data[0] = ord("[")
        self.ledger.write_bytes(data)

        with self.assertRaisesRegex(ValueError, "append-only prefix"):
            validate_paper_forward_plan(self.paper_plan_path, self.paper_plan["plan_hash"])

    def test_plan_cannot_be_frozen_after_rejected_paper_date_accrual(self) -> None:
        row = json.loads(self.paper_lines[0])
        body = {key: value for key, value in row.items() if key != "certification_id"}
        body["technical_quality_accepted"] = False
        body["reasons"] = ["fixture_rejected_before_plan"]
        body["certification_id"] = pit_fixture._canonical_hash(body)
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, separators=(",", ":")) + "\n")

        with self.assertRaisesRegex(ValueError, "before any paper-date accrual"):
            build_paper_forward_plan(
                self.execution_evaluation_path,
                self.root / "test-late-paper-plan.json",
            )

    def test_existing_state_tamper_is_rejected_before_cache_hit(self) -> None:
        self._append_paper_dates(len(self.paper_lines))
        approval = self._approval("test-state-tamper-approval.json")
        state_path = self.root / "test-state-tamper-state.json"
        evaluate_paper_forward_state(
            self.paper_plan_path,
            approval,
            state_path,
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["metrics"]["net_pnl_quote"] = 1_000_000.0
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "deterministic result hash"):
            evaluate_paper_forward_state(
                self.paper_plan_path,
                approval,
                state_path,
            )

    def test_rejected_state_is_terminal_when_ledger_grows(self) -> None:
        rows = [json.loads(line) for line in self.paper_lines[:14]]
        for row in rows[:2]:
            body = {key: value for key, value in row.items() if key != "certification_id"}
            body["technical_quality_accepted"] = False
            body["reasons"] = ["fixture_terminal_incident"]
            body["certification_id"] = pit_fixture._canonical_hash(body)
            row.clear()
            row.update(body)
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))
        approval = self._approval("test-terminal-approval.json")
        state_path = self.root / "test-terminal-state.json"
        first = evaluate_paper_forward_state(
            self.paper_plan_path,
            approval,
            state_path,
        )
        self.assertEqual(first["status"], "PAPER_REJECTED")
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write("".join(self.paper_lines[14:]))

        with self.assertRaisesRegex(ValueError, "terminal"):
            evaluate_paper_forward_state(
                self.paper_plan_path,
                approval,
                state_path,
            )

    def test_ledger_change_during_evaluation_is_rejected(self) -> None:
        self._append_paper_dates(14)
        approval = self._approval("test-ledger-race-approval.json")
        original_loader = paper_module._load_quality_ledger

        def load_then_append(path: Path) -> list[dict[str, object]]:
            entries = original_loader(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(self.paper_lines[14])
            return entries

        with patch.object(paper_module, "_load_quality_ledger", side_effect=load_then_append):
            with self.assertRaisesRegex(ValueError, "changed during evaluation"):
                evaluate_paper_forward_state(
                    self.paper_plan_path,
                    approval,
                    self.root / "test-ledger-race-state.json",
                )


if __name__ == "__main__":
    unittest.main()
