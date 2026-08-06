# trading_mvp branch selector funding block hardening

- Time: 2026-06-27 14:01 +03:00
- Agent: Codex
- Goal: continue high-winrate edge proof pipeline without starting long market runs.
- Gate: READY_FOR_POSTPROCESS only formally; funding postprocess remains blocked by data_quality:min_min_rows_per_cycle, min_rows_per_cycle=9.

## What changed
- 	ools/trading_branch_selector.ps1: when unding_blocked_by_swarm=true, nested selected_evidence.funding now overrides stale scorecard 
ext_action.
- The old scorecard 
ext_action is preserved as original_scorecard_next_action, but current 
ext_action is locked_by_swarm_do_not_run_7d_funding_collect_or_final_review.
- Guard block evidence is copied into the funding evidence block: postprocess_block_reasons, min_rows_per_cycle.
- 	rading_mvp/tests/test_visible_ws_collect_wrapper.py: regression test added for branch selector funding block.

## Verification
- 	rading_branch_selector.ps1 -Json: decision NEXT_BRANCH_SPOT_MAKER_LIQUIDITY_SWEEP_REVERSAL; funding status locked_by_swarm; funding next_action no longer points to visible 7d funding collect.
- 	rading_edge_preflight.ps1 -Json: READY_FOR_EDGE_PROOF_STEP, ok=true, ail_count=0, warn_count=0.
- 	rading_next_goal_step.ps1 -Json: primary command is WS PlanOnly; funding blocked true; gate block reason preserved.
- start_ws_collect_visible.ps1 -Hours 6 -PlanOnly: would_start=false, equires_confirmed_long_run=true, zero-line/schema/early-density guards enabled.
- python -m unittest discover -s trading_mvp/tests: 205 OK.

## Risks and limits
- No collectors/backtests/replay/grid or live/API/leverage/margin actions were run.
- Actual 6h WS collect still requires explicit user approval and visible terminal/monitor.
