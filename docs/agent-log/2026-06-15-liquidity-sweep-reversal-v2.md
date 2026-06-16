# 2026-06-15 Liquidity Sweep Reversal V2

## Request
Continue the `trading_mvp` goal after event-slice optimizer. Convert the best in-sample slice into a replayable strategy branch and test whether it survives execution assumptions.

## Implementation
- Added strategy fields to `StrategyConfig`:
  - `sweep_v2_allowed_markets`;
  - `sweep_v2_side`;
  - `sweep_v2_min_trade_notional_quote`;
  - `sweep_v2_min_intensity_bps`;
  - `sweep_v2_max_pre_spread_bps`;
  - `sweep_v2_max_reclaim_sec`;
  - `sweep_v2_event_cooldown_sec`.
- Added signal type `liquidity_sweep_reversal_v2`.
- Extended sweep candidates with `intensity_bps` and `pre_spread_bps`.
- Added CLI and PowerShell wiring for v2 filters.
- Added unit tests for v2 short entry and market allowlist blocking.
- Documented v2 usage in `trading_mvp/README.md`.

## Verification
- `C:\Windows\py.exe -3 -m py_compile trading_mvp\src\cli.py trading_mvp\src\ws_replay.py trading_mvp\src\config.py`.
- `C:\Windows\py.exe -3 -m unittest trading_mvp.tests.test_ws_replay`.
- `C:\Windows\py.exe -3 -m unittest trading_mvp.tests.test_perp_replay`.
- `C:\Windows\py.exe -3 -m unittest discover -s trading_mvp\tests`.
- Final full suite: `77` tests, `OK`.

## In-Sample Candidate
From event-slice optimizer:
- Market: `gateio:HYPE_USDT`.
- Side: `SHORT`.
- Min sweep notional: `2500`.
- Max pre-spread: `1` bps.
- Event cooldown: `10` sec.
- Event-label score: `21` events, `15` reclaimed, `9` target-before-stop, `5` stop-before-target, `60%` target-before-stop among reclaimed.

## Maker Replay
Artifact: `exports/trading-mvp/backtests/perp_grid_lsr_v2_gate_hype_short_maker_cooldown10_6h_duration_20260614_181422.json`.

Config:
- Execution: `maker`.
- Queue model: `top_qty_fraction`.
- Queue ahead fraction: `1`.
- Latency: `250 ms`.
- TP/SL/Hold: `6 bps / 3 bps / 300 sec`.

Result:
- Eligible configs: `0`.
- Trades: `10`.
- Wins: `1`.
- Losses: `9`.
- Win rate: `10%`.
- Net PnL quote: `-0.390137`.
- Expectancy quote: `-0.039014`.
- Profit factor: `0.0878`.
- Funding PnL quote: `0.000160`.

## Taker Diagnostic
Artifact: `exports/trading-mvp/backtests/perp_grid_lsr_v2_gate_hype_short_taker_6h_duration_20260614_181422.json`.

Result:
- Eligible configs: `0`.
- Trades: `35`.
- Wins: `1`.
- Losses: `34`.
- Win rate: `2.86%`.
- Net PnL quote: `-1.939474`.
- Expectancy quote: `-0.055414`.
- Profit factor: `0.00436`.

## Decision
Reject `liquidity_sweep_reversal_v2` on this 6h dataset. The event-label slice looked marginally acceptable before execution, but replay with latency, order lifecycle, fees and exits destroys the edge. The issue is not only maker fill quality: taker diagnostic is also strongly negative.

## Next
Do not optimize this branch further on the same 6h sample. The next viable project step should be one of:
- collect 24h+ and rerun the event-quality/slice pipeline to check whether the 6h result was sample-specific;
- pivot back to funding/basis carry where edge is slower but more structurally measurable;
- build a market-making simulator around spread capture and inventory risk instead of reversal prediction.

Research-only. No live orders, no API keys, no Binance testnet, no investment advice.
