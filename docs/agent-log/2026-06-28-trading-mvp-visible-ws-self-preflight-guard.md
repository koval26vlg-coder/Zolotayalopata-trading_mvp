# trading_mvp visible WS self-preflight guard

Date: 2026-06-28 15:45:36 +03:00
Agent: Codex
User request: continue the active trading_mvp goal.

## Plan
- Respect active-run gate before any substantive step.
- Avoid launching a long run without explicit user approval.
- Close the direct-wrapper bypass where start_ws_collect_visible.ps1 -ConfirmedLongRun could be called without the edge preflight guard.

## Done
- Checked active-run gate: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700; rows=2745067; errors=0.
- Added self_preflight_guard to tools/start_ws_collect_visible.ps1.
- Confirmed WS collect now runs tools/trading_edge_preflight.ps1 -Json before starting a collector.
- Confirmed WS collect refuses to start unless preflight ok=true, status=READY_FOR_EDGE_PROOF_STEP, and current_scorecard_freshness=pass.
- PlanOnly output now exposes self_preflight_guard metadata.
- Updated trading_mvp/tests/test_visible_ws_collect_wrapper.py to assert the self-preflight guard markers and PlanOnly metadata.

## Files changed
- C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1
- C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\tests\test_visible_ws_collect_wrapper.py
- C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-06-28-trading-mvp-visible-ws-self-preflight-guard.md
- D:\AionUi-Paperclip\docs\agent-log\2026-06-28-codex-trading-mvp-visible-ws-self-preflight-guard.md

## Verification
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate: 13 OK, 1 skipped.
- C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests: 211 OK, 1 skipped.
- tools/trading_edge_preflight.ps1 -Json: ok=true, status=READY_FOR_EDGE_PROOF_STEP, current_scorecard_freshness=pass.
- tools/start_ws_collect_visible.ps1 -Hours 0.01 -PlanOnly: would_start=false, self_preflight_guard.required_status=READY_FOR_EDGE_PROOF_STEP, self_preflight_guard.required_check=current_scorecard_freshness.
- tools/trading_next_goal_step.ps1 -Json: decision=SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.
- tools/trading_strategy_acceptance_gate.ps1 -Json: accepted=false, live_orders=false, stage=research_only_no_accepted_strategy.

## Risks and limits
- No accepted strategy exists yet.
- No live orders, API keys, leverage, margin or paper-forward are allowed.
- Actual 6h WS collect still requires explicit user approval and visible terminal/monitor.
