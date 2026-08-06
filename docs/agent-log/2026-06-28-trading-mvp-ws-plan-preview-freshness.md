# Trading MVP visible WS PlanOnly freshness guard

- time: 2026-06-28 16:17:25 +03:00
- agent: Codex
- user_request: continue active trading_mvp goal
- goal: prove or reject a high-winrate trading edge for non-Binance markets via data/backtest/OOS/walk-forward/stress/economics/paper-forward gates.

## Context
- Active run gate checked first: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700.
- Current strategy acceptance remains false; live orders and paper-forward remain blocked.
- No long collector, grid, replay, paper-forward, API-key, leverage or live action was started.

## Swarm
- Created Aion workflow: D:\AionUi-Paperclip\docs\agent-workflows\2026-06-28-160821-121559-trading-mvp-dense-ws-checkpoint-review.
- Risk flags: trading=true, long_running=true.
- Antigravity L1 failed with empty stdout and no DB fallback; recorded tmp-l1-antigravity-runtime-failure.md and tmp-codex-fallback-verdict.md.
- Status: swarm_limited; Codex continued manually under the same gates.

## Changes
- tools/start_ws_collect_visible.ps1:
  - Added plan_preview_latest_path and refreshed exports/trading-mvp/run/ws_collect_6h_plan_preview_latest.json during multi-hour PlanOnly runs.
  - The preview artifact now contains self_preflight_guard, postprocess plan, replay-validation plan and command_after_explicit_approval.
- tools/trading_edge_preflight.ps1:
  - Added visible_ws_collect_plan_preview_freshness check.
  - Stale/missing preview is warning-only to avoid circular FIX_PREFLIGHT; a fresh preview passes and is exposed as visible_ws_collect_plan_preview_latest.
- trading_mvp/tests/test_visible_ws_collect_wrapper.py:
  - Added assertions for PlanOnly latest preview and preflight freshness check.
- exports/trading-mvp/run/ws_collect_6h_plan_preview_latest.json:
  - Refreshed with current 6h PlanOnly output; would_start=false; next_goal_decision=SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.

## Verification
- start_ws_collect_visible.ps1 -Hours 6 -PlanOnly: would_start=false, selected_branch=spot_maker_liquidity_sweep_reversal_event_quality, current decision is SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate: 13 OK, 1 skipped.
- tools/trading_edge_preflight.ps1 -Json: ok=true, READY_FOR_EDGE_PROOF_STEP, visible_ws_collect_plan_preview_freshness=pass.
- python -m unittest discover -s trading_mvp\\tests: 211 OK, 1 skipped.
- check_active_run_gate.ps1 -Json: READY_FOR_POSTPROCESS, expected_outputs_complete=true, rows=2745067, errors=0.
- trading_strategy_acceptance_gate.ps1 -Json: accepted=false, live_orders=false.

## Next
- Do not paper/live.
- Next useful action is explicit user-approved visible 6h WS collect, or another short proof-quality engineering task.
- Goal continuation alone is not explicit approval for ConfirmedLongRun.
