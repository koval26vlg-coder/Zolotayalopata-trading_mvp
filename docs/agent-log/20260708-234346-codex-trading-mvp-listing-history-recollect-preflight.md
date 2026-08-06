# trading_mvp listing-event history recollect/preflight gate

Date: 2026-07-08 23:43:46 +03:00
Agent: Codex
Request: continue active trading_mvp edge goal after visible listing-event OHLCV history collect confirmation.

## Current state
- Active run gate is READY_FOR_POSTPROCESS for listing_event_history_collect_20260708_210753.
- Replay/grid/paper-forward/live/API keys remain blocked: eplay_allowed=false.
- Data-quality rejected the current listing-event history artifact.
- Next decision remains LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN.

## Evidence
- Data-quality fail reasons include min_ok_exchanges, max_single_exchange_ok_event_fraction, and max_api_error_slot_rate.
- Current history artifact is effectively MEXC-only in OK rows and failed Gate coverage.
- Updated collect preview now returns LISTING_EVENT_HISTORY_COLLECT_PREVIEW_BLOCKED_NEEDS_REVISED_TWO_VENUE_PREFLIGHT, not approval for another actual collect.

## Changes
- 	ools/trading_listing_event_history_planonly.ps1: reads previous quality report and emits rejected/recollect plan with quality evidence.
- 	ools/trading_listing_event_history_collect_preview.ps1: passes previous quality into preview and preserves rejected gate on update.
- 	rading_mvp/src/listing_event_history_collect_plan.py: added previous-quality summary and hard-block contract for two-venue preflight.
- 	rading_mvp/tests/test_listing_event_history_collect_plan.py: added regression for quality-rejected repeat preview blocking.
- 	rading_mvp/tests/test_visible_ws_collect_wrapper.py: added regression for PlanOnly quality rejection routing.
- docs/agent-log/active-run-gate.json: updated current next step and last preview output.

## Verification
- PowerShell parser checks OK for updated wrappers.
- Targeted tests OK.
- Full suite: python -m unittest discover -s trading_mvp/tests -> 336 OK, 4 skipped.

## Next allowed step
Implement/run only a short explicit 	wo-venue public history availability preflight in visible/confirmed mode, or add that preflight as a separate PlanOnly/approval packet first. Do not run actual OHLCV collect, replay, grid, paper-forward, live orders, API keys, leverage or margin.
