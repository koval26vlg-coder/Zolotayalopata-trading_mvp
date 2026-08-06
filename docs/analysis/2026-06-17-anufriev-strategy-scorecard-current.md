# Anufriev Strategy Scorecard Current

Дата: 2026-06-17
Статус: source-grounded scorecard по текущей доказательной базе. Не инвестсовет и не live-рекомендация.

## Source Quality

- Ledger-backed rows use `exports/trading-mvp/experiments/experiment_ledger.jsonl`.
- Channel cluster counts use `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_summary_20260606.json`.
- Funding economics use `exports/trading-mvp/funding/funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json`.
- Fields marked `not-specified` are absent from current source artifacts, not inferred.

## CSV Artifact

- `exports\trading-mvp\analysis\anufriev_strategy_scorecard_current_20260617.csv`
- Funding thresholds companion: `exports\trading-mvp\analysis\funding_economic_thresholds_20260617.csv`

## Scorecard

| Strategy | Verdict | Trades | Win rate | Net PnL | PF | Economic status | Next action |
|---|---|---:|---:|---:|---:|---|---|
| Spot maker order-book continuation | rejected | 45 | 0.422222 | -0.206488 | 0.721489 | negative EV after replay gates | keep as regression baseline, not production strategy |
| Spot maker liquidity sweep/reversal | inconclusive | 2 | 0.5 | 0.0199022 | 3.97438 | insufficient sample despite positive net in tiny slice | do not paper/live; require independent multi-day replay |
| Perp long/short microstructure current signal family | rejected | flow=77; fade=92; lsr=3 | flow=0.181818; fade=0.23913; lsr=0.666667 | flow=-7.21835; fade=-11.3245; lsr=0.0368628 | flow=0.0273085; fade=0.056099; lsr=9.07511 | current signal family rejected; lsr too few trades | collect dense independent multi-day perp/WS data before retesting |
| Sweep/reclaim event-quality layer | inconclusive | 1018 | 0.367177 | not-applicable | not-applicable | diagnostic only; not an execution strategy | use as feature layer only after better slice/OOS proof |
| Liquidity sweep reversal v2 execution | rejected | maker=10; taker=35 | maker=0.1; taker=0.0285714 | maker=-0.390137; taker=-1.93947 | maker=0.0877861; taker=0.00435934 | negative execution economics | reject current v2; do not optimize same thin sample |
| Large-move breakout momentum | rejected | train=8; oos=2 | train=0.75; oos=0.5 | train=0.279; oos=-0.002 | train=4.74; oos=0.97 | in-sample edge failed holdout | do not retest until longer independent WS sample exists |
| Funding/basis carry current cost model | failed | 0 | 0 | 0 | not-applicable | cost model failed: no positive expected net carry/risk-adjusted edge | visible 7d collect, then guarded final-review |
| P2P/off-ramp/legal crypto | excluded_from_trading_bot | not-applicable | not-applicable | not-applicable | not-applicable | not an alpha model; separate legal/off-ramp risk | keep outside MVP execution; use live-readiness checklist |
| AI trading / bot automation | tooling_only | not-applicable | not-applicable | not-applicable | not-applicable | productivity gain only; no trading edge accepted | use for research automation, classification, monitoring; never bypass replay gates |
| Risk/playbook/process engine | mandatory_gate | not-applicable | not-applicable | not-applicable | not-applicable | no direct alpha; prevents false deployment and uncontrolled loss | keep mandatory before paper/live |

## Key Conclusion

No strategy currently has accepted high-winrate/positive-EV status. Funding/basis is the next cleanest proof path, but only after a visible 7d collection and guarded final-review. Intraday/perp strategies require new independent dense data before more tuning.

Funding threshold companion:

- `docs/analysis/2026-06-17-funding-economic-thresholds.md`

## Provenance Notes

| Strategy | Provenance | Evidence |
|---|---|---|
| Spot maker order-book continuation | extracted | exports\trading-mvp\backtests\ws_grid_search_signal_type_maker_quality_6h_20260608.json / negative net pnl and PF below threshold |
| Spot maker liquidity sweep/reversal | extracted | exports/trading-mvp/backtests/ws_grid_search_three_signals_maker_quality_6h_20260609_optimized.json / Best sweep config had positive net PnL but only 2 trades and 50% win rate, failing min_trades and min_win_rate gates; not enough evidence for edge. |
| Perp long/short microstructure current signal family | extracted | exports/trading-mvp/backtests/perp_grid_search_6h_duration_20260614_181422.json / Clean final 6h duration-bound perp replay produced 0 eligible configs. Flow/fade are materially negative; liquidity_sweep_reversal is positive but only 3 trades, failing min_trades and not proving a scalable edge. |
| Sweep/reclaim event-quality layer | extracted | exports/trading-mvp/backtests/event_quality_6h_duration_20260614_181422.json / Raw sweep/reclaim labels produce 1018 candidates and 70.63% reclaim rate, but target-before-stop among reclaimed events is only 36.72% and false-sweep rate is 74.07%; must slice/filter before replay v2. |
| Liquidity sweep reversal v2 execution | extracted | exports/trading-mvp/backtests/perp_grid_lsr_v2_gate_hype_short_maker_cooldown10_6h_duration_20260614_181422.json / Event-slice candidate fails execution replay: maker winrate 10% and net PnL -0.3901; taker diagnostic winrate 2.86% and net PnL -1.9395. Not suitable for paper/live. |
| Large-move breakout momentum | extracted | exports/trading-mvp/backtests/breakout_oos_test30_20260604.json / In-sample (train 0.94h) лучший maker-конфиг bps3/look30/tp30/sl15/flow500: 8 сделок, 75% win, PF 4.74, net +0.279. На holdout (test 0.42h): 2 сделки, 50% win, PF 0.97, net -0.002, не eligible (min_trades, min_profit_factor). Edge не переживает OOS; trades << min_trades=20; датасет тонкий (1.35h). На taker мёртв. Cost-gate корректно блокирует flow_continue taker (0 сделок). |
| Funding/basis carry current cost model | extracted | exports/trading-mvp/funding/funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json / No market passed positive expected net carry/risk-adjusted edge after fees, slippage, spread and basis risk; backtest opened 0 trades. |
| P2P/off-ramp/legal crypto | selected | docs/analysis/live-readiness-checklist.md; docs/analysis/2026-06-17-anufriev-latest-two-source-packet.md |
| AI trading / bot automation | selected | docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md; docs/analysis/2026-06-17-anufriev-master-evidence-index.md |
| Risk/playbook/process engine | selected | docs/analysis/live-readiness-checklist.md; docs/agent-log/active-run-gate.json; docs/plans/2026-06-15-trading-mvp-research-goal.md |
