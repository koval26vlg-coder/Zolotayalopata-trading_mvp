# Funding Postprocess OOS-Required Gate

Дата: 2026-06-15

## Цель

Закрыть acceptance-gap: `funding-postprocess` не должен выставлять `research_acceptance.accepted=true`, если full backtest прошел, но OOS не был запущен. Это требование напрямую следует из цели проекта: принимать этапы только после out-of-sample проверки.

## Реализовано

- `research_acceptance.accepted` теперь требует:
  - full backtest acceptance
  - наличие OOS проверки
  - успешную OOS acceptance
- Если OOS не передан через `--oos-output`, postprocess все равно пишет rank/backtest artifacts, но research acceptance отклоняется.
- Добавлены причины:
  - `full_backtest_rejected`
  - `oos_required`
  - `oos_rejected`
- Добавлено поле:
  - `oos_required_passed`

## Измененные участки

- `trading_mvp/src/basis.py`
  - `run_funding_postprocess_file`
- `trading_mvp/tests/test_basis.py`
  - `test_funding_postprocess_runs_rank_and_backtest_for_final_manifest`

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 35 tests in 0.079s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 107 tests in 0.281s
OK
```

PowerShell smoke без OOS:

```json
{
  "ok": true,
  "status": "completed",
  "fullAccepted": true,
  "researchAccepted": false,
  "reasons": "oos_required",
  "oosRequiredPassed": false,
  "rankExists": true,
  "backtestExists": true,
  "rankRows": 1,
  "trades": 1
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 18,
  "cycles": 288,
  "remaining_cycles": 270,
  "progress_pct": 6.25,
  "manifest_rows": 408,
  "line_count": 408,
  "line_count_matches_manifest": true,
  "errors": 104,
  "last_write_age_sec": 19.570852994918823,
  "stale_after_sec": 900.0
}
```

Postprocess рабочего 24h collect не запускался, потому что manifest еще не финальный.

## Следующий Gate

После `final=true` у 24h collect запускать `funding-postprocess` только с `--oos-output`. Без OOS результат может быть технически `ok=true`, но не может быть `research_acceptance.accepted=true`.

