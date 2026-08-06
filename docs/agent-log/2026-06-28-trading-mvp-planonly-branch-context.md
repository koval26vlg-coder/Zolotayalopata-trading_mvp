# trading_mvp PlanOnly branch context

- Date: 2026-06-28 13:57:35 +03:00
- Agent: Codex
- User request: continue the trading_mvp objective without wasting limits during/around long runs.
- Gate: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700; no new long run started.
- Goal step: short engineering improvement only.

## What changed
- Updated tools/start_ws_collect_visible.ps1 so -PlanOnly includes branch_decision, selected_branch and branch_source.
- PlanOnly branch context is derived from trading_next_goal_step.ps1 to avoid running the heavier branch selector during preview.
- Added a regression/smoke test in trading_mvp/tests/test_visible_ws_collect_wrapper.py.
- Made an existing funding-block test tolerant of the current READY_FOR_POSTPROCESS gate when postprocess_block is absent.
- Saved latest 6h preview artifact: exports/trading-mvp/run/ws_collect_6h_plan_preview_latest.json.

## Verification
- Gate check: READY_FOR_POSTPROCESS, expected_outputs_complete=true, rows=2745067, errors=0.
- Targeted tests: python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate -> 12 tests OK, 1 skipped.
- Full tests: C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests -> 210 tests OK, 1 skipped.
- Bundled Codex Python full discovery failed because requests is not installed there; system Python has requests 2.32.3 and passed.

## Current decision
- No accepted trading strategy yet.
- No live orders, API keys, leverage or margin.
- Next branch remains spot_maker_liquidity_sweep_reversal_event_quality.
- Next long step still requires explicit user approval with ConfirmedLongRun / visible terminal.
