# 2026-06-15 Funding Postprocess OOS Integration

## Purpose

Make the final funding research gate harder to misuse. Guarded `funding-postprocess` can now produce the OOS artifact and combined research verdict in the same final postprocess run.

This avoids accepting a strategy from full-sample rank/backtest while forgetting the out-of-sample gate.

## Implemented

- `run_funding_postprocess_file()` accepts optional:
  - `oos_output_path`
  - `oos_cfg`
- When `oos_output_path` is provided, postprocess writes an OOS artifact using the same backtest, acceptance, and stress configs.
- Postprocess result now includes:
  - `oos_output`
  - `oos`
  - `research_acceptance`
- `research_acceptance.accepted=true` only if:
  - full backtest acceptance passes;
  - OOS acceptance passes, when OOS is requested.
- CLI `funding-postprocess` accepts:
  - `--oos-output`
  - `--oos-train-fraction`
  - `--oos-min-train-rows`
  - `--oos-min-rows`
- PowerShell `run_mvp.ps1 -Action funding-postprocess` accepts:
  - `-OosOutputPath`
  - `-FundingOosTrainFraction`
  - `-FundingOosMinTrainRows`
  - `-FundingOosMinRows`

## Verification

- Added regression: `test_funding_postprocess_can_run_oos_gate_for_final_manifest`.
- Extended CLI parser coverage for `funding-postprocess --oos-*`.
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 28 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 100 tests ... OK`

## Wrapper Smoke

Smoke command used a temporary final 4-row JSONL fixture through:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess -OosOutputPath <tmp-oos.json> ...
```

Result:

- `stdoutOk=true`
- `status=completed`
- `rankExists=true`
- `backtestExists=true`
- `oosExists=true`
- `researchAccepted=true` under deliberately loose smoke thresholds
- OOS split:
  - `total_rows=4`
  - `train_rows=2`
  - `oos_rows=2`
  - `train_fraction=0.5`

The smoke validates plumbing only; it is not a trading result.

## Live Funding Collect Status

Latest status:

- `status=running_or_waiting`
- `ready_for_postprocess=false`
- `final=false`
- `completed_cycles=13 / 288`
- `rows=288`
- `line_count=288`
- `line_count_matches_manifest=true`
- `errors=74`
- `last_write_age_sec≈114`
- `stderr=0 bytes`

## Final Gate Command Shape

When manifest becomes final, run `funding-postprocess` with `-OosOutputPath` so rank, backtest, OOS, stress, and combined research acceptance are produced together.
