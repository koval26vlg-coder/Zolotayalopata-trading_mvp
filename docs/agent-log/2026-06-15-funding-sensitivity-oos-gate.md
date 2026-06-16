# Funding sensitivity OOS gate

Date: 2026-06-15

Goal context: research-only trading strategy validation for non-Binance spot universe. No live orders, no API keys, no leverage, no margin execution.

## Why this step

The final funding postprocess already requires out-of-sample validation, but `funding-sensitivity` previously ranked fee/slippage/hold scenarios on the full sample only. That allowed parameter selection to be overfit before the final OOS gate. This step adds an optional OOS gate directly into the sensitivity grid.

## Code changes

- `trading_mvp/src/basis.py`
  - `run_funding_sensitivity(...)` now accepts optional `FundingOosConfig`.
  - Each scenario can run a compact OOS summary with in-sample and out-of-sample metrics/acceptance.
  - Scenario `accepted` now requires full-sample acceptance and OOS acceptance when OOS is enabled.
  - Sensitivity summary now includes `oos_enabled`, `oos_accepted_scenarios`, and `best_oos_net_pnl_quote`.
- `trading_mvp/src/cli.py`
  - Added `--sensitivity-oos`.
  - Added sensitivity OOS parameters: `--oos-train-fraction`, `--oos-min-train-rows`, `--oos-min-rows`, `--oos-min-train-span-hours`, `--oos-min-span-hours`.
  - Strict research preset now enables sensitivity OOS automatically.
- `trading_mvp/run_mvp.ps1`
  - Added `-FundingSensitivityOos`.
  - Passed existing `FundingOos*` parameters into `funding-sensitivity`.
- `trading_mvp/tests/test_basis.py`
  - Added regression coverage that rejects a sensitivity scenario when OOS fails even if the full-sample gate can pass.
  - Extended CLI parser and strict preset coverage for sensitivity OOS.

## Collector status

Command:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File 'C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1' -Action funding-status -FundingStrictResearch -InputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl' -ManifestPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json'
```

Result:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `8 / 288`
- `manifest_rows`: `192`
- `line_count`: `192`
- `line_count_matches_manifest`: `true`
- `errors`: `48`
- `error_rate`: `0.2`
- readiness blockers: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Decision: final funding postprocess/finalize still must wait.

## Strict sensitivity OOS smoke

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_sensitivity_oos_strict_smoke_20260615.json
```

Summary:

- `input_rows`: `192`
- `markets`: `24`
- `scenarios`: `1`
- `accepted_scenarios`: `0`
- `oos_enabled`: `true`
- `oos_accepted_scenarios`: `0`
- `best_net_pnl_quote`: `-0.20801299424085967`
- `best_oos_net_pnl_quote`: `-0.03330637905373677`
- `best_rank_eligible`: `0`

Top scenario rejection:

- `research_acceptance.accepted`: `false`
- reasons: `full_backtest_rejected`, `oos_rejected`
- OOS coverage reasons: `min_train_span_hours`, `min_oos_span_hours`
- trades: `5`
- win rate: `0.0`
- net PnL: `-0.20801299424085967`
- expectancy: `-0.04160259884817193`

## Verification

Targeted tests:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_funding_sensitivity_sorts_more_viable_execution_scenarios_first trading_mvp.tests.test_basis.BasisTests.test_funding_sensitivity_oos_gate_rejects_bad_out_of_sample trading_mvp.tests.test_basis.BasisTests.test_oos_backtest_requires_in_sample_and_out_of_sample_acceptance trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands
```

Result:

```text
Ran 4 tests in 0.029s
OK
```

Strict preset test:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests -p 'test_basis.py' -k strict
```

Result:

```text
Ran 1 test in 0.005s
OK
```

Full test suite:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 141 tests in 0.545s
OK
```
