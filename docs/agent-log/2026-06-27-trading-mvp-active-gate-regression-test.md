# trading_mvp active gate regression test

Date: 2026-06-27
Agent: Codex
Request: continue active trading_mvp goal without starting long runs.

## Context
- Funding 7d collect is final but rejected by guarded final-review (`min_rows_per_cycle=9`).
- `check_active_run_gate.ps1` and `trading_next_goal_step.ps1` now expose `postprocess_block` so the next proof step does not return to funding rank/backtest/paper-forward.

## Change
- Added `trading_mvp/tests/test_active_run_gate.py`.
- The test builds a temporary repo-like gate/manifest/funding directory and verifies:
  - completed funding gate with a blocking `funding_final_review_*.json` reports `postprocess_block` and overrides `next_step_after_ready`;
  - completed funding gate without a guard artifact preserves the raw next step.

## Verification
- `python -m unittest trading_mvp.tests.test_active_run_gate`: 2 OK.
- `python -m unittest discover -s trading_mvp/tests`: 200 OK.
- `tools/check_active_run_gate.ps1 -Json`: READY_FOR_POSTPROCESS with `postprocess_block` and warning.
- `tools/trading_next_goal_step.ps1 -Json`: `SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT`, `state.gate_postprocess_block` present.
- `tools/trading_edge_preflight.ps1 -Json`: READY_FOR_EDGE_PROOF_STEP, failures=0, warnings=0.
- `tools/trading_strategy_acceptance_gate.ps1`: research_only_no_accepted_strategy; live orders false.

## Next
- No market long-run was started.
- Next long action is still visible 6h WS collect after explicit user confirmation only.
