# trading_mvp next-step postprocess-block evidence

Date: 2026-06-27
Agent: Codex
Request: continue active trading_mvp goal without starting long runs.

## Context
- Active gate is READY_FOR_POSTPROCESS for `funding_collect_7d_spotliq_visible_20260617_185732`.
- Funding guard review blocks that completed dataset: `funding_final_review_guard_stop_verify_20260627.json`, `ok=false`, `status=not_ready_for_postprocess`, `min_rows_per_cycle=9`.
- Previous fix made `check_active_run_gate.ps1` expose `postprocess_block` and override stale next-step text.

## Change
- Updated `tools/trading_next_goal_step.ps1` so `state` now includes:
  - `gate_warning`
  - `gate_next_step_after_ready`
  - `gate_raw_next_step_after_ready`
  - `gate_postprocess_block`

## Verification
- `tools/trading_next_goal_step.ps1 -Json` returns decision `SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT` and includes `state.gate_postprocess_block.path` plus reasons `data_quality:min_min_rows_per_cycle` / `min_min_rows_per_cycle`.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, failures=0, warnings=0.
- `tools/trading_strategy_acceptance_gate.ps1`: `research_only_no_accepted_strategy`, live orders false.
- `python -m unittest discover -s trading_mvp/tests`: 198 OK.

## Next
- Do not use funding 7d dataset for rank/backtest/paper-forward.
- Next long data action remains visible 6h WS collect only after explicit user confirmation.
