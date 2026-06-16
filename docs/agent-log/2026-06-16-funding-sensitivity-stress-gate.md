# 2026-06-16 Funding Sensitivity Stress Gate

## Goal
Make stress evidence explicit in funding sensitivity and decision reports before any paper-forward candidate can be accepted.

## Problem
`run_funding_sensitivity` used stress inside `evaluate_funding_backtest_metrics` when stress was enabled, but its summary did not expose whether stress was enabled, whether stress assumptions were non-zero, or how many scenarios passed stress. A standalone `funding-decision-report` could therefore accept an auxiliary sensitivity artifact that lacked explicit stress evidence.

## Code Changes
- `run_funding_sensitivity` now records:
  - `stress_enabled`;
  - `stress_assumptions_passed`;
  - `stress_accepted_scenarios`.
- Per-scenario `research_acceptance` now includes:
  - `stress_required_passed`;
  - `stress_assumptions_passed`;
  - `stress_accepted`.
- Scenarios without stress now get `stress_required` in research reasons.
- `funding_decision_report` now rejects sensitivity artifacts when:
  - stress is not enabled;
  - stress assumptions are missing;
  - zero scenarios passed stress.
- `funding-final-review` summary now exposes `sensitivity_stress_accepted_scenarios`.

## Regression Coverage
- Added `test_funding_sensitivity_requires_stress_for_research_acceptance`.
- Added `test_funding_decision_report_rejects_sensitivity_without_stress_evidence`.
- Updated positive decision test to require explicit stress evidence.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_sensitivity_requires_stress_for_research_acceptance`
  - `test_funding_decision_report_rejects_sensitivity_without_stress_evidence`
  - `test_funding_decision_report_accepts_only_full_metric_gate`
  - `test_funding_decision_report_rejects_failed_postprocess_research_gate`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite:
  - `python -m unittest discover -s trading_mvp/tests`
  - result: `166 tests OK`.
- Runtime smoke:
  - action: `funding-sensitivity`
  - profile: `FundingStrictResearch`
  - output: `exports/trading-mvp/backtests/funding_sensitivity_stress_gate_smoke_20260616.json`
  - summary includes `stress_enabled=true`, `stress_assumptions_passed=true`, `stress_accepted_scenarios=1`.

## Collector Status After Change
- artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_043435.json`
- accepted: `false`
- stage: `collecting_funding`
- `ready_for_postprocess=false`
- cycles: `86 / 288`
- line_count: `2064`
- errors: `516`
- collector processes are alive.

## Decision
Do not run `funding-final-review` until strict readiness passes. The next final review will now require stress evidence in sensitivity and postprocess research acceptance.
