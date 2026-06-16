# Funding 24h Partial Status - 2026-06-16 03:20 local

## Objective
Continue the research-only `trading_mvp` goal toward a viable non-Binance exchange strategy. No live orders, no API keys, no investment advice.

## Collector Status
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Status: `running_or_waiting`
- Final: `false`
- Ready for postprocess: `false`
- Completed cycles: `73 / 288`
- Progress: `25.35%`
- Rows: `1752`
- Errors: `438`
- Error rate: `0.20`
- Markets: `24`
- Span: `6.88h`
- Last write age at check: `23s`
- Stale threshold: `900s`

## Readiness Decision
`funding-finalize` was intentionally not run.

Readiness blockers:
- `status_not_final`
- `data_quality:min_completed_cycles`
- `data_quality:min_unique_cycles`

The line-count gate is already passing, but strict research requires final completion and enough unique cycles before final postprocess/backtest.

## Partial Artifacts
- Gate report: `exports/trading-mvp/funding/funding_gate_report_quality_partial_20260616.json`
- Quality universe: `exports/trading-mvp/funding/funding_quality_universe_partial_20260616.csv`
- Progress report: `exports/trading-mvp/funding/funding_progress_report_partial_20260616.json`

## Partial Metrics
- Gate report input rows: `1752`
- Markets analyzed: `24`
- Rank eligible: `0`
- Funding gap pass: `0`
- Source eligible: `15`
- Persistence eligible: `24`
- Best risk-adjusted funding gap: `-41.4877 bps/interval`
- Latest cycle: `73`
- Latest best: `gateio:HYPE`
- Latest best gap: `-39.0596 bps/interval`
- Best gap delta from first cycle: `+0.4005 bps`
- Latest average spot top notional: `95.84 quote`
- Average spot top notional delta: `-63.94 quote`

## Current Interpretation
The partial dataset still does not support funding/basis carry as executable economics. Funding persistence is visible on some markets, but after fees, basis risk, spread risk, and shallow spot top-of-book liquidity, every market fails strict ranking.

Main blockers:
- expected edge below minimum;
- risk-adjusted edge below minimum;
- break-even horizon too long;
- spot top liquidity too low for most markets;
- basis floor failure on most markets.

## Next Gate
Wait for the collector to reach `final=true` and strict readiness to pass before running `funding-finalize`.

If the final 24h dataset still has `rank_eligible=0`, the next engineering step is not live trading. It is to either:
- narrow universe to stronger spot top-of-book liquidity and rerun collection; or
- shift research weight back to event-driven perp/market-quality signals where the cost model is less dominated by spot execution.
