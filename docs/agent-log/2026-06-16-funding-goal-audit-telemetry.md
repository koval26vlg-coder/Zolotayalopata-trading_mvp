# Funding Goal Audit Telemetry - 2026-06-16 04:49 local

## Objective
Continue the research-only `trading_mvp` goal toward a viable non-Binance exchange strategy. No live orders, no API keys, no investment advice.

## Collector Readiness
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Latest strict audit: `exports/trading-mvp/funding/funding_goal_audit_partial_20260616_044911.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Status: `running_or_waiting`
- Completed cycles: `88 / 288`
- Progress: `30.56%`
- Remaining cycles: `200`
- ETA estimate: `67805s`
- Rows: `2112`
- Errors: `528`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

## Code Change
Improved `funding_collect_status`, `funding_goal_audit`, and wait-history telemetry:
- added `expected_cycles` alias from manifest `cycles`;
- added `remaining_cycles`, `progress_pct`, `eta_sec`, `estimated_next_cycle_in_sec` to audit summary and wait entries;
- added `last_write_ts` and `last_write_age_sec` to audit summary.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/tests/test_basis.py`

## Partial Monitoring Artifacts
These are monitoring-only and not final acceptance artifacts:
- Progress: `exports/trading-mvp/funding/funding_progress_report_partial_20260616_0449.json`
- Gate: `exports/trading-mvp/funding/funding_gate_report_quality_partial_20260616_0449.json`
- Regime: `exports/trading-mvp/funding/funding_regime_report_partial_20260616_0449.json`
- Quality universe CSV: `exports/trading-mvp/funding/funding_quality_universe_partial_20260616_0449.csv`

## Partial Economics
- Progress summary: latest cycle `88`, latest rows `24`, latest markets `24`.
- Latest rank eligible: `0`.
- Latest funding gap pass: `0`.
- Latest best market: `gateio:HYPE`.
- Latest best funding gap for risk edge: `-39.0560 bps/interval`.
- Gate summary: markets analyzed `24`, rank eligible `0`, persistence eligible `24`.
- Regime summary: eligible markets `0`, source pass `17`, persistence pass `24`, regime pass `24`, liquidity pass `1`, economics pass `0`.
- Main blockers: `expected_edge_below_min`, `risk_adjusted_edge_below_min`, `break_even_horizon_too_long`, `spot_top_liquidity_low`, `basis_below_min`.

## Verification
- Targeted audit/wait tests: 2 tests OK.
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py` passed.
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests` passed: 169 tests OK.

## Next Step
Do not run final postprocess yet. Continue condition-based waiting until strict audit reports `ready_for_postprocess=true`. Then run `funding-final-review` with strict research settings and inspect postprocess/gate/regime/frontier/sensitivity/decision/OOS/walk-forward/stress artifacts.
