# trading_mvp active gate funding block override

Date: 2026-06-27
Agent: Codex
Request: continue active trading_mvp goal without starting hidden/long runs.

## Context
- Active-run gate showed READY_FOR_POSTPROCESS for `funding_collect_7d_spotliq_visible_20260617_185732`.
- The same funding dataset was already rejected by guarded final-review: `funding_final_review_guard_stop_verify_20260627.json` with `ok=false`, `status=not_ready_for_postprocess`, reason `min_min_rows_per_cycle`.
- Risk: `check_active_run_gate.ps1` still printed stale `next_step_after_ready` pointing to funding final-review, which could lead a future agent into the rejected funding branch.

## Change
- Updated `tools/check_active_run_gate.ps1` with read-only detection of matching `funding_final_review_*.json` guard artifacts for completed funding runs.
- If the guard artifact blocks postprocess, the checker now reports:
  - `postprocess_block` details;
  - original `raw_gate_next_step_after_ready`;
  - overridden `next_step_after_ready` pointing to `tools/trading_next_goal_step.ps1` and guarded WS path.

## Verification
- `tools/check_active_run_gate.ps1 -Json`: status remains `READY_FOR_POSTPROCESS`, but warning now says funding postprocess is blocked by guard review and includes `postprocess_block.path`.
- `tools/trading_next_goal_step.ps1 -Json`: decision `SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT`.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, failures 0, warnings 0.
- `python -m unittest discover -s trading_mvp/tests`: 198 OK.

## Next
- Do not use the 7d funding dataset for rank/backtest/paper-forward.
- Next long action remains visible 6h WS collect only after explicit user confirmation.
- During any future `RUNNING` gate, do status-only.
