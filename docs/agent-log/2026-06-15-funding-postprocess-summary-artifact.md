# Funding Postprocess Summary Artifact

Дата: 2026-06-15

## Цель

Закрыть практический разрыв между `funding-postprocess` и `funding-paper-plan`: postprocess payload с gate evidence должен сохраняться в файл, а не только печататься в stdout. Иначе `funding-paper-plan` не имеет надежного artifact input.

## Реализовано

- Добавлен default path helper:
  - `default_funding_postprocess_summary_path(input_path, funding_dir)`
- `funding-postprocess` теперь сохраняет summary artifact:
  - по умолчанию `funding_postprocess_<input_stem>.json`
  - или по явному `--postprocess-output`
- PowerShell wrapper теперь использует:
  - `-OutputPath` как путь к postprocess summary artifact
- В result добавляется:
  - `postprocess_output`
- Сохраненный artifact содержит:
  - rank/backtest/OOS output paths
  - acceptance
  - research_acceptance
  - all configs
  - manifest summary

## Измененные участки

- `trading_mvp/src/basis.py`
  - `default_funding_postprocess_summary_path`
- `trading_mvp/src/cli.py`
  - `cmd_funding_postprocess`
  - `funding-postprocess --postprocess-output`
- `trading_mvp/run_mvp.ps1`
  - `funding-postprocess` passes `-OutputPath` to `--postprocess-output`
- `trading_mvp/tests/test_basis.py`
  - parser coverage for `--postprocess-output`

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 38 tests in 0.124s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 110 tests in 0.283s
OK
```

PowerShell smoke:

```json
{
  "postprocessOutputExists": true,
  "postprocessOutputMatches": true,
  "savedResearchAccepted": true,
  "savedStressEvidence": true,
  "planOk": true,
  "planStatus": "ready_for_paper_forward",
  "planReady": true,
  "rankExists": true,
  "backtestExists": true,
  "oosExists": true
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 20,
  "cycles": 288,
  "remaining_cycles": 268,
  "progress_pct": 6.944444444444445,
  "manifest_rows": 456,
  "line_count": 456,
  "line_count_matches_manifest": true,
  "errors": 116,
  "last_write_age_sec": 161.84443426132202,
  "stale_after_sec": 900.0
}
```

Postprocess рабочего 24h collect не запускался, потому что manifest еще не финальный.

## Следующий Gate

После `final=true` запускать:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-postprocess `
  -InputPath <final_jsonl> `
  -ManifestPath <final_manifest> `
  -OutputPath <postprocess_summary.json> `
  -ReportOutputPath <rank.json> `
  -GridOutputPath <backtest.json> `
  -OosOutputPath <oos.json> `
  -FundingStress `
  -FundingStressAdverseBasisBps <nonzero> `
  -FundingStressSpreadWidenBps <nonzero> `
  -FundingStressFundingFlipBps <nonzero>
```

Затем `funding-paper-plan` должен брать именно `<postprocess_summary.json>`.

