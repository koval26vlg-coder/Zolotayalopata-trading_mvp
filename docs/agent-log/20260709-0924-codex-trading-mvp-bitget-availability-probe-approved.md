# trading_mvp Bitget listing-event availability probe

Generated: 2026-07-09 09:23:51 +03:00

## Result
- Availability decision: LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET
- Availability slots: 60; ok=36; api_error=14; no_data_or_delisted=10
- OK events by exchange: bitget=9; gateio=7; mexc=20
- Max single-exchange OK event fraction: 0.555555555555556
- Preview decision: LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL
- Preview selected: events=36; bases=36; exchanges=3; estimated_requests=36
- Approval packet: READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET; fail_count=0; would_start=False

## Gate
- next_goal_decision: LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL
- next_step_after_ready: Await explicit user approval before implementing/running visible public OHLCV history collect. Do not start collect/grid/replay/live/API/paper-forward automatically.
- replay_allowed: False
- collect_allowed: False
- grid_allowed: False

## Required user input for actual collect
$(System.Collections.Specialized.OrderedDictionary.approval_packet.start_requires_exact_user_input)

## Artifacts
- availability: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_history_availability_preflight_20260709_091847.json
- preview: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_history_collect_preview_20260709_092116.json
- approval_packet: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_history_collect_approval_packet_current.json
