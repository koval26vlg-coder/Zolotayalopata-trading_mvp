# trading_mvp listing_event_drift_reversal PlanOnly

Context:
- Previous branch cross_venue_spot_dislocation_inventory_rebalance was rejected by full scan under base fees/buffers.
- Next branch is listing_event_drift_reversal, research-only.

Implemented:
- Added tools/trading_listing_event_planonly.ps1.
- The script is PlanOnly: no collect, no grid, no live orders, no API keys, no leverage/margin, no paper-forward.
- It defines event-calendar schema, base/VIP0 cost hurdle, hypotheses, data requirements, OOS/walk-forward/stress/economics gates and rejection gates.

Expected current decision:
- LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_NEEDS_BIAS_CONTROLLED_EVENT_CALENDAR unless a local listing calendar artifact already exists.

Next valid move:
- Build or source a local bias-controlled listing/delisting event calendar including delisted/frozen/no-trade outcomes before any backtest or collection.
