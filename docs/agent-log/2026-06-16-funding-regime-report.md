# 2026-06-16 Funding Regime Report

## Goal
Make volume/regime filters auditable per market before final funding acceptance, without running final postprocess on an incomplete dataset and without live orders.

## Collector Status
- stage: `collecting_funding`
- `ready_for_postprocess=false`
- cycles: `83 / 288`
- rows at audit: `1992`
- latest partial regime rows: `2016`
- collector processes still alive

Final postprocess was not run.

## Code Changes
- Added `funding_regime_report` and `funding_regime_report_file`.
- Added default output path `default_funding_regime_report_path`.
- Added CLI command `funding-regime-report`.
- Added PowerShell action `funding-regime-report`.
- Added tests for:
  - per-market regime/volume blockers;
  - CLI parser coverage;
  - strict preset coverage.

## Report Behavior
For each market, the report aggregates rows across cycles and exposes:
- funding persistence metrics;
- regime observations;
- average/min liquidity and volume fields;
- basis average/std;
- average spot/perp spreads;
- risk-adjusted edge;
- blockers split into source, persistence, regime, liquidity, and economics.

## Partial Dataset Diagnostic
Artifact:
- `exports/trading-mvp/funding/funding_regime_report_partial_20260616.json`

Summary:
- input_rows: `2016`
- markets: `24`
- eligible_markets: `0`
- source_pass: `18`
- persistence_pass: `24`
- regime_pass: `24`
- liquidity_pass: `1`
- economics_pass: `0`

Top blocker counts:
- `expected_edge_below_min`: `24`
- `risk_adjusted_edge_below_min`: `24`
- `break_even_horizon_too_long`: `23`
- `spot_top_liquidity_low`: `23`
- `spot_top_liquidity_regime_low`: `23`
- `basis_below_min`: `18`

Interpretation:
- Current partial data is not a paper-forward candidate.
- Regime/persistence are not the current bottleneck.
- The main bottlenecks are economics after fees/slippage and spot top-of-book liquidity.
- This is diagnostic only because the 24h collector is not final.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_funding_regime_report_exposes_volume_and_regime_blockers`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite:
  - `python -m unittest discover -s trading_mvp/tests`
  - result: `163 tests OK`.

## Next Gate
Continue condition-based waiting. When `ready_for_postprocess=true`, run strict `funding-final-review`. Use the regime report to interpret whether failures come from economics, liquidity, regime instability, or source availability.

## Follow-Up Readiness Audit
- artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616.json`
- accepted: `false`
- stage: `collecting_funding`
- next_action: `wait_and_recheck`
- `ready_for_postprocess=false`
- collector_status: `running_or_waiting`
- cycles: `84 / 288`
- line_count: `2016`
- errors: `504`

Blockers:
- `collector_not_ready`
- `readiness:status_not_final`
- `readiness:data_quality:min_completed_cycles`
- `readiness:data_quality:min_unique_cycles`

Decision: continue the goal, but do not run final postprocess/backtest until the collector is final and strict readiness passes.

## Continuation Audit 2026-06-16 04:25 Local
- artifact: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_042533.json`
- accepted: `false`
- stage: `collecting_funding`
- next_action: `wait_and_recheck`
- `ready_for_postprocess=false`
- collector_status: `running_or_waiting`
- cycles: `84 / 288`
- line_count: `2016`
- errors: `504`

Blockers:
- `collector_not_ready`
- `readiness:status_not_final`
- `readiness:data_quality:min_completed_cycles`
- `readiness:data_quality:min_unique_cycles`

Decision: skipped `funding-final-review` because the strict data-quality gate is not satisfied. Continue condition-based waiting.
