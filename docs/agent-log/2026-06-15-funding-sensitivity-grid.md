# Funding sensitivity grid status

Date: 2026-06-15

Goal context: research-only funding/basis carry engine for non-Binance spot universe. No live orders, no API keys, no margin execution.

## Changes in this step

- Added a funding sensitivity grid that reprices collected funding rows across fee, slippage, target-hold, and break-even assumptions.
- Aligned `funding-rank` filters with `funding-backtest` gates so rank eligibility respects spread, liquidity, regime, basis, expected edge, and break-even constraints.
- Added CLI and `run_mvp.ps1` support for `funding-sensitivity`.

## Current collector status

Command:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File 'C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1' -Action funding-status -FundingStrictResearch -InputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl' -ManifestPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json'
```

Result:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `7 / 288`
- `progress_pct`: `2.430555555555556`
- `manifest_rows`: `168`
- `line_count`: `168`
- `line_count_matches_manifest`: `true`
- `errors`: `42`
- `error_rate`: `0.2`
- `span_hours`: `0.639707207414839`
- readiness blockers: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Decision: do not run final funding postprocess or finalize until `final=true` and strict readiness passes.

## Sensitivity smoke artifact

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_sensitivity_smoke_aligned_20260615.json
```

Summary:

- `input_rows`: `168`
- `markets`: `24`
- `scenarios`: `48`
- `accepted_scenarios`: `0`
- `best_net_pnl_quote`: `0.0`
- `best_rank_eligible`: `1`

Best rank-eligible diagnostics:

- Best observed rank-eligible scenarios still failed acceptance.
- Example: spot fee `0`, perp fee `0`, slippage `1`, hold `3`, max break-even `24h`: `3` trades, net PnL `-0.17021316296585096`, win rate `0.0`, expectancy `-0.056737720988616985`, `accepted=false`.
- Acceptance blockers included low trade count, low win rate, negative expectancy, negative net PnL, low market/exchange diversity, and failed stress net PnL.

Interpretation: current partial 24h dataset is too small for strategy acceptance and still economically negative under the best rank-eligible smoke scenarios.

## Verification

Command:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 140 tests in 0.399s
OK
```
