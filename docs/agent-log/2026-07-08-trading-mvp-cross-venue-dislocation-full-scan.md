# trading_mvp cross-venue dislocation full scan

Agent: Codex visible wrapper
Time: 2026-07-08 18:27:14 +03:00

Input:
- C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_market_filtered_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.jsonl

Output:
- C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json

Manifest:
- C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\cross_venue_dislocation_full_20260708_181741.manifest.json

Summary:
- rows_read: 51278447
- bbo_rows: 36039132
- matched_bases: 12
- candidate_events: 2266
- eligible_events: 0
- max_gross_edge_bps: 66.3415023655367
- max_net_edge_bps: -2.65849763446329
- scan_complete: True
- decision: REJECTED_NO_NET_EDGE_AFTER_BASE_FEES

Next:
- Reject or park cross-venue spot dislocation under current base-fee assumptions, then select the next non-HFT structural branch PlanOnly. Do not grid-tune this rejected branch.

Constraints:
- research-only
- no live orders
- no API keys
- no leverage/margin
- no grid before validation gate
