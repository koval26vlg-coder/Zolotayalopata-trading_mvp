import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class RunMvpVenueCostsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (REPO_ROOT / "trading_mvp" / "run_mvp.ps1").read_text(
            encoding="utf-8-sig"
        )

    def _case(self, name: str, next_name: str) -> str:
        start = self.script.index(f'"{name}" {{')
        end = self.script.index(f'"{next_name}" {{', start)
        return self.script[start:end]

    def test_venue_costs_are_only_forwarded_to_funding_backtest(self) -> None:
        funding_scan = self._case("funding-scan", "funding-collect")
        funding_backtest = self._case("funding-backtest", "funding-sensitivity")

        self.assertNotIn("--venue-costs-json", funding_scan)
        self.assertIn("--venue-costs-json", funding_backtest)

    def test_venue_costs_are_forwarded_once_to_each_replay_command(self) -> None:
        cases = (
            ("ws-replay", "ws-grid-search"),
            ("ws-grid-search", "perp-replay"),
            ("perp-replay", "perp-grid-search"),
            ("perp-grid-search", "funding-scan"),
        )

        for name, next_name in cases:
            with self.subTest(command=name):
                self.assertEqual(
                    self._case(name, next_name).count("--venue-costs-json"),
                    1,
                )

    def test_fast_edge_actions_and_hard_runtime_cap_are_wired(self) -> None:
        for action in (
            "resolve-active-run",
            "fast-edge-plan",
            "fast-edge-evaluate",
            "fast-edge-v2-validate",
            "fast-edge-v2-evaluate",
            "fast-edge-v3-validate",
            "fast-edge-v3-evaluate",
            "fast-edge-v4-validate",
            "fast-edge-v4-evaluate",
            "fast-edge-v5-validate",
            "fast-edge-v5-evaluate",
            "fast-edge-v6-validate",
            "fast-edge-v6-evaluate",
            "fast-edge-data-track-plan",
            "fast-edge-night-schedule-plan",
            "fast-edge-pit-futility-plan",
            "fast-edge-pit-futility-evaluate",
            "fast-edge-pit-input-plan",
            "fast-edge-pit-feasibility",
            "fast-edge-pit-evaluate",
            "fast-edge-pit-paper-plan",
            "fast-edge-pit-paper-evaluate",
            "fast-edge-feasibility",
            "fast-edge-execution-probe",
            "fast-edge-report",
            "paper-forward-segment",
        ):
            self.assertIn(f'"{action}"', self.script)
        self.assertIn("[ValidateRange(1, 10800)]", self.script)
        self.assertIn("$process.WaitForExit($MaxRuntimeSec * 1000)", self.script)
        self.assertIn("$process.Kill($true)", self.script)
        self.assertIn("Assert-FastEdgeGateOpen", self.script)
        self.assertIn("$feasibilityGateCli", self.script)
        self.assertIn("$pitMembershipDriftFutilityCli", self.script)
        self.assertIn("$pitMembershipDriftCli", self.script)

    def test_pit_paper_forward_wiring_is_hash_bound_and_cannot_approve_or_start(self) -> None:
        plan_case = self._case("fast-edge-pit-paper-plan", "fast-edge-pit-paper-evaluate")
        evaluate_case = self._case("fast-edge-pit-paper-evaluate", "fast-edge-feasibility")

        self.assertIn("Assert-FastEdgeGateOpen", plan_case)
        self.assertIn("$pitMembershipDriftPaperCli", plan_case)
        self.assertIn('"plan"', plan_case)
        self.assertIn("--execution-evaluation", plan_case)
        self.assertIn("$EvaluationPath", plan_case)
        self.assertIn("MaxRuntimeSec -gt 1800", plan_case)

        self.assertIn("Assert-FastEdgeGateOpen", evaluate_case)
        self.assertIn("$pitMembershipDriftPaperCli", evaluate_case)
        self.assertIn('"evaluate"', evaluate_case)
        self.assertIn("--plan", evaluate_case)
        self.assertIn("$PlanPath", evaluate_case)
        self.assertIn("--approval", evaluate_case)
        self.assertIn("$PaperApprovalPath", evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("MaxRuntimeSec -gt 1800", evaluate_case)

        self.assertNotIn('"fast-edge-pit-paper-approve"', self.script)
        self.assertNotIn('"approve"', plan_case)
        self.assertNotIn("Start-Process", plan_case + evaluate_case)
        self.assertNotIn("grid", (plan_case + evaluate_case).lower())
        self.assertNotIn("live", (plan_case + evaluate_case).lower())
        self.assertIn(
            '$Action -in @("fast-edge-pit-execution-probe-evaluate", "fast-edge-pit-paper-plan")',
            self.script,
        )

    def test_membership_drift_pipeline_is_hash_bound_and_no_grid(self) -> None:
        plan_case = self._case("fast-edge-pit-input-plan", "fast-edge-pit-feasibility")
        feasibility_case = self._case("fast-edge-pit-feasibility", "fast-edge-pit-evaluate")
        evaluate_case = self._case("fast-edge-pit-evaluate", "fast-edge-feasibility")

        self.assertIn("$pitMembershipDriftCli", plan_case)
        self.assertIn('"plan"', plan_case)
        self.assertIn("--quality-ledger", plan_case)
        self.assertIn("--hypothesis-bank", plan_case)
        self.assertIn("--hypothesis-id", plan_case)
        self.assertIn("--plan-stage", plan_case)
        self.assertIn("$PitPlanStage", plan_case)
        self.assertIn("--train-plan", plan_case)
        self.assertIn("$TrainPlanPath", plan_case)
        self.assertIn("--feasibility", plan_case)
        self.assertIn("full_evaluation", plan_case)
        self.assertIn('"feasibility"', feasibility_case)
        self.assertIn("--expected-plan-hash", feasibility_case)
        self.assertIn('"evaluate"', evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("--feasibility", evaluate_case)
        self.assertIn("$FeasibilityPath", evaluate_case)
        self.assertNotIn("grid", evaluate_case.lower())

    def test_membership_drift_futility_wiring_is_bounded_and_hash_bound(self) -> None:
        plan_case = self._case("fast-edge-pit-futility-plan", "fast-edge-pit-futility-evaluate")
        evaluate_case = self._case("fast-edge-pit-futility-evaluate", "fast-edge-pit-input-plan")

        self.assertIn("Assert-FastEdgeGateOpen", plan_case)
        self.assertIn("$pitMembershipDriftFutilityCli", plan_case)
        self.assertIn('"plan"', plan_case)
        self.assertIn("--quality-ledger", plan_case)
        self.assertIn("--hypothesis-bank", plan_case)
        self.assertIn("--hypothesis-id", plan_case)
        self.assertIn("MaxRuntimeSec -gt 1200", plan_case)

        self.assertIn("Assert-FastEdgeGateOpen", evaluate_case)
        self.assertIn("$pitMembershipDriftFutilityCli", evaluate_case)
        self.assertIn('"evaluate"', evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("MaxRuntimeSec -gt 1800", evaluate_case)
        self.assertNotIn("grid", (plan_case + evaluate_case).lower())

    def test_fast_edge_data_track_plan_is_planonly_and_forwards_explicit_feasibility_inputs(self) -> None:
        case = self._case("fast-edge-data-track-plan", "fast-edge-night-schedule-plan")

        self.assertIn("Assert-FastEdgeGateOpen", case)
        self.assertIn("$dataTrackContractCli", case)
        self.assertIn('"build"', case)
        self.assertIn("--hypothesis-bank", case)
        self.assertIn("--hypothesis-id", case)
        self.assertIn("--data-type", case)
        self.assertIn("--dataset-id", case)
        self.assertIn("--input-merkle-sha256", case)
        self.assertIn("--train-candidate-events", case)
        self.assertIn("--train-valid-events", case)
        self.assertIn("--oos-candidate-events", case)
        self.assertIn("--per-venue-oos-candidate-events-json", case)
        self.assertIn("--unique-oos-dates", case)
        self.assertIn("--dual-venue-coverage", case)
        self.assertIn("--capacity-proxy-quote-per-selected-leg", case)
        self.assertIn("--max-runtime-sec", case)
        self.assertIn("2026-07-14-trading-mvp-canonical-goal-v3.md", case)
        self.assertNotIn("--evaluate", case)

    def test_fast_edge_night_schedule_plan_is_planonly_and_does_not_start_collection(self) -> None:
        case = self._case("fast-edge-night-schedule-plan", "fast-edge-feasibility")

        self.assertIn("Assert-FastEdgeGateOpen", case)
        self.assertIn("$nightSchedulePlanCli", case)
        self.assertIn('"build"', case)
        self.assertIn("--schedule-start-date", case)
        self.assertIn("--nights", case)
        self.assertIn("--segment-start-local", case)
        self.assertIn("--segment-duration-sec", case)
        self.assertIn("--interval-sec", case)
        self.assertIn("--output-root", case)
        self.assertIn("--collection-stage", case)
        self.assertIn("$ScheduleCollectionStage", case)
        self.assertIn("--quality-ledger", case)
        self.assertIn("--train-plan", case)
        self.assertIn("--feasibility", case)
        self.assertIn("2026-07-14-trading-mvp-canonical-goal-v3.md", case)
        self.assertNotIn("ConfirmedPitUniverseSnapshotCollect", case)
        self.assertNotIn("Start-Process", case)

    def test_fast_edge_feasibility_is_wired_as_no_oos_gate(self) -> None:
        case = self._case("fast-edge-feasibility", "fast-edge-execution-probe")

        self.assertIn("Assert-FastEdgeGateOpen", case)
        self.assertIn("$feasibilityGateCli", case)
        self.assertIn('"evaluate"', case)
        self.assertIn("--plan", case)
        self.assertIn("if (-not $PlanPath)", case)
        self.assertIn("--output", case)

    def test_fast_edge_v2_is_bound_to_expected_plan_hash(self) -> None:
        validate_case = self._case("fast-edge-v2-validate", "fast-edge-v2-evaluate")
        evaluate_case = self._case("fast-edge-v2-evaluate", "fast-edge-execution-probe")

        self.assertIn("$residualDispersionCli", validate_case)
        self.assertIn("--expected-plan-hash", validate_case)
        self.assertIn("$ExpectedPlanHash", validate_case)
        self.assertIn("$residualDispersionCli", evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("if (-not $OutputPath)", evaluate_case)
        self.assertIn('$gateResult.run_id -eq $RunId', self.script)
        self.assertIn('"fast-edge-v2-validate", "fast-edge-v2-evaluate"', self.script)

    def test_fast_edge_v3_is_hash_bound_and_evaluation_needs_owned_visible_gate(self) -> None:
        validate_case = self._case("fast-edge-v3-validate", "fast-edge-v3-evaluate")
        evaluate_case = self._case("fast-edge-v3-evaluate", "fast-edge-v4-validate")

        self.assertIn("$lotteryMaxCli", validate_case)
        self.assertIn("--expected-plan-hash", validate_case)
        self.assertIn("$ExpectedPlanHash", validate_case)
        self.assertIn("$lotteryMaxCli", evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("if (-not $OutputPath)", evaluate_case)
        self.assertIn("Assert-FastEdgeV3EvaluationAuthorized", evaluate_case)
        self.assertIn("FAST_FIRST_V3_EVALUATION_RUNNING", self.script)

    def test_fast_edge_v4_is_hash_bound_and_evaluation_needs_owned_visible_gate(self) -> None:
        validate_case = self._case("fast-edge-v4-validate", "fast-edge-v4-evaluate")
        evaluate_case = self._case("fast-edge-v4-evaluate", "fast-edge-execution-probe")

        self.assertIn("$fundingPressureCli", validate_case)
        self.assertIn("--expected-plan-hash", validate_case)
        self.assertIn("$ExpectedPlanHash", validate_case)
        self.assertIn("$fundingPressureCli", evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("if (-not $OutputPath)", evaluate_case)
        self.assertIn("Assert-FastEdgeV4EvaluationAuthorized", evaluate_case)
        self.assertIn("FAST_FIRST_V4_EVALUATION_RUNNING", self.script)

    def test_fast_edge_v5_is_hash_bound_and_evaluation_needs_owned_visible_gate(self) -> None:
        validate_case = self._case("fast-edge-v5-validate", "fast-edge-v5-evaluate")
        evaluate_case = self._case("fast-edge-v5-evaluate", "fast-edge-v6-validate")

        self.assertIn("$wickRejectionCli", validate_case)
        self.assertIn("--expected-plan-hash", validate_case)
        self.assertIn("$ExpectedPlanHash", validate_case)
        self.assertIn("$wickRejectionCli", evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("if (-not $OutputPath)", evaluate_case)
        self.assertIn("Assert-FastEdgeV5EvaluationAuthorized", evaluate_case)
        self.assertIn("FAST_FIRST_V5_EVALUATION_RUNNING", self.script)

    def test_fast_edge_v6_is_hash_bound_and_evaluation_needs_owned_visible_gate(self) -> None:
        validate_case = self._case("fast-edge-v6-validate", "fast-edge-v6-evaluate")
        evaluate_case = self._case("fast-edge-v6-evaluate", "fast-edge-feasibility")

        self.assertIn("$weekendLiquidityCli", validate_case)
        self.assertIn("--expected-plan-hash", validate_case)
        self.assertIn("$ExpectedPlanHash", validate_case)
        self.assertIn("$weekendLiquidityCli", evaluate_case)
        self.assertIn("--expected-plan-hash", evaluate_case)
        self.assertIn("$ExpectedPlanHash", evaluate_case)
        self.assertIn("if (-not $OutputPath)", evaluate_case)
        self.assertIn("Assert-FastEdgeV6EvaluationAuthorized", evaluate_case)
        self.assertIn("FAST_FIRST_V6_EVALUATION_RUNNING", self.script)

    def test_experiment_record_forwards_oos_provenance(self) -> None:
        case = self._case("experiment-record", "experiment-list")

        self.assertIn("--fee-schedule-revision", case)
        self.assertIn("--evaluation-scope", case)
        self.assertIn("--oos-status", case)
        self.assertIn("--source-channel", case)


class FastFirstV2VisibleEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = REPO_ROOT / "tools" / "run_fast_first_v2_evaluation_visible.ps1"

    def test_visible_launcher_is_sealed_reproducible_and_fail_closed(self) -> None:
        self.assertTrue(self.path.exists())
        script = self.path.read_text(encoding="utf-8-sig")

        self.assertIn("[ValidateRange(1, 1800)]", script)
        self.assertIn("-WindowStyle Normal", script)
        self.assertIn("Start-Process", script)
        self.assertIn("check_active_run_gate.ps1", script)
        self.assertIn("fast-edge-v2-validate", script)
        self.assertEqual(script.count('"fast-edge-v2-evaluate"'), 2)
        self.assertIn("deterministic_result_hash", script)
        self.assertIn("Deterministic repeat mismatch", script)
        self.assertIn("READY_FOR_POSTPROCESS", script)
        self.assertIn("STOPPED_INCOMPLETE", script)
        self.assertIn("execution_probe_allowed", script)
        self.assertIn("E:\\ZolotyayLopata-data", script)
        self.assertIn("[switch]$Resume", script)
        self.assertGreaterEqual(script.count('"-RunId", $RunId'), 3)
        self.assertIn("expected_outputs =", script)
        self.assertIn("completed_cycles = 2", script)
        self.assertIn("rows = [int]$first.metrics.oos.event_count", script)


class FastFirstV3VisibleEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = REPO_ROOT / "tools" / "run_fast_first_v3_evaluation_visible.ps1"

    def test_visible_launcher_is_sealed_reproducible_and_deadline_bounded(self) -> None:
        self.assertTrue(self.path.exists())
        script = self.path.read_text(encoding="utf-8-sig")

        self.assertIn("[ValidateRange(1, 1800)]", script)
        self.assertIn("-WindowStyle Normal", script)
        self.assertIn("ApprovedNotLaterThan", script)
        self.assertIn("Get-RemainingRuntimeSec", script)
        self.assertIn("requested_duration_sec = $MaxRuntimeSec", script)
        self.assertIn("actual_duration_sec", script)
        self.assertIn("fast-edge-v3-validate", script)
        self.assertEqual(script.count('"fast-edge-v3-evaluate"'), 2)
        self.assertIn("FAST_FIRST_V3_EVALUATION_RUNNING", script)
        self.assertIn("Deterministic repeat mismatch", script)
        self.assertIn("READY_FOR_POSTPROCESS", script)
        self.assertIn("STOPPED_INCOMPLETE", script)
        self.assertIn("execution_probe_allowed", script)
        self.assertIn("E:\\ZolotyayLopata-data", script)
        self.assertIn("rows = [int]$first.metrics.main.oos.event_count", script)
        self.assertIn("grid_search = $false", script)
        self.assertIn("live_orders = $false", script)
        self.assertIn("api_keys = $false", script)


class FastFirstV4VisibleEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = REPO_ROOT / "tools" / "run_fast_first_v4_evaluation_visible.ps1"

    def test_visible_launcher_is_owned_sealed_reproducible_and_deadline_bounded(self) -> None:
        self.assertTrue(self.path.exists())
        script = self.path.read_text(encoding="utf-8-sig")

        self.assertIn("[ValidateRange(1, 1800)]", script)
        self.assertIn("[switch]$ConfirmedResearchRun", script)
        self.assertIn("worker_token_sha256", script)
        self.assertIn("Worker ownership token mismatch", script)
        self.assertIn('StopReason "worker_exit_nonzero"', script)
        self.assertIn("-WindowStyle Normal", script)
        self.assertIn("ApprovedNotLaterThan", script)
        self.assertIn("Get-RemainingRuntimeSec", script)
        self.assertIn("requested_duration_sec = $MaxRuntimeSec", script)
        self.assertIn("actual_duration_sec", script)
        self.assertIn("fast-edge-v4-validate", script)
        self.assertEqual(script.count('"fast-edge-v4-evaluate"'), 2)
        self.assertIn("FAST_FIRST_V4_EVALUATION_RUNNING", script)
        self.assertIn("Deterministic repeat mismatch", script)
        self.assertIn("READY_FOR_POSTPROCESS", script)
        self.assertIn("STOPPED_INCOMPLETE", script)
        self.assertIn("execution_probe_allowed", script)
        self.assertIn("E:\\ZolotyayLopata-data", script)
        self.assertIn("rows = [int]$first.metrics.main.oos.event_count", script)
        self.assertIn("grid_search = $false", script)
        self.assertIn("execution_probe = $false", script)
        self.assertIn("paper_forward = $false", script)
        self.assertIn("live_orders = $false", script)
        self.assertIn("api_keys = $false", script)
        self.assertGreaterEqual(script.count('"-RunId", $RunId'), 3)
        self.assertIn(
            "5396885aa9abf77a461f20aa190c843b86be098b76abd6f3a5655a8f725eee60",
            script,
        )


class FastFirstV5VisibleEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = REPO_ROOT / "tools" / "run_fast_first_v5_evaluation_visible.ps1"

    def test_visible_launcher_is_owned_sealed_reproducible_and_uses_short_proof_policy(self) -> None:
        self.assertTrue(self.path.exists())
        script = self.path.read_text(encoding="utf-8-sig")

        self.assertIn("[ValidateRange(1, 1800)]", script)
        self.assertNotIn("[switch]$ConfirmedResearchRun", script)
        self.assertNotIn('"-ConfirmedResearchRun"', script)
        self.assertIn("short_owned_no_grid_no_separate_confirmation_required", script)
        self.assertIn("auto_now_plus_MaxRuntimeSec", script)
        self.assertIn("worker_token_sha256", script)
        self.assertIn("Worker ownership token mismatch", script)
        self.assertIn('StopReason "worker_exit_nonzero"', script)
        self.assertIn("-WindowStyle Normal", script)
        self.assertIn("Get-RemainingRuntimeSec", script)
        self.assertIn("requested_duration_sec = $MaxRuntimeSec", script)
        self.assertIn("actual_duration_sec", script)
        self.assertIn("fast-edge-v5-validate", script)
        self.assertEqual(script.count('"fast-edge-v5-evaluate"'), 2)
        self.assertIn("FAST_FIRST_V5_EVALUATION_RUNNING", script)
        self.assertIn("Deterministic repeat mismatch", script)
        self.assertIn("READY_FOR_POSTPROCESS", script)
        self.assertIn("STOPPED_INCOMPLETE", script)
        self.assertIn("execution_probe_allowed", script)
        self.assertIn("E:\\ZolotyayLopata-data", script)
        self.assertIn("rows = [int]$first.metrics.main.oos.event_count", script)
        self.assertIn("grid_search = $false", script)
        self.assertIn("execution_probe = $false", script)
        self.assertIn("paper_forward = $false", script)
        self.assertIn("live_orders = $false", script)
        self.assertIn("api_keys = $false", script)
        self.assertGreaterEqual(script.count('"-RunId", $RunId'), 3)
        self.assertIn(
            "d553c0120b0c3fcb3e4ff80d097bb8270788f690ab703c4b9c3c92d75db5277c",
            script,
        )


class FastFirstV6VisibleEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = REPO_ROOT / "tools" / "run_fast_first_v6_evaluation_visible.ps1"

    def test_visible_launcher_is_owned_sealed_reproducible_and_uses_short_proof_policy(self) -> None:
        self.assertTrue(self.path.exists())
        script = self.path.read_text(encoding="utf-8-sig")

        self.assertIn("[ValidateRange(1, 1800)]", script)
        self.assertNotIn("[switch]$ConfirmedResearchRun", script)
        self.assertNotIn('"-ConfirmedResearchRun"', script)
        self.assertIn("short_owned_no_grid_no_separate_confirmation_required", script)
        self.assertIn("auto_now_plus_MaxRuntimeSec", script)
        self.assertIn("worker_token_sha256", script)
        self.assertIn("Worker ownership token mismatch", script)
        self.assertIn('StopReason "worker_exit_nonzero"', script)
        self.assertIn("-WindowStyle Normal", script)
        self.assertIn("Get-RemainingRuntimeSec", script)
        self.assertIn("requested_duration_sec = $MaxRuntimeSec", script)
        self.assertIn("actual_duration_sec", script)
        self.assertIn("fast-edge-v6-validate", script)
        self.assertEqual(script.count('"fast-edge-v6-evaluate"'), 2)
        self.assertIn("FAST_FIRST_V6_EVALUATION_RUNNING", script)
        self.assertIn("Deterministic repeat mismatch", script)
        self.assertIn("READY_FOR_POSTPROCESS", script)
        self.assertIn("STOPPED_INCOMPLETE", script)
        self.assertIn("execution_probe_allowed", script)
        self.assertIn("E:\\ZolotyayLopata-data", script)
        self.assertIn("rows = [int]$first.metrics.main.oos.event_count", script)
        self.assertIn("grid_search = $false", script)
        self.assertIn("execution_probe = $false", script)
        self.assertIn("paper_forward = $false", script)
        self.assertIn("live_orders = $false", script)
        self.assertIn("api_keys = $false", script)
        self.assertGreaterEqual(script.count('"-RunId", $RunId'), 3)
        self.assertIn(
            "18af65fc211d31a8a0f38bc6d9161b4adf7a92404aba788dfb66c45d2af850a9",
            script,
        )
        self.assertIn("fast_first_weekend_liquidity_window_planonly_20260714_143640.json", script)


class TradingTestRunnerPlanTests(unittest.TestCase):
    def test_fast_shard_plan_exposes_timeout_files_and_commands(self) -> None:
        script = REPO_ROOT / "tools" / "run_trading_tests.ps1"
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-PlanOnly",
                "-Json",
                "-Shard",
                "fast",
                "-TimeoutSec",
                "123",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        plan = json.loads(completed.stdout)
        self.assertEqual(plan["shard"], "fast")
        self.assertEqual(plan["timeout_sec"], 123)
        self.assertTrue(plan["test_files"])
        self.assertEqual(len(plan["commands"]), 1)
        self.assertIn("unittest", plan["commands"][0])


if __name__ == "__main__":
    unittest.main()
