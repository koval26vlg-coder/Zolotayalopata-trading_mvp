# Funding Postprocess 24h Spotliq Summary

Дата: 2026-06-17

## Source
- Input: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl
- Manifest: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json
- Rows: 7659
- Completed cycles: 288/288
- Errors: 824

## Data Quality
- Accepted: True
- Markets: 30
- Unique cycles: 287
- Avg rows per cycle: 26,69
- Min rows per cycle: 15
- Error rate: 9,71 %
- Span hours: 30,51

## Rank And Backtest
- Rank eligible: 0
- Persistence eligible: 23
- Total trades: 0
- Traded markets: 0
- Net PnL quote: 0
- Funding PnL quote: 0
- Basis PnL quote: 0
- Fees quote: 0
- Slippage quote: 0

## Research Acceptance
- Accepted: False
- Reasons: full_backtest_rejected, oos_rejected, walk_forward_rejected
- OOS accepted: False
- Walk-forward accepted: False
- Stress accepted: True

## Interpretation
- Current 24h funding carry dataset is usable for diagnostics, but no paper trades pass strict positive edge gates.
- The blocker is economics, not execution code: expected net carry and risk-adjusted edge are negative after fees/slippage/spread/basis risk.
- This aligns with the external recommendation: do not continue breakout/live trading on thin short samples; funding carry needs longer multi-week data and better cost model/maker execution assumptions.

## Artifacts
- Rank: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_rank_24h_spotliq_relaxed15_20260615_202709.json
- Backtest: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_backtest_24h_spotliq_relaxed15_20260615_202709.json
- OOS: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_oos_24h_spotliq_relaxed15_20260615_202709.json
- Walk-forward: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_walk_forward_24h_spotliq_relaxed15_20260615_202709.json
- Postprocess: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json
