# 2026-06-16 Funding Sensitivity OOS/Walk Gate

## Goal
Make OOS and walk-forward evidence mandatory in funding sensitivity and decision reports before any paper-forward candidate can be accepted.

## Problem
`funding_decision_report` previously rejected OOS/walk-forward failures only when the sensitivity artifact said those checks were enabled. A sensitivity artifact without OOS/walk-forward evidence could still pass if other auxiliary fields looked good.

## Code Changes
- `run_funding_sensitivity` now marks scenarios without OOS as `oos_required`.
- `run_funding_sensitivity` now marks scenarios without walk-forward as `walk_forward_required`.
- `funding_decision_report` now rejects sensitivity artifacts when:
  - `oos_enabled` is not explicitly `true`;
  - `walk_forward_enabled` is not explicitly `true`;
  - OOS is enabled but zero scenarios pass;
  - walk-forward is enabled but zero scenarios pass.
- Decision summary now exposes:
  - `sensitivity_oos_enabled`;
  - `sensitivity_walk_forward_enabled`.

## Regression Coverage
- Extended `test_funding_sensitivity_requires_stress_for_research_acceptance` to assert `oos_required` and `walk_forward_required`.
- Added `test_funding_decision_report_rejects_sensitivity_without_oos_walk_evidence`.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_sensitivity_requires_stress_for_research_acceptance`
  - `test_funding_decision_report_rejects_sensitivity_without_oos_walk_evidence`
  - `test_funding_decision_report_rejects_sensitivity_without_stress_evidence`
  - `test_funding_decision_report_accepts_only_full_metric_gate`
  - result: OK.
- Full suite:
  - `python -m unittest discover -s trading_mvp/tests`
  - result: `167 tests OK`.
- Runtime smoke:
  - action: `funding-sensitivity`
  - profile: `FundingStrictResearch`
  - output: `exports/trading-mvp/backtests/funding_sensitivity_oos_walk_gate_smoke_20260616.json`
  - summary includes `oos_enabled=true`, `walk_forward_enabled=true`, `stress_enabled=true`, and `accepted_scenarios=0` because OOS/walk-forward did not pass on the partial dataset.

## Collector Status After Change
- artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_043721.json`
- accepted: `false`
- stage: `collecting_funding`
- `ready_for_postprocess=false`
- cycles: `86 / 288`
- line_count: `2064`
- errors: `516`
- collector processes are alive.

## Decision
Do not run `funding-final-review` yet. Continue condition-based waiting until the collector is final and strict readiness passes.
