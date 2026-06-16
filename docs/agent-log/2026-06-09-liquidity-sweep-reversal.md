# 2026-06-09 Liquidity Sweep Reversal

## Request
Continue the Anufriev/trading_mvp research goal after spot maker `flow_continue` and `fade_exhaustion` failed strict gates. Implement the next research-only signal family that better matches stop-cascade/liquidity-sweep channel claims without labeling market-maker intent.

## Changes
- Added `liquidity_sweep_reversal` as a third `signal_type` in `trading_mvp/src/ws_replay.py`.
- The signal detects observable sell/buy sweep candidates from trade prints versus recent BBO levels, then requires reclaim/rejection plus imbalance confirmation.
- Optimized sweep detection from nested BBO/trade scans to one rolling pass over the current window.
- Added unit coverage for spot long sweep/reclaim, spot short blocking without `AllowShort`, perp short sweep/rejection, and grid-search signal dimension.
- Updated `perp_postprocess` default signal grid to include `liquidity_sweep_reversal`.
- Updated README signal documentation and grid examples.
- Added experiment-ledger record `exp_20260609_194420_a76df30244ba`.

## Verification
- `C:\Windows\py.exe -3 -m unittest discover -s trading_mvp\tests` -> `Ran 67 tests`, `OK`.
- 30m smoke grid:
  - artifact: `exports/trading-mvp/backtests/ws_grid_search_three_signals_30m_smoke_20260609_optimized.json`
  - events: `167737`
  - combinations: `3`
  - signal families present: `flow_continue`, `fade_exhaustion`, `liquidity_sweep_reversal`
- 6h maker-quality grid:
  - artifact: `exports/trading-mvp/backtests/ws_grid_search_three_signals_maker_quality_6h_20260609_optimized.json`
  - events: `472583`
  - combinations: `288`
  - eligible combinations: `0`

## 6h Best-By-Signal Metrics
| Signal | Trades | Win rate | Net PnL quote | Profit factor | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `liquidity_sweep_reversal` | 2 | 50.00% | 0.019902 | 3.9744 | inconclusive; fails `min_trades`, `min_win_rate` |
| `flow_continue` | 45 | 42.22% | -0.206488 | 0.7215 | rejected by strict gates |
| `fade_exhaustion` | 77 | 45.45% | -0.437481 | 0.6483 | rejected by strict gates |

## Decision
`liquidity_sweep_reversal` is technically implemented and more faithful to the channel's stop-cascade narrative, but current 6h spot maker evidence is not sufficient. Positive PnL on two trades is not an edge. Keep this research-only and move it to perp long/short replay once the perp dataset is final.

## Perp Collect Status
The current REST perp collection manifest was last observed as `final=false`, `completed_cycles=218`, `rows=44009`, `errors=193`, with no matching process found. Treat it as an interrupted partial dataset unless a later manifest proves `final=true`.
