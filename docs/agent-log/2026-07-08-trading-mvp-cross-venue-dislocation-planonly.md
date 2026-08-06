# trading_mvp cross-venue dislocation PlanOnly

Status: implemented research-only detector/backtester for MEXC/Gate spot BBO dislocations.

Files changed:
- trading_mvp/src/cross_venue_dislocation.py
- trading_mvp/src/cli.py
- trading_mvp/run_mvp.ps1
- trading_mvp/tests/test_cross_venue_dislocation.py

Smoke artifact:
- C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\cross_venue_dislocation_smoke_20260708.json

Smoke summary:
- rows_read: 200000
- bbo_rows: 106493
- matched_bases: 12
- candidate_events: 101
- eligible_events: 0
- max_gross_edge_bps: 5.32197977647586
- max_net_edge_bps: -63.6780202235241
- decision: REJECTED_NO_NET_EDGE_AFTER_BASE_FEES

Verification:
- python -m unittest trading_mvp.tests.test_cross_venue_dislocation: OK
- python -m py_compile trading_mvp/src/cross_venue_dislocation.py trading_mvp/src/cli.py: OK
- run_mvp.ps1 cross-venue-dislocation smoke with CrossVenueMaxRows=200000: OK

Next allowed step:
- pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1" -Action cross-venue-dislocation -InputPath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_market_filtered_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.jsonl" -OutputPath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json" -CrossVenueProgressEveryRows 1000000 -CrossVenueMaxEvents 1000

Constraints:
- research-only; no live orders, API keys, leverage, margin, grid, or paper-forward.
- full scan must be visible because it can process ~51M rows.
