# Funding Partial Refresh - 2026-06-16 03:44 local

## Objective
Continue the research-only `trading_mvp` goal for non-Binance markets by keeping funding/basis carry diagnostics current while the 24h collector runs.

No live orders, no API keys, no investment advice.

## Collector Status
Post-refresh status:
- Status: `running_or_waiting`
- Final: `false`
- Ready for postprocess: `false`
- Completed cycles: `77 / 288`
- Rows: `1848`
- Errors: `462`
- Progress: `26.74%`
- Last write age at check: `64s`

Readiness blockers:
- `status_not_final`
- `data_quality:min_completed_cycles`
- `data_quality:min_unique_cycles`

## Refreshed Artifacts
The following partial artifacts were refreshed from the 1824-row snapshot:
- `exports/trading-mvp/funding/funding_gate_report_quality_partial_20260616.json`
- `exports/trading-mvp/funding/funding_quality_universe_partial_20260616.csv`
- `exports/trading-mvp/funding/funding_frontier_report_partial_20260616.json`
- `exports/trading-mvp/funding/funding_progress_report_partial_20260616.json`
- `exports/trading-mvp/backtests/funding_sensitivity_stress_partial_20260616.json`
- `exports/trading-mvp/funding/funding_decision_report_partial_20260616.json`

## Partial Metrics
Gate report:
- Input rows: `1824`
- Markets: `24`
- Rank eligible: `0`
- Funding gap pass: `0`
- Best funding gap: `-41.5287 bps/interval`
- Spot liquidity pass: `1`

Frontier report:
- Strict rank eligible: `0`
- Liquidity-relaxed rank eligible: `0`
- Economics-relaxed rank eligible: `0`
- Fully-relaxed rank eligible: `8`
- Primary blockers: `economics_and_liquidity=17`, `source=7`
- Median spot liquidity ratio: `0.0994`
- Minimum required hold hours: `26.7446`

Progress report:
- Latest cycle in artifact: `76`
- Latest rank eligible: `0`
- Latest funding gap pass: `0`
- Latest best: `gateio:HYPE`
- Latest best gap: `-38.7997 bps/interval`
- Warnings: `latest_cycle_no_rank_eligible`, `latest_cycle_no_funding_gap_pass`, `latest_best_gap_negative`

Sensitivity/stress:
- Scenarios: `243`
- Accepted scenarios: `0`
- OOS accepted scenarios: `0`
- Walk-forward accepted scenarios: `0`
- Best net PnL: `0.0`
- Best OOS net PnL: `0.0`
- Best walk-forward average test net PnL: `0.0`

Decision report:
- Accepted: `false`
- Verdict: `wait_for_final_dataset`
- Next action: `wait_and_recheck`
- Ready for postprocess: `false`

## Interpretation
The partial funding/carry branch remains non-acceptable. The most important signal is stable across refreshed artifacts: no strict candidate survives ranking, no funding-gap pass exists, and stress/OOS/walk-forward acceptance is zero.

This is still not a final rejection because the collector is not final and strict readiness has not passed. The correct next action remains condition-based waiting for `ready_for_postprocess=true`, not live trading or paper-forward.

## Next Gate
Run final processing only when:
- `funding-status --strict-research` returns `ready_for_postprocess=true`;
- manifest has `final=true`;
- data quality passes minimum cycles/unique cycles.

Then run final:
- `funding-finalize`
- `funding-frontier-report`
- `funding-decision-report`
