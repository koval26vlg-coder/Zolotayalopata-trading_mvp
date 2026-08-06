# trading_mvp shortcut alignment after status command swarm

- Time: 2026-06-27 13:58 +03:00
- Agent: Codex
- Goal: continue trading_mvp edge proof pipeline without starting long market runs.
- Gate: READY_FOR_POSTPROCESS only formally; funding postprocess remains blocked by data_quality:min_min_rows_per_cycle, min_rows_per_cycle=9.

## What changed
- 	ools/trading_goal_status.ps1: legacy isible_collect_*_shortcut now follows the active WS branch when unding_blocked_by_swarm=true; explicit funding shortcuts are exposed as unding_visible_collect_*_shortcut.
- 	ools/trading_next_goal_step.ps1: same shortcut alignment for next-step command output.
- 	rading_mvp/tests/test_visible_ws_collect_wrapper.py: regression coverage extended to shortcut fields.

## Verification
- 	rading_goal_status.ps1 -Json: legacy shortcut fields point to TRADING_PREVIEW_6H_WS.cmd / TRADING_START_6H_WS_CONFIRMED.cmd; funding shortcut fields remain TRADING_PREVIEW_7D_FUNDING.cmd / TRADING_START_7D_FUNDING_CONFIRMED.cmd.
- 	rading_next_goal_step.ps1 -Json: same shortcut alignment; decision remains SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.
- 	rading_edge_preflight.ps1 -Json: READY_FOR_EDGE_PROOF_STEP, ok=true, ail_count=0, warn_count=0.
- start_ws_collect_visible.ps1 -Hours 6 -PlanOnly: would_start=false, equires_confirmed_long_run=true, zero-line/schema/early-density guards enabled.
- python -m unittest discover -s trading_mvp/tests: 204 OK.

## Risks
- No collectors/backtests/replay/grid or live/API/leverage/margin actions were run.
- Actual 6h WS collect still requires explicit user approval and visible terminal/monitor.
