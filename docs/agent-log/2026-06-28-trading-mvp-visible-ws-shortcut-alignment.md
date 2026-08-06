# trading_mvp visible WS shortcut alignment

Date: 2026-06-28 15:56:19 +03:00
Agent: Codex
User request: continue the active trading_mvp goal.

## Plan
- Respect active-run gate.
- Do not launch a long collector without explicit approval.
- Verify and lock shortcut routing for the next visible 6h WS collect so the user-facing .cmd files cannot drift away from the guarded wrapper path.

## Done
- Checked active-run gate: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700; rows=2745067; errors=0.
- Verified TRADING_PREVIEW_6H_WS.cmd routes to tools/start_ws_collect_visible.ps1 -PlanOnly.
- Verified TRADING_START_6H_WS_CONFIRMED.cmd prompts START6H and routes to tools/start_ws_collect_visible.ps1 -ConfirmedLongRun.
- Added visible_ws_collect_shortcut_alignment to tools/trading_edge_preflight.ps1.
- Updated trading_mvp/tests/test_visible_ws_collect_wrapper.py to require visible_ws_collect_shortcut_alignment=pass.

## Files changed
- C:\Users\koval\Documents\ZolotyayLopata\tools\trading_edge_preflight.ps1
- C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\tests\test_visible_ws_collect_wrapper.py
- C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-06-28-trading-mvp-visible-ws-shortcut-alignment.md
- D:\AionUi-Paperclip\docs\agent-log\2026-06-28-codex-trading-mvp-visible-ws-shortcut-alignment.md

## Verification
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate: 13 OK, 1 skipped.
- C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests: 211 OK, 1 skipped.
- tools/trading_edge_preflight.ps1 -Json: ok=true, status=READY_FOR_EDGE_PROOF_STEP, visible_ws_collect_shortcut_alignment=pass.
- tools/start_ws_collect_visible.ps1 -Hours 0.01 -PlanOnly: would_start=false and selected_branch=spot_maker_liquidity_sweep_reversal_event_quality.
- tools/trading_next_goal_step.ps1 -Json: decision=SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.
- tools/trading_strategy_acceptance_gate.ps1 -Json: accepted=false, live_orders=false, stage=research_only_no_accepted_strategy.

## Risks and limits
- No accepted strategy exists.
- No paper-forward/live execution is allowed.
- Actual 6h WS collect remains the next data step but requires explicit user approval and visible terminal/monitor.
