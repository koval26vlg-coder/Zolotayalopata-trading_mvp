# trading_mvp status command alignment swarm

- Time: 2026-06-27 13:52 +03:00
- Agent: Codex
- User request: используй Рой
- Workflow: D:\AionUi-Paperclip\docs\agent-workflows\2026-06-27-134209-319447-trading-mvp-status-command-alignment-checkpoint
- Result: Рой L1 Antigravity approve, L2 Antigravity approve, L3 Codex approve, L4 Codex approve, L5 Claude Code approve; workflow finalized as done.

## Plan
- Respect active-run gate and visible-run rules.
- Use swarm for independent checkpoint on stale legacy isible_collect_* commands.
- Do not launch collectors/backtests/replay/grid or funding postprocess.

## Changes
- 	ools/trading_goal_status.ps1: legacy isible_collect_* now resolves to WS commands when unding_blocked_by_swarm=true; explicit funding commands exposed as unding_visible_*.
- 	ools/trading_next_goal_step.ps1: same legacy alias alignment for next-step command output.
- 	rading_mvp/tests/test_visible_ws_collect_wrapper.py: added JSON-output regression tests for both status controllers.

## Verification
- 	rading_goal_status.ps1 -Json: legacy command redirects to start_ws_collect_visible.ps1 while explicit funding command remains separate.
- 	rading_next_goal_step.ps1 -Json: decision is SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT; primary command is WS PlanOnly.
- 	rading_edge_preflight.ps1 -Json: READY_FOR_EDGE_PROOF_STEP, ok=true, ail_count=0, warn_count=0.
- start_ws_collect_visible.ps1 -Hours 6 -PlanOnly: would_start=false, equires_confirmed_long_run=true, zero-line/schema/early-density guards enabled.
- python -m unittest discover -s trading_mvp/tests: 204 OK.

## Risks and limits
- No market long run was started.
- Funding dataset unding_collect_7d_spotliq_visible_20260617_185732 remains rejected for rank/backtest/paper-forward because guard review blocked data quality.
- Actual 6h WS collect still requires explicit user confirmation and visible terminal/monitor.
