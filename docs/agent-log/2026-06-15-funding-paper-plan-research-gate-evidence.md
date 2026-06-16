# Funding Paper Plan Research Gate Evidence

Дата: 2026-06-15

## Цель

Закрыть safety-gap между `funding-postprocess` и `funding-paper-plan`: нельзя создавать `ready_for_paper_forward` plan только по одному полю `research_acceptance.accepted=true`. Plan теперь требует явные доказательства, что full backtest, OOS и stress gates действительно прошли.

## Реализовано

- `funding-paper-plan` теперь проверяет `research_acceptance` на обязательные поля:
  - `full_backtest_accepted=true`
  - `oos_required_passed=true`
  - `oos_accepted=true`
  - `stress_required_passed=true`
  - `stress_assumptions_passed=true`
  - `stress_accepted=true`
  - `reasons=[]`
- Если `accepted=true`, но этих доказательств нет, plan получает:
  - `ok=false`
  - `ready_for_paper_forward=false`
  - `status=research_gate_evidence_missing`
  - `research_gate_reasons=[...]`
- Это защищает paper-forward от вручную или старым кодом созданных неполных postprocess artifacts.

## Измененные участки

- `trading_mvp/src/basis.py`
  - `create_funding_paper_forward_plan_file`
  - `_funding_research_gate_reasons`
- `trading_mvp/tests/test_basis.py`
  - `test_paper_forward_plan_requires_accepted_research`
  - `test_paper_forward_plan_rejects_incomplete_research_gate_evidence`

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 38 tests in 0.107s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 110 tests in 0.191s
OK
```

PowerShell smoke:

```json
{
  "completeOk": true,
  "completeStatus": "ready_for_paper_forward",
  "completeReady": true,
  "incompleteOk": false,
  "incompleteStatus": "research_gate_evidence_missing",
  "incompleteReady": false,
  "incompleteReasons": "full_backtest_accepted_missing,oos_required_passed_missing,oos_accepted_missing,stress_required_passed_missing,stress_assumptions_passed_missing,stress_accepted_missing"
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
  "last_write_age_sec": 276.07021379470825,
  "stale_after_sec": 900.0
}
```

Postprocess рабочего 24h collect не запускался, потому что manifest еще не финальный.

## Следующий Gate

После `final=true`:

1. `funding-postprocess` с OOS и ненулевым stress.
2. `research_acceptance.accepted=true` и все gate evidence fields true.
3. Только после этого `funding-paper-plan` может стать `ready_for_paper_forward`.

