# Funding Postprocess Stress-Required Gate

Дата: 2026-06-15

## Цель

Закрыть acceptance-gap: `funding-postprocess` не должен выставлять `research_acceptance.accepted=true`, если full backtest и OOS прошли, но stress gate не был включен. Это нужно, чтобы этап принимался только после проверки затрат, неблагоприятного basis/spread/funding режима и drawdown.

## Реализовано

- `research_acceptance.accepted` теперь требует:
  - full backtest acceptance
  - OOS acceptance
  - включенный stress gate
  - отсутствие stress rejection reasons
- Если stress gate не включен, добавляется reason:
  - `stress_required`
- Если stress gate включен, но stress-adjusted acceptance не прошел, добавляется reason:
  - `stress_rejected`
- Добавлены поля:
  - `stress_required_passed`
  - `stress_accepted`

## Измененные участки

- `trading_mvp/src/basis.py`
  - `run_funding_postprocess_file`
- `trading_mvp/tests/test_basis.py`
  - `test_funding_postprocess_requires_stress_gate_for_research_acceptance`
  - `test_funding_postprocess_can_accept_oos_and_stress_for_final_manifest`

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 36 tests in 0.085s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 108 tests in 0.224s
OK
```

PowerShell smoke:

```json
{
  "noStressResearchAccepted": false,
  "noStressReasons": "stress_required",
  "noStressOosAccepted": true,
  "stressResearchAccepted": true,
  "stressReasons": "",
  "stressRequiredPassed": true,
  "stressAccepted": true,
  "oosExists": true
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
  "last_write_age_sec": 196.80321645736694,
  "stale_after_sec": 900.0
}
```

Postprocess рабочего 24h collect не запускался, потому что manifest еще не финальный.

## Следующий Gate

После `final=true` у 24h collect запускать `funding-postprocess` только с:

- `--oos-output`
- `--stress-enabled`
- непустыми stress assumptions для adverse basis, spread widening и funding flip

Без stress gate результат может быть `ok=true`, но не может быть `research_acceptance.accepted=true`.

