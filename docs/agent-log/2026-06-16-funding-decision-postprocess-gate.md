# 2026-06-16 Funding Decision Postprocess Gate

## Goal
Tighten the funding acceptance pipeline so a positive `funding-decision-report` cannot bypass the final postprocess `research_acceptance` gate.

## Problem
`funding-final-review` creates a postprocess artifact with the canonical `research_acceptance` result, but `funding_decision_report` previously decided from auxiliary gate/frontier/sensitivity reports only. That could create an inconsistent state where decision looked accepted even though postprocess research acceptance failed and no paper-forward plan was created.

## Code Changes
- Added optional `postprocess_report_path` to `funding_decision_report`.
- Added `postprocess_research_not_accepted` and `postprocess:<reason>` blockers when the postprocess research gate fails.
- Added postprocess summary fields to decision report output.
- Wired `run_funding_final_review_file` to pass its postprocess artifact into `funding_decision_report`.
- Added CLI flag `--postprocess-report` for `funding-decision-report`.
- Added PowerShell wrapper parameter `-PostprocessReportPath`.

## Regression Coverage
- Added `test_funding_decision_report_rejects_failed_postprocess_research_gate`.
- Extended CLI parser smoke to cover `--postprocess-report`.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_decision_report_rejects_failed_postprocess_research_gate`
  - `test_funding_decision_report_accepts_only_full_metric_gate`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite:
  - `python -m unittest discover -s trading_mvp/tests`
  - result: `164 tests OK`.
- PowerShell smoke:
  - action: `funding-decision-report`
  - new parameter: `-PostprocessReportPath`
  - output: `exports/trading-mvp/funding/funding_decision_report_postprocess_gate_smoke_20260616.json`
  - result: command accepted the parameter and preserved `wait_for_final_dataset`.

## Collector Status After Change
- artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_043036.json`
- accepted: `false`
- stage: `collecting_funding`
- `ready_for_postprocess=false`
- cycles: `85 / 288`
- line_count: `2040`
- errors: `510`
- collector processes are still alive.

## Decision
Do not run `funding-final-review` yet. Continue condition-based waiting until the collector is final and strict data-quality readiness passes.
