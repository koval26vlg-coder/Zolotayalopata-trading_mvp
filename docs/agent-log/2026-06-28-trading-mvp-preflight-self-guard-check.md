# trading_mvp preflight self-guard check

Date: 2026-06-28 15:51:09 +03:00
Agent: Codex
User request: continue the active trading_mvp goal.

## Plan
- Respect active-run gate.
- Do not launch long collectors, replay, grid, postprocess or paper-forward without explicit approval.
- Make short proof-pipeline progress by making the global edge preflight verify that visible WS collect cannot bypass the current scorecard freshness guard.

## Done
- Checked active-run gate: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700; rows=2745067; errors=0.
- Added visible_ws_collect_self_preflight_guard to tools/trading_edge_preflight.ps1.
- Updated trading_mvp/tests/test_visible_ws_collect_wrapper.py to require the new preflight check and pass status.
- Confirmed PlanOnly exposes self_preflight_guard metadata and does not start a collector.

## Files changed
- C:\Users\koval\Documents\ZolotyayLopata\tools\trading_edge_preflight.ps1
- C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\tests\test_visible_ws_collect_wrapper.py
- C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-06-28-trading-mvp-preflight-self-guard-check.md
- D:\AionUi-Paperclip\docs\agent-log\2026-06-28-codex-trading-mvp-preflight-self-guard-check.md

## Verification
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate: 13 OK, 1 skipped.
- C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests: 211 OK, 1 skipped.
- tools/trading_edge_preflight.ps1 -Json: ok=true, status=READY_FOR_EDGE_PROOF_STEP, visible_ws_collect_self_preflight_guard=pass.
- tools/start_ws_collect_visible.ps1 -Hours 0.01 -PlanOnly: would_start=false, self_preflight_guard.required_status=READY_FOR_EDGE_PROOF_STEP, required_check=current_scorecard_freshness.
- tools/trading_next_goal_step.ps1 -Json: decision=SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.
- tools/trading_strategy_acceptance_gate.ps1 -Json: accepted=false, live_orders=false, stage=research_only_no_accepted_strategy.

## Risks and limits
- No accepted strategy exists yet.
- No paper-forward/live execution is allowed.
- Actual 6h WS collect remains the next data step but requires explicit user approval and visible terminal/monitor.
