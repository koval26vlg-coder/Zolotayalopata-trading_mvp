# Funding Sensitivity Stress Partial - 2026-06-16 03:25 local

## Objective
Continue the research-only `trading_mvp` goal for non-Binance markets. This step adds evidence for the volume/regime/stress gate while the 24h funding collector continues running.

No live orders, no API keys, no investment advice.

## Collector Gate
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Collector status at pre-check: `running_or_waiting`
- Final: `false`
- Ready for postprocess: `false`
- Completed cycles: `73 / 288`
- Rows at sensitivity run: `1752`
- Markets: `24`
- Strict finalize decision: not run

Readiness blockers:
- `status_not_final`
- `data_quality:min_completed_cycles`
- `data_quality:min_unique_cycles`

## Sensitivity/Stress Command
Ran `funding-sensitivity` with:
- `--strict-research`
- `--stress-enabled`
- `--sensitivity-oos`
- `--sensitivity-walk-forward`

Artifact:
- `exports/trading-mvp/backtests/funding_sensitivity_stress_partial_20260616.json`

## Stress Assumptions
- adverse basis: `5 bps`
- spread widen: `2 bps`
- funding flip: `2 bps`
- stress cost: `11 bps`
- min stress net PnL: `0`
- max stress drawdown: `5 quote`

## Summary
- Input rows: `1752`
- Markets: `24`
- Scenarios: `243`
- Accepted scenarios: `0`
- OOS enabled: `true`
- OOS accepted scenarios: `0`
- Walk-forward enabled: `true`
- Walk-forward accepted scenarios: `0`
- Best net PnL: `0.0`
- Best OOS net PnL: `0.0`
- Best walk-forward average test net PnL: `0.0`
- Best rank eligible: `0`

## Best Scenario Diagnostic
The best displayed scenario is the lowest-cost scenario:
- spot fee: `0 bps`
- perp fee: `0 bps`
- slippage: `0 bps`
- target hold intervals: `1`
- max break-even hours: `24`
- round-trip cost: `0 bps`

Even this scenario was rejected:
- acceptance reasons: `min_trades`, `min_win_rate`, `min_profit_factor`, `min_markets`, `min_exchanges`, `min_profitable_windows`
- research acceptance reasons: `full_backtest_rejected`, `oos_rejected`, `walk_forward_rejected`
- rank eligible: `0`
- persistence eligible: `20`

OOS/walk-forward diagnostics:
- OOS status: `completed`
- OOS accepted: `false`
- OOS coverage reasons: `min_train_span_hours`, `min_oos_span_hours`
- Walk-forward status: `completed`
- Walk-forward windows: `31`
- Walk-forward accepted windows: `0`
- Walk-forward accepted ratio: `0.0`

## Interpretation
The partial dataset does not only fail on profitability. It fails earlier: no market survives the strict ranking gate, so the backtester has zero valid trades across all sensitivity scenarios.

This makes the current funding/carry branch unsuitable for paper-forward until the final 24h dataset proves otherwise. The most likely blockers remain:
- spot top-of-book liquidity is too shallow;
- risk-adjusted edge is negative after basis/spread risk;
- strict rank eligibility remains zero despite funding persistence on some symbols.

## Next Gate
Do not run `funding-finalize` until `funding-status --strict-research` returns `ready_for_postprocess=true`.

If the final 24h run still has `accepted_scenarios=0` and `rank_eligible=0`, the next engineering step should be to reduce the carry universe to higher top-of-book spot liquidity or shift the project focus back to event-driven perp signals.

## Post-Run Collector Verification
After the sensitivity artifact was written, the collector advanced again:
- Final: `false`
- Ready for postprocess: `false`
- Completed cycles: `74 / 288`
- Rows: `1776`
- Errors: `444`
- Last write age at check: `22s`

The sensitivity artifact remains a valid partial-data stress check for the 1752-row snapshot used at run time. It is not a final acceptance artifact.
