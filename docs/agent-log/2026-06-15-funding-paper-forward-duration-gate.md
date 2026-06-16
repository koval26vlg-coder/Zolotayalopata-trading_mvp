# Funding Paper-Forward Duration Gate

Дата: 2026-06-15

## Цель

Усилить `funding-paper-forward`: запретить принимать paper-forward результат на слишком короткой forward-выборке. Даже прибыльный forward backtest не считается accepted, если покрытие меньше `min_forward_hours` из frozen plan.

## Реализовано

- Добавлен расчет forward coverage:
  - `rows`
  - `markets`
  - `first_ts`
  - `last_ts`
  - `span_sec`
  - `span_hours`
  - `min_forward_hours`
  - `duration_accepted`
- `paper_acceptance.accepted` теперь объединяет:
  - backtest acceptance gates
  - duration gate
- При недостаточной длительности добавляется reason:
  - `min_forward_hours`
- Coverage пишется в итоговый JSONL `summary`.

## Измененные участки

- `trading_mvp/src/basis.py`
  - `run_funding_paper_forward_file`
  - `_funding_forward_coverage`
  - `_funding_paper_forward_acceptance`
- `trading_mvp/tests/test_basis.py`
  - `test_paper_forward_rejects_when_forward_duration_is_too_short`

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 34 tests in 0.078s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 106 tests in 0.180s
OK
```

PowerShell smoke:

```json
{
  "ok": true,
  "status": "completed",
  "outputExists": true,
  "outputLines": 3,
  "trades": 1,
  "accepted": false,
  "reasons": "min_forward_hours",
  "spanHours": 1.0,
  "minForwardHours": 24.0,
  "liveOrders": false
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 16,
  "cycles": 288,
  "remaining_cycles": 272,
  "progress_pct": 5.555555555555555,
  "manifest_rows": 360,
  "line_count": 360,
  "line_count_matches_manifest": true,
  "errors": 92,
  "last_write_age_sec": 256.63262033462524,
  "stale_after_sec": 900.0
}
```

Postprocess не запускался, потому что manifest еще не финальный.

## Следующий Gate

Дальше нельзя принимать стратегию, пока не будет:

1. `funding-postprocess` на финальном 24h dataset.
2. OOS acceptance.
3. Stress acceptance.
4. Frozen `funding-paper-plan`.
5. Отдельный forward dataset с `span_hours >= min_forward_hours`.
6. `funding-paper-forward` accepted по net PnL, winrate, expectancy, drawdown, sample size и duration coverage.

