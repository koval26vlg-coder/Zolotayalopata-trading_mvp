# Funding Paper-Forward Runner

Дата: 2026-06-15

## Цель

Закрыть пробел между accepted `funding-paper-plan` и фактической forward-проверкой: добавить research-only runner, который применяет frozen config к отдельному forward JSONL dataset и пишет audit trail без live orders, API keys, leverage и margin execution.

## Реализовано

- Добавлен `run_funding_paper_forward_file()` в `trading_mvp/src/basis.py`.
- Добавлена CLI-команда `funding-paper-forward`.
- Добавлен PowerShell action `funding-paper-forward`.
- Добавлен `-FundingPlanPath` в `trading_mvp/run_mvp.ps1`.
- Добавлена защита от повторного использования in-sample `source_input` как forward input.
- Output пишется как JSONL audit trail:
  - `start`
  - `trade` для каждой paper-сделки
  - `summary`

## Safety Invariants

- `research_only=true`
- `live_orders=false`
- `api_keys_required=false`
- `leverage_enabled=false`
- `margin_execution=false`
- rejected/unready plan не запускает paper-forward backtest
- source input reuse блокируется по умолчанию

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 33 tests in 0.103s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 105 tests in 0.184s
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
  "accepted": true,
  "liveOrders": false
}
```

## Статус 24h Funding Collect

Проверка после реализации:

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
  "last_write_age_sec": 42.53934407234192,
  "stale_after_sec": 900.0
}
```

Postprocess не запускался, потому что manifest еще не финальный.

## Следующий Gate

Когда 24h collector завершится:

1. Запустить `funding-postprocess` с OOS output и stress gates.
2. Если `research_acceptance.accepted=true`, создать `funding-paper-plan`.
3. Собрать отдельный forward JSONL dataset.
4. Запустить `funding-paper-forward -FundingPlanPath <plan> -InputPath <forward_jsonl>`.
5. Принимать только по paper-forward metrics: net PnL после costs, winrate, expectancy, drawdown, sample size и stability.

