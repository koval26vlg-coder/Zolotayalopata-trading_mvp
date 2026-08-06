# trading_mvp listing-event history data-quality

Date: 2026-07-08 23:25:57 +03:00
Agent: Codex
User request: confirmed visible listing-event OHLCV history collect / continue goal.

## Outcome
- Existing visible listing-event OHLCV history collect listing_event_history_collect_20260708_210753 is final and ready for postprocess, but data-quality rejected it.
- Gate remains READY_FOR_POSTPROCESS with eplay_allowed=false.
- Current next decision: LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN.
- CLI routing now points to LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN, not stale collect-preview or replay.

## Evidence
- Rows: 2309 jsonl lines; OK OHLCV rows: 1953; placeholder rows: 356.
- OK events: 4 / 120.
- OK bases: 4.
- OK exchanges: 1.
- Gate OK rows are effectively MEXC-only; Gate historical coverage produced 0 OK rows in the collected artifact.
- API errors: 216; API error slot rate: 0.60.
- Failed thresholds include min OK events/bases/exchanges/slots, OK fractions, max API error slot rate, and max single-exchange concentration.

## Files changed
- 	rading_mvp/src/listing_event_history_quality.py
- 	rading_mvp/tests/test_listing_event_history_quality.py
- 	ools/trading_listing_event_history_data_quality.ps1
- 	ools/trading_next_goal_step.ps1
- 	ools/trading_goal_status.ps1
- 	ools/trading_branch_selector.ps1
- 	rading_mvp/tests/test_visible_ws_collect_wrapper.py
- docs/agent-log/active-run-gate.json

## Verification
- PowerShell parser checks OK for next-goal, goal-status, branch-selector, and data-quality scripts.
- python -m unittest trading_mvp.tests.test_listing_event_history_quality trading_mvp.tests.test_listing_event_history_collector: 8 OK.
- Targeted visible-wrapper regression: 3 OK.
- Full suite: python -m unittest discover -s trading_mvp/tests: 334 OK, 4 skipped.

## Next allowed step
Run PlanOnly recollect/design revision only:
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_listing_event_history_planonly.ps1 -Json

Do not run replay/grid/paper-forward/live/API keys. Fix the collection design first: improve Gate historical coverage or resample event universe so at least two venues have OK historical OHLCV while retaining no-data/delisted outcomes.
