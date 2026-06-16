# Funding walk-forward gate

Date: 2026-06-15

Goal context: research-only strategy validation for non-Binance spot universe. No live orders, no API keys, no leverage, no margin execution.

## Why this step

Single train/OOS split can still pass by chance. This step adds a rolling walk-forward validation gate so a funding/basis setup must survive multiple sequential train/test windows before it can be considered for paper-forward.

## Code changes

- `trading_mvp/src/basis.py`
  - Added `FundingWalkForwardConfig`.
  - Added `run_funding_walk_forward_backtest(...)`.
  - Added `run_funding_walk_forward_backtest_file(...)`.
  - Added `default_funding_walk_forward_path(...)`.
- `trading_mvp/src/cli.py`
  - Added `funding-walk-forward` command.
  - Added strict-research preset coverage for walk-forward gates.
- `trading_mvp/run_mvp.ps1`
  - Added `funding-walk-forward` action.
  - Added `FundingWalk*` parameters.
- `trading_mvp/tests/test_basis.py`
  - Added walk-forward acceptance/rejection tests.
  - Added parser and strict preset coverage.

## Collector status

Command:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File 'C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1' -Action funding-status -FundingStrictResearch -InputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl' -ManifestPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json'
```

Result:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `10 / 288`
- `manifest_rows`: `240`
- `line_count`: `240`
- `line_count_matches_manifest`: `true`
- `errors`: `60`
- `error_rate`: `0.2`
- readiness blockers: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Decision: final funding postprocess/finalize still must wait.

## Walk-forward smoke

Loose command smoke was used only to verify CLI execution and artifact writing.

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_walk_forward_smoke_20260615.json
```

Summary:

- `total_rows`: `240`
- `windows`: `8`
- `accepted_windows`: `8`
- `accepted_ratio`: `1.0`
- `avg_test_net_pnl_quote`: `-1.3688750695981633`
- `avg_test_win_rate`: `0.0`

Interpretation: loose acceptance can pass mechanically even when economics are negative; this is not a research acceptance.

## Strict walk-forward smoke

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_walk_forward_strict_smoke_20260615.json
```

Summary:

- `total_rows`: `240`
- `windows`: `8`
- `accepted_windows`: `0`
- `failed_windows`: `8`
- `accepted_ratio`: `0.0`
- `min_windows`: `3`
- `min_accepted_windows`: `3`
- `min_accepted_ratio`: `1.0`
- top-level reasons: `min_accepted_windows`, `min_accepted_ratio`
- window-level reasons included: `min_trades`, `min_win_rate`, `min_profit_factor`, `min_markets`, `min_exchanges`, `min_profitable_windows`, `min_train_span_hours`, `min_oos_span_hours`

Interpretation: current partial dataset is not a candidate for paper-forward. The strict gate is rejecting for both signal/trade quality and insufficient temporal coverage.

## Verification

Compile:

```powershell
& 'C:\Program Files\Python313\python.exe' -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py
```

Result: exit code `0`.

Targeted tests:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_walk_forward_accepts_multiple_passing_oos_windows trading_mvp.tests.test_basis.BasisTests.test_walk_forward_rejects_when_too_few_windows_pass trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands
```

Result:

```text
Ran 3 tests in 0.026s
OK
```

Strict preset test:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests -p 'test_basis.py' -k strict
```

Result:

```text
Ran 1 test in 0.006s
OK
```

Full test suite:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 143 tests in 0.537s
OK
```
