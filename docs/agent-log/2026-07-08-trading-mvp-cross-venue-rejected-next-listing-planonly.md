# trading_mvp cross-venue rejected -> listing_event_drift_reversal PlanOnly

Context:
- Full cross-venue MEXC/Gate spot dislocation scan completed.
- Output: exports/trading-mvp/backtests/cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json
- Decision: REJECTED_NO_NET_EDGE_AFTER_BASE_FEES
- rows_read: 51278447
- bbo_rows: 36039132
- matched_bases: 12
- candidate_events: 2266
- eligible_events: 0
- max_gross_edge_bps: 66.34150236553671
- max_net_edge_bps: -2.658497634463288

Change:
- Repaired PlanOnly routing so a rejected cross-venue branch does not route back into itself.
- Next branch: listing_event_drift_reversal PlanOnly.
- No collect/grid/live/API/leverage/margin/paper-forward is allowed by this step.

Next valid move:
- Build listing_event_drift_reversal PlanOnly research scaffold: listing calendar requirements, survivorship/delist/freeze controls, base-fee cost hurdle, OOS/walk-forward/stress/economics gates.
