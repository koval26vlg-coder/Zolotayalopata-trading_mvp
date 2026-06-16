# Funding Matched Universe Ordering - 2026-06-15 22:26 local

## Objective
Continue research-only trading_mvp toward a viable non-Binance exchange strategy. No live orders, no API keys, no investment advice.

## Collector Status
- Status artifact: exports/trading-mvp/funding/funding_status_strict_24h_spotliq_20260615_latest.json
- Status: running_or_waiting
- Final: False
- Ready for postprocess: False
- Readiness blockers: status_not_final, data_quality:min_rows, data_quality:min_completed_cycles, data_quality:min_unique_cycles
- Completed cycles: 20 / 288
- Progress: 6.94%
- Rows: 480
- Errors: 120
- ETA: 25.75 hours

## Implementation
Improved matched universe CSV ordering:
- coverage rows now include universe_rank from the source no-Binance universe order;
- matched CSV is sorted by exchange_count desc, then universe_rank asc, then symbol;
- symbol remains the first CSV column, so load_universe_symbols and funding-collect --universe remain compatible;
- this prevents the next collector from starting with alphabetically early but lower-priority symbols.

## Verification
- python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py: OK
- Focused tests: 2 tests OK
- Full tests: 150 tests OK
- Compatibility check: load_universe_symbols read 99 symbols from the ordered CSV.

## Artifacts
- Ordered coverage JSON: exports/trading-mvp/funding/funding_coverage_mexc_gate_200_ordered_20260615.json
- Ordered matched universe CSV: exports/trading-mvp/funding/funding_matched_universe_mexc_gate_200_ordered_20260615.csv
- Matched symbols: 99
- Exchange-symbol slots: 171
- Coverage errors: 0
- First ordered symbols: HYPE, CC, OKB, M, MNT, CRO, PI, H, VVV, KAS

## Decision
Do not run funding-finalize while collector final=false. For the next clean long collect, use the ordered matched universe CSV so MaxPairsPerExchange selects higher-coverage, source-priority symbols first.
