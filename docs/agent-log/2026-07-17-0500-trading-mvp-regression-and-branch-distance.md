# 2026-07-17 05:00 +03 - regression and branch-distance checkpoint

## Verified state

- Full visible regression run: `trading_mvp_full_regression_20260717_045201`.
- Result: `940 OK`, `5 skipped`, `0` failures/errors, `379.377s`, `exit_code=0`.
- Basis v2 verdict remains `INFEASIBLE_ON_CURRENT_DATA`; OOS was not read.
- Active gate remains `READY_FOR_POSTPROCESS`, with replay/grid/probe/paper/live blocked for this branch.

## Reliability fixes

- `tools/run_trading_mvp_full_regression_visible.ps1` now forces UTF-8 consistently for Python and nested Windows PowerShell subprocesses.
- `pit_membership_drift_execution_probe_collector._atomic_write_json` retries transient Windows `PermissionError` during atomic manifest replacement, with a bounded eight-attempt backoff.
- New retry unit test passed.

## Research decision

- Do not open time-series trend or another return factor on the current daily cache: the point-in-time/delisted-universe defect is unchanged.
- Do not retune weekend, funding, basis, listing, slow-liquidity, wick, residual or HFT branches on their existing evidence.
- Continue the independent PIT shadow track or create a materially new PlanOnly historical-membership source contract.

## Evidence

- Analysis: `docs/analysis/2026-07-17-trading-mvp-next-branch-distance-audit.md`.
- Full regression log: `exports/trading-mvp/run/trading_mvp_full_regression_20260717_045201.full-regression.visible.log`.
- Launch record: `docs/agent-log/run-gates/trading_mvp_full_regression_20260717_045201.visible-launch.json`.
