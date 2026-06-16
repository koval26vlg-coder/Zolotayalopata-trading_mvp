# Funding Viability Gap Diagnostics - 2026-06-15

## Goal Context
Research-only trading_mvp continues toward a metric-gated exchange strategy on non-Binance spot universe. No live orders, no API keys, no investment advice.

## Collector Status
- Dataset: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Launcher PID: 14080
- Child Python observed: 8060 / 25592 started at 2026-06-15 20:27 local
- Manifest final: false
- Completed cycles: 16
- Rows/lines: 384 / 384
- Errors: 96
- Last write: 2026-06-15T21:59:15 local
- Decision: do not run funding-finalize while manifest is not final.

## Implementation
Added viability gap diagnostics to `funding_gate_report`:
- `required_total_carry_bps_for_risk_edge`
- `required_funding_bps_per_interval_for_risk_edge`
- `funding_gap_bps_per_interval_for_risk_edge`
- `required_hold_intervals_for_risk_edge`
- `required_hold_hours_for_risk_edge`
- `target_hold_hours`
- `funding_gap_pass`
- summary `best_funding_gap_bps_per_interval_for_risk_edge`
- report section `top_by_funding_gap`

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK
- Focused tests: 2 tests OK
- Full tests: 147 tests OK

## Smoke Artifact
- Output: `exports/trading-mvp/funding/funding_gate_report_viability_strict_partial_20260615.json`
- Input rows: 384
- Markets analyzed: 24
- Rank eligible: 0
- Funding gap pass: 0
- Best funding gap: -41.2566 bps/interval
- Spot liquidity pass: 2 / 24
- Basis floor pass: 6 / 24

## Top Funding Gap Candidates
1. MEXC HYPE: gap -41.2566 bps/interval; required funding 41.7566 bps/interval; required hold 334.05h vs target 4h.
2. Gate HYPE: gap -42.5382 bps/interval; required funding 42.7182 bps/interval; required hold 949.29h vs target 4h.
3. Gate PI: gap -43.8948 bps/interval; required funding 44.3948 bps/interval; required hold 355.16h vs target 4h.
4. MEXC MNT: gap -44.8818 bps/interval; required funding 44.7418 bps/interval; latest funding was not positive enough for required hold.
5. MEXC XMR: gap -45.1907 bps/interval; required funding 49.8007 bps/interval; required hold 86.42h vs target 8h.

## Interpretation
Partial 24h data still rejects the current strict carry setup on economics, not just implementation details. The largest blockers remain expected edge, risk-adjusted edge, break-even horizon, and spot top-of-book liquidity. The next valid step after final dataset is strict finalize; if the same gap persists, the project should not move to live trading and should instead expand exchange/universe coverage or test a different carry structure.
