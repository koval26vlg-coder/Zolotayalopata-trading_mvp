# trading_mvp current strategy scorecard, 2026-06-28

Research-only status: no accepted strategy, no paper-forward, no live orders/API keys/leverage/margin.

CSV: `exports/trading-mvp/analysis/anufriev_strategy_scorecard_current_20260628.csv`

| Strategy family | Verdict | Trades/events | Win/quality rate | Net PnL | PF | Status | Next action |
|---|---:|---:|---:|---:|---:|---|---|
| Spot maker order-book continuation | rejected | 45 | 0.422222 | -0.206488 | 0.721489 | negative EV after replay gates | keep as regression baseline, not production strategy |
| Spot maker liquidity sweep/reversal | rejected | 11 | 0.545454545455 | 0.029408446156 | 1.56497671655 | fresh 20260628 WS grid positive tiny net but rejected by sample-size and win-rate gates | do not paper/live; collect independent dense WS data before retesting |
| Perp long/short microstructure current signal family | rejected | flow=77; fade=92; lsr=3 | flow=0.181818; fade=0.23913; lsr=0.666667 | flow=-7.21835; fade=-11.3245; lsr=0.0368628 | flow=0.0273085; fade=0.056099; lsr=9.07511 | current signal family rejected; lsr too few trades | collect dense independent multi-day perp/WS data before retesting |
| Sweep/reclaim event-quality layer | rejected | 43 | 0.382352941176 | not-applicable | not-applicable | diagnostic layer failed event-quality/OOS/walk-forward/stress gates; not execution-ready | use only as feature hypothesis; require independent dense sample and accepted validation gate |
| Liquidity sweep reversal v2 execution | rejected | maker=10; taker=35 | maker=0.1; taker=0.0285714 | maker=-0.390137; taker=-1.93947 | maker=0.0877861; taker=0.00435934 | negative execution economics | reject current v2; do not optimize same thin sample |
| Large-move breakout momentum | rejected | train=8; oos=2 | train=0.75; oos=0.5 | train=0.279; oos=-0.002 | train=4.74; oos=0.97 | in-sample edge failed holdout | do not retest until longer independent WS sample exists |
| Funding/basis carry current cost model | failed | 0 | 0 | 0 | not-applicable | 7d final-review refused by data-quality gate and relaxed diagnostics still had rank_eligible=0 | blocked_by_swarm_do_not_run_7d_funding_collect_or_final_review; reopen only with non-secret fee-tier evidence |
| P2P/off-ramp/legal crypto | excluded_from_trading_bot | not-applicable | not-applicable | not-applicable | not-applicable | not an alpha model; separate legal/off-ramp risk | keep outside MVP execution; use live-readiness checklist |
| AI trading / bot automation | tooling_only | not-applicable | not-applicable | not-applicable | not-applicable | productivity gain only; no trading edge accepted | use for research automation, classification, monitoring; never bypass replay gates |
| Risk/playbook/process engine | mandatory_gate | not-applicable | not-applicable | not-applicable | not-applicable | no direct alpha; prevents false deployment and uncontrolled loss | keep mandatory before paper/live |

## Fresh 2026-06-28 changes

- `Spot maker liquidity sweep/reversal` now uses `ws_grid_search_ws_confirmed_research_6h_20260628_103700.json`: 11 trades, 54.55% win rate, net +0.0294 quote, PF 1.565, rejected by `min_trades` and `min_win_rate`.
- `Sweep/reclaim event-quality layer` now uses `sweep_reversal_acceptance_ws_confirmed_research_6h_20260628_103700_gatefixed.json`: 43 sweeps, target-before-stop 38.24%, false-sweep 69.77%, validation rejected.
- `Funding/basis carry current cost model` now reflects the 7d guarded final-review refusal: 50,583 rows, 2016/2016 cycles, `min_rows_per_cycle=9`, relaxed `rank_eligible=0`.

## Decision

Do not paper/live. Current branch remains `spot_maker_liquidity_sweep_reversal_event_quality`, but only as a hypothesis requiring a new visible independent dense WS collect and full OOS/walk-forward/stress gates.
