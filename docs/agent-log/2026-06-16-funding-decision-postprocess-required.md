# 2026-06-16 Funding Decision Requires Postprocess Evidence

## Goal
Prevent `funding-decision-report` from accepting a paper-forward candidate using only auxiliary gate/frontier/sensitivity artifacts.

## Problem
Postprocess carries the canonical `research_acceptance` result. It includes the full backtest acceptance, OOS, walk-forward, stress and data-quality evidence. The decision report previously accepted postprocess evidence when supplied, but did not require it for standalone positive decisions.

## Code Changes
- Added `postprocess_report` to the mandatory artifact set in `funding_decision_report`.
- A ready collector with no postprocess artifact now gets `missing:postprocess_report`.
- Existing failed-postprocess handling remains:
  - `postprocess_status:<status>` when postprocess is not OK;
  - `postprocess_research_not_accepted` and `postprocess:<reason>` when research acceptance fails.
- `funding-final-review` already passes its postprocess artifact into `funding_decision_report`, so final-review behavior is aligned with the stricter gate.

## Regression Coverage
- Updated positive decision test to provide accepted postprocess evidence.
- Added `test_funding_decision_report_rejects_missing_postprocess_evidence`.
- Kept negative tests for failed postprocess, missing stress, and missing OOS/walk evidence.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_decision_report_accepts_only_full_metric_gate`
  - `test_funding_decision_report_rejects_missing_postprocess_evidence`
  - `test_funding_decision_report_rejects_sensitivity_without_stress_evidence`
  - `test_funding_decision_report_rejects_sensitivity_without_oos_walk_evidence`
  - `test_funding_decision_report_rejects_failed_postprocess_research_gate`
  - result: OK.
- Full suite:
  - `python -m unittest discover -s trading_mvp/tests`
  - result: `168 tests OK`.

## Collector Status After Change
- artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_043956.json`
- accepted: `false`
- stage: `collecting_funding`
- `ready_for_postprocess=false`
- cycles: `87 / 288`
- line_count: `2088`
- errors: `522`
- collector processes are alive.

## Decision
Do not run `funding-final-review` yet. Continue condition-based waiting until the collector is final and strict readiness passes.
