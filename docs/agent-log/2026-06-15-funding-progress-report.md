# Funding Progress Report - 2026-06-15 22:36 local

## Objective
Continue research-only trading_mvp toward a viable non-Binance exchange strategy. No live orders, no API keys, no investment advice.

## Collector Status
- Status artifact: exports/trading-mvp/funding/funding_status_strict_24h_spotliq_20260615_latest.json
- Status: running_or_waiting
- Final: False
- Ready for postprocess: False
- Readiness blockers: status_not_final, data_quality:min_rows, data_quality:min_completed_cycles, data_quality:min_unique_cycles
- Completed cycles: 23 / 288
- Progress: 7.99%
- Rows: 552
- Errors: 138
- ETA: 25 hours

## Implementation
Added funding-progress-report:
- cycle-level summaries using existing rank_funding_rows and viability gap logic;
- manifest cycle error counts attached to each cycle when manifest is available;
- trend fields: latest best gap, gap delta from first cycle, spot top liquidity delta, latest warnings;
- CLI command and run_mvp.ps1 action with strict-research support.

## Verification
- python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py: OK
- Focused tests: 2 tests OK
- Full tests: 152 tests OK

## Artifact
- Progress report: exports/trading-mvp/funding/funding_progress_report_partial_20260615.json
- Input rows: 528
- Cycles analyzed: 22
- Latest cycle: 22
- Latest rank eligible: 0
- Latest funding gap pass: 0
- Latest best: mexc:XMR
- Latest best gap: -37.5749 bps/interval
- Best gap delta from first cycle: 1.8852 bps
- Avg spot top notional delta: -74.82 quote
- Warnings: latest_cycle_no_rank_eligible, latest_cycle_no_funding_gap_pass, latest_best_gap_negative

## Decision
Do not run funding-finalize while collector final=false. Progress report shows slight best-gap improvement, but latest best gap remains negative and there are no rank-eligible or funding-gap-pass markets, so this remains research-only monitoring.
