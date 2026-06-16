# Funding Postprocess Stress Assumptions Gate

Дата: 2026-06-15

## Цель

Закрыть acceptance-gap: включенный `stress-enabled` с нулевыми stress assumptions не является реальной stress-проверкой. Research acceptance теперь требует не только включенный stress gate, но и хотя бы одну ненулевую неблагоприятную assumption.

## Реализовано

- Добавлена проверка stress assumptions:
  - `adverse_basis_bps > 0`
  - или `spread_widen_bps > 0`
  - или `funding_flip_bps > 0`
- Если stress включен, но все assumptions равны нулю, добавляется reason:
  - `stress_assumptions_required`
- Добавлено поле:
  - `stress_assumptions_passed`
- `stress_accepted=true` теперь возможно только если:
  - stress включен
  - stress assumptions ненулевые
  - stress-adjusted acceptance не вернул stress rejection reasons

## Измененные участки

- `trading_mvp/src/basis.py`
  - `run_funding_postprocess_file`
- `trading_mvp/tests/test_basis.py`
  - `test_funding_postprocess_can_accept_oos_and_stress_for_final_manifest`
  - `test_funding_postprocess_rejects_zero_stress_assumptions_for_research_acceptance`

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 37 tests in 0.392s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 109 tests in 0.325s
OK
```

PowerShell smoke:

```json
{
  "zeroResearchAccepted": false,
  "zeroReasons": "stress_assumptions_required",
  "zeroStressAssumptionsPassed": false,
  "nonZeroResearchAccepted": true,
  "nonZeroReasons": "",
  "nonZeroStressAssumptionsPassed": true,
  "nonZeroStressAccepted": true
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 19,
  "cycles": 288,
  "remaining_cycles": 269,
  "progress_pct": 6.597222222222222,
  "manifest_rows": 432,
  "line_count": 432,
  "line_count_matches_manifest": true,
  "errors": 110,
  "last_write_age_sec": 24.82578992843628,
  "stale_after_sec": 900.0
}
```

Postprocess рабочего 24h collect не запускался, потому что manifest еще не финальный.

## Следующий Gate

После `final=true` запускать `funding-postprocess` с OOS и stress, где stress assumptions не нулевые. Минимальный приемлемый формат:

- `--oos-output <path>`
- `--stress-enabled`
- `--stress-adverse-basis-bps > 0` или `--stress-spread-widen-bps > 0` или `--stress-funding-flip-bps > 0`

