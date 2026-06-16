# Funding Quality Universe Export - 2026-06-15 22:30 local

## Objective
Continue research-only trading_mvp toward a viable non-Binance exchange strategy. No live orders, no API keys, no investment advice.

## Collector Status
- Status artifact: exports/trading-mvp/funding/funding_status_strict_24h_spotliq_20260615_latest.json
- Status: running_or_waiting
- Final: False
- Ready for postprocess: False
- Readiness blockers: status_not_final, data_quality:min_rows, data_quality:min_completed_cycles, data_quality:min_unique_cycles
- Completed cycles: 22 / 288
- Progress: 7.64%
- Rows: 528
- Errors: 132
- ETA: 25.36 hours

## Implementation
Added optional quality universe export to funding-gate-report:
- build_funding_quality_universe_rows aggregates ranked/regime funding rows by base symbol;
- write_funding_quality_universe_csv writes a symbol-first CSV compatible with load_universe_symbols;
- funding-gate-report accepts --quality-universe-output;
- run_mvp.ps1 accepts -QualityUniverseOutputPath for funding-gate-report.

## Quality Sort
Sort priority:
1. rank_eligible
2. funding_gap_pass
3. exchange_count
4. max_regime_spot_top_min_notional_avg_quote
5. max_regime_perp_volume_avg_quote
6. best_funding_gap_bps_per_interval_for_risk_edge
7. lower min_regime_spread_avg_bps

## Verification
- python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py: OK
- Focused tests: 2 tests OK
- Full tests: 151 tests OK
- Compatibility check: load_universe_symbols read 14 symbols from the generated quality CSV.

## Artifacts
- Gate report JSON: exports/trading-mvp/funding/funding_gate_report_quality_partial_20260615.json
- Quality universe CSV: exports/trading-mvp/funding/funding_quality_universe_partial_20260615.csv
- Input rows: 504
- Markets analyzed: 24
- Quality symbols: 
- Rank eligible symbols: 
- Funding gap pass symbols: 
- Top quality symbols: M spotTop=606.74 gap=-45.96; MNT spotTop=588.02 gap=-46.04; HYPE spotTop=254.99 gap=-41.12; KAS spotTop=92.03 gap=-47.02; CRO spotTop=84.21 gap=-46.64

## Decision
Do not run funding-finalize while collector final=false. Current partial data still rejects carry economics, but the quality CSV prepares a better next clean collect by prioritizing real observed liquidity/execution quality rather than alphabetical or metadata-only ordering.
