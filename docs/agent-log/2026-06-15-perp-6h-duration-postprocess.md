# 2026-06-15 Perp 6h Duration Postprocess

## Request
Continue `trading_mvp` after the clean duration-bound 6h public perp collect and execute the guarded postprocess without `AllowPartial`.

## Collection Status
- Output: `exports/trading-mvp/normalized/perp_normalized_6h_duration_20260614_181422.jsonl`.
- Manifest: `exports/trading-mvp/normalized/perp_normalized_6h_duration_20260614_181422.manifest.json`.
- Manifest final: `true`.
- Stop condition: `duration_sec`.
- Duration: `21600.000970602036` seconds.
- Completed cycles: `529`.
- Rows: `82414`.
- Errors: `0`.
- Stderr: empty.

## QA Report
- Report artifact: `exports/trading-mvp/backtests/perp_report_6h_duration_20260614_181422.json`.
- Rows: `82414`.
- Markets: `10`.
- Events: `bbo=5290`, `depth=5290`, `trade=71834`.
- Exchanges: `mexc=67957`, `gateio=14457`.
- Field coverage: `mark_price`, `index_price`, `funding_rate`, `next_funding_ts`, `funding_interval_sec`, `open_interest`, `volume_24h_quote` all `82414/82414`.
- Warnings: none.
- Malformed rows: `0`.

## Grid Search
- Grid artifact: `exports/trading-mvp/backtests/perp_grid_search_6h_duration_20260614_181422.json`.
- Events: `82414`.
- Combinations: `288`.
- Strict eligible combinations: `0`.

### Best-By-Signal
| Signal | Trades | Win rate | Net PnL quote | Funding PnL quote | Profit factor | Eligibility |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `liquidity_sweep_reversal` | 3 | 66.67% | 0.036863 | 0.000004 | 9.0751 | fails `min_trades` |
| `flow_continue` | 77 | 18.18% | -7.218351 | 0.001251 | 0.0273 | fails winrate/EV/PF/drawdown |
| `fade_exhaustion` | 92 | 23.91% | -11.324496 | 0.024902 | 0.0561 | fails winrate/EV/PF/drawdown |

## Decision
The clean final 6h perp replay rejects the current signal family for live use. `flow_continue` and `fade_exhaustion` are materially negative. `liquidity_sweep_reversal` has positive PnL and high PF, but only three trades, which is not enough to claim a scalable high-winrate edge.

## Ledger
- Added experiment record: `exp_20260614_214746_c3e3d0d5ee93`.
- Verdict: `rejected`.
- Scope: current `perp_replay` implementation and current three signal families on this final 6h dataset.

## Next
Do not loosen gates to force a positive result. The next execution step should be a stronger event-definition layer:
- sweep intensity and reclaim distance;
- adverse excursion after entry;
- market-specific filters that remove toxic symbols like `mexc:H_USDT`;
- separate funding/basis carry validation, not blended into the microstructure signal.

Research-only. No live orders, no API keys, no Binance testnet, no investment advice.
