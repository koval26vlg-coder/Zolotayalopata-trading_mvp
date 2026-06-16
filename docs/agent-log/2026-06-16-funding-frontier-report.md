# Funding Frontier Report - 2026-06-16 03:30 local

## Objective
Continue the research-only `trading_mvp` goal for non-Binance markets. This step adds a frontier diagnostic for the funding/basis carry branch while the 24h collector continues running.

No live orders, no API keys, no investment advice.

## Collector Status
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Status: `running_or_waiting`
- Final: `false`
- Ready for postprocess: `false`
- Completed cycles: `75 / 288`
- Rows: `1800`
- Errors: `450`
- Progress: `26.04%`
- Last write age at final check: `120s`

Readiness blockers:
- `status_not_final`
- `data_quality:min_completed_cycles`
- `data_quality:min_unique_cycles`

## Implementation
Added `funding-frontier-report`:
- compares strict rank eligibility with `liquidity_relaxed`, `economics_relaxed`, and `fully_relaxed` variants;
- computes per-market funding gap, required funding, required hold hours, spot top-of-book liquidity gap, liquidity ratio, and primary blocker;
- writes a JSON artifact and exposes the command through CLI and `run_mvp.ps1`;
- leaves existing ranking/backtest/trading behavior unchanged.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_basis.py`

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK
- Targeted tests: 2 tests OK
- Full tests: 153 tests OK

## Artifact
- Frontier report: `exports/trading-mvp/funding/funding_frontier_report_partial_20260616.json`
- Artifact rows: `1800`
- Markets analyzed: `24`
- Strict rank eligible: `0`
- Liquidity-relaxed rank eligible: `0`
- Economics-relaxed rank eligible: `0`
- Fully-relaxed rank eligible: `6`
- Funding gap pass: `0`
- Spot liquidity pass: `1`
- Best funding gap: `-41.4721 bps/interval`
- Median spot liquidity ratio: `0.1003`
- Best spot liquidity ratio: `1.0720`
- Minimum required hold hours: `25.2050`

Primary blocker counts:
- `economics_and_liquidity`: `16`
- `source`: `8`

Top frontier row:
- `gateio:HYPE`
- primary blocker: `economics_and_liquidity`
- funding gap: `-41.4721 bps/interval`
- required funding: `41.9721 bps/interval`
- required hold: `335.7767h`
- regime spot top notional: `38.6963 quote`
- required spot top notional: `500 quote`
- liquidity ratio: `0.0774`

## Interpretation
The blocker is not only low spot liquidity and not only fees/risk economics. Relaxing liquidity alone still gives zero eligible markets, and relaxing economics alone also gives zero eligible markets. Only relaxing both gives six theoretical candidates.

This means the current funding/carry branch should not be promoted to paper-forward unless the final 24h dataset materially improves both:
- risk-adjusted funding edge after fees, basis risk, and spread risk;
- spot top-of-book liquidity.

## Next Gate
Continue waiting for `funding-status --strict-research` to return `ready_for_postprocess=true`. Then run `funding-finalize`.

If final frontier metrics remain similar, the next engineering decision should be to stop expanding funding/carry on this universe and shift priority to event-driven perp signals or a much stricter liquidity-filtered universe.
