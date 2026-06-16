# Funding Paper-Forward Summary Artifact

Дата: 2026-06-15

## Цель

Закрыть стык paper-forward acceptance: `funding-paper-forward` должен сохранять отдельный summary JSON с metrics, coverage и paper acceptance, а не полагаться только на stdout или последнюю строку JSONL audit trail.

## Реализовано

- `run_funding_paper_forward_file` теперь принимает:
  - `summary_output_path`
- Если summary path не задан, используется default:
  - `<paper_forward_output>.summary.json`
- Summary JSON пишется и для успешного forward, и для отказов:
  - `plan_not_ready`
  - `source_input_reuse_blocked`
- CLI:
  - `funding-paper-forward --summary-output`
- PowerShell:
  - `-PaperSummaryOutputPath`
- Result теперь включает:
  - `summary_output`

## Измененные участки

- `trading_mvp/src/basis.py`
  - `run_funding_paper_forward_file`
  - `default_funding_paper_forward_summary_path`
  - `_write_json`
- `trading_mvp/src/cli.py`
  - `cmd_funding_paper_forward`
  - `funding-paper-forward --summary-output`
- `trading_mvp/run_mvp.ps1`
  - `-PaperSummaryOutputPath`
- `trading_mvp/tests/test_basis.py`
  - summary artifact assertion
  - parser coverage

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 40 tests in 0.141s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 112 tests in 0.350s
OK
```

PowerShell smoke:

```json
{
  "ok": true,
  "status": "completed",
  "outputExists": true,
  "summaryExists": true,
  "summaryOutputMatches": true,
  "accepted": true,
  "savedAccepted": true,
  "savedRows": 2,
  "savedMarkets": 1,
  "liveOrders": false
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 22,
  "cycles": 288,
  "remaining_cycles": 266,
  "progress_pct": 7.638888888888889,
  "manifest_rows": 504,
  "line_count": 504,
  "line_count_matches_manifest": true,
  "errors": 128,
  "last_write_age_sec": 85.31228852272034,
  "stale_after_sec": 900.0
}
```

Рабочий postprocess/finalize не запускался, потому что manifest еще не финальный.

## Следующий Gate

После accepted `funding-finalize` и отдельного forward collect запускать:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-paper-forward `
  -FundingPlanPath <paper_plan.json> `
  -InputPath <forward_jsonl> `
  -OutputPath <paper_forward.jsonl> `
  -PaperSummaryOutputPath <paper_forward_summary.json>
```

Acceptance смотреть по `<paper_forward_summary.json>`.

