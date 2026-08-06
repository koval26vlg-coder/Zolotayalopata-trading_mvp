# trading_mvp listing-event history normalizer ready

Generated: 2026-07-09 09:50:48 +03:00

## Collect
- run_id: listing_event_history_collect_bitget_accepted_20260709_092116
- final: True
- completed/planned: 36/36
- ohlcv_rows: 2554
- placeholder_rows: 0
- errors: 0
- http_requests: 36

## Data quality
- artifact: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_history_data_quality_20260709_093747.json
- decision: LISTING_EVENT_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_NORMALIZER
- accepted: true

## Normalizer
- artifact: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_normalizer_planonly_20260709_094518.json
- decision: LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY
- source: listing_event_history
- ok_events: 36
- ok_unique_bases: 30
- ok_exchange_count: 3
- max_single_exchange_ok_event_fraction: 0.555555555555556
- replay_allowed_now: True
- grid_allowed_now: False

## Gate
- next_goal_decision: LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY
- next_step_after_ready: Implement read-only listing_event_drift_reversal event replay PlanOnly on normalized events. No grid/live/API/paper-forward.
- replay_allowed: True
- grid_allowed: False
- collect_allowed: False

## Verification
- python313 -m unittest trading_mvp.tests.test_listing_event_normalizer trading_mvp.tests.test_listing_event_history_quality trading_mvp.tests.test_visible_ws_collect_wrapper: 34 OK, 4 skipped

## Code changes
- trading_mvp/src/listing_event_normalizer.py: added listing_event_history mode.
- tools/trading_listing_event_normalizer_planonly.ps1: auto-picks accepted history artifacts from gate and sets replay_allowed from normalizer result.
- trading_mvp/tests/test_listing_event_normalizer.py: added history normalizer regression test.
