# 2026-06-15 Event Slice Optimizer

## Request
Continue the `trading_mvp` goal after the first event-quality layer. Build the next research-only step toward a high-winrate, viable strategy: slice sweep/reclaim events before adding replay v2.

## Implementation
- Added `trading_mvp/src/event_slicer.py`.
- Added CLI action `event-slice-optimizer`.
- Added PowerShell action `-Action event-slice-optimizer`.
- Added tests in `trading_mvp/tests/test_event_slicer.py`.
- Documented the workflow in `trading_mvp/README.md`.

The optimizer consumes `event_quality_*.json`; it does not read live data and does not open paper/live trades.

## Verification
- Targeted: `C:\Windows\py.exe -3 -m unittest trading_mvp.tests.test_event_slicer`.
- Targeted: `C:\Windows\py.exe -3 -m unittest trading_mvp.tests.test_event_labeler`.
- Full suite: `C:\Windows\py.exe -3 -m unittest discover -s trading_mvp\tests`.
- Full suite result after final code changes: `75` tests, `OK`.

## 60% Slice Run
Artifact: `exports/trading-mvp/backtests/event_slice_optimizer_6h_duration_20260614_181422.json`.

Command gates:
- `SliceMinEvents=20`.
- `SliceMinReclaimed=10`.
- `SliceMinTargetBeforeStopRate=0.60`.
- `SliceMinTargetRateAll=0.20`.
- `SliceMaxFalseSweepRate=0.80`.
- `SliceMaxAvgAdverseBps=15`.
- `SliceMinFavorableToAdverse=0.8`.

Result:
- Events analyzed: `1018`.
- Raw generated slices: `16513`.
- Deduped slices: `3350`.
- Eligible slices: `3`.

Best eligible slice:
- Market: `gateio:HYPE_USDT`.
- Expected side: `SHORT`.
- Filters: `pre_spread_bps <= 1`, `trade_notional_quote >= 2500`.
- Total events: `21`.
- Reclaimed: `15`.
- Target before stop: `9`.
- Stop before target: `5`.
- Target-before-stop rate among reclaimed: `60.00%`.
- Target rate over all events: `42.86%`.
- False-sweep rate: `57.14%`.
- Average favorable excursion: `13.2177` bps.
- Average adverse excursion: `-6.0495` bps.
- Favorable/adverse ratio: `2.1849`.

## 70% Strict Run
Artifact: `exports/trading-mvp/backtests/event_slice_optimizer_6h_duration_20260614_181422_strict70.json`.

Changed gates:
- `SliceMinTargetBeforeStopRate=0.70`.
- `SliceMinTargetRateAll=0.25`.
- `SliceMaxFalseSweepRate=0.75`.

Result:
- Events analyzed: `1018`.
- Deduped slices: `3350`.
- Eligible slices: `0`.

The highest-looking strict slices had only `1-4` events and failed `min_events` / `min_reclaimed`, so they are not actionable.

## Decision
The current 6h dataset does not support a robust high-winrate sweep/reversal claim. It does expose one marginal replay-v2 candidate:

`gateio:HYPE_USDT`, `SHORT`, `pre_spread_bps <= 1`, `trade_notional_quote >= 2500`.

This candidate is not ready for live trading. It is only suitable for the next research step: implement a filtered `liquidity_sweep_reversal_v2` replay branch and test it out-of-sample, preferably on 24h+ data.

## Next
- Add `liquidity_sweep_reversal_v2` with event-derived filters:
  - exchange/symbol allowlist initially limited to `gateio:HYPE_USDT`;
  - short-only;
  - max pre-spread `1 bps`;
  - min triggering trade notional `2500 quote`;
  - keep maker/fill assumptions conservative.
- Run replay on the existing 6h dataset only as in-sample confirmation.
- Then collect 24h and run out-of-sample before considering any paper-forward execution.

Research-only. No live orders, no API keys, no Binance testnet, no investment advice.
