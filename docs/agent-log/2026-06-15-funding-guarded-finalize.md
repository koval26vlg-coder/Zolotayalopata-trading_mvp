# Funding Guarded Finalize

Дата: 2026-06-15

## Цель

Свести финальный research-only переход в одну защищенную команду: после завершения collect автоматически выполнить только корректный pipeline `postprocess -> OOS -> stress -> postprocess summary -> paper plan`, но не запускаться на незавершенном collect и не создавать paper plan без accepted research gates.

## Реализовано

- Добавлена core-функция:
  - `run_funding_research_finalize_file`
- Добавлена CLI-команда:
  - `funding-finalize`
- Добавлен PowerShell action:
  - `-Action funding-finalize`
- Guarded behavior:
  - если collect не готов: `status=not_ready_for_postprocess`, artifacts не создаются
  - если нет OOS output: `status=oos_output_required`
  - если stress не включен: `status=stress_required`
  - если stress assumptions нулевые: `status=stress_assumptions_required`
  - если postprocess accepted: создается `funding-paper-plan`
- PowerShell mapping:
  - `-OutputPath` -> postprocess summary
  - `-ReportOutputPath` -> rank
  - `-GridOutputPath` -> backtest
  - `-OosOutputPath` -> OOS
  - `-FundingPlanPath` -> paper plan
  - `-PaperOutputPath` -> future paper-forward JSONL

## Измененные участки

- `trading_mvp/src/basis.py`
  - `run_funding_research_finalize_file`
- `trading_mvp/src/cli.py`
  - `cmd_funding_finalize`
  - `funding-finalize` parser and dispatch
- `trading_mvp/run_mvp.ps1`
  - `funding-finalize` action
- `trading_mvp/tests/test_basis.py`
  - not-final finalize rejection
  - accepted finalize creates postprocess and paper plan
  - CLI parser coverage

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 40 tests in 0.157s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 112 tests in 0.330s
OK
```

PowerShell smoke:

```json
{
  "notReadyOk": false,
  "notReadyStatus": "not_ready_for_postprocess",
  "readyOk": true,
  "readyStatus": "completed",
  "researchAccepted": true,
  "paperPlanCreated": true,
  "postprocessExists": true,
  "rankExists": true,
  "backtestExists": true,
  "oosExists": true,
  "planExists": true,
  "planReady": true
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 21,
  "cycles": 288,
  "remaining_cycles": 267,
  "progress_pct": 7.291666666666667,
  "manifest_rows": 480,
  "line_count": 480,
  "line_count_matches_manifest": true,
  "errors": 122,
  "last_write_age_sec": 207.56531190872192,
  "stale_after_sec": 900.0
}
```

Postprocess рабочего 24h collect не запускался, потому что manifest еще не финальный.

## Следующий Gate

Когда collect станет `final=true`, можно запускать:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-finalize `
  -InputPath <final_jsonl> `
  -ManifestPath <final_manifest> `
  -OutputPath <postprocess_summary.json> `
  -ReportOutputPath <rank.json> `
  -GridOutputPath <backtest.json> `
  -OosOutputPath <oos.json> `
  -FundingPlanPath <paper_plan.json> `
  -PaperOutputPath <paper_forward.jsonl> `
  -FundingStress `
  -FundingStressAdverseBasisBps <nonzero> `
  -FundingStressSpreadWidenBps <nonzero> `
  -FundingStressFundingFlipBps <nonzero>
```

