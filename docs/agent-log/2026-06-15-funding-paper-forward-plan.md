# Funding Paper-Forward Plan Gate

Дата: 2026-06-15

## Цель

Зафиксировать следующий безопасный переход для `funding/basis carry`: после успешного 24h postprocess и OOS-gate не запускать live trading, а сформировать frozen paper-forward plan без API keys, leverage, margin execution и live orders.

## Реализовано

- Добавлен `funding-paper-plan` CLI/PowerShell action.
- План создается только из `funding-postprocess` artifact.
- Если `research_acceptance.accepted=true`, artifact получает статус `ready_for_paper_forward`.
- Если `research_acceptance.accepted=false`, artifact создается, но получает статус `research_not_accepted` и `ready_for_paper_forward=false`.
- Frozen config включает backtest, acceptance, stress и rank config из postprocess artifact.

## Проверка

Команда:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 102 tests in 0.222s
OK
```

Smoke `funding-paper-plan` через `trading_mvp\run_mvp.ps1`:

```json
{
  "acceptedOk": true,
  "acceptedReady": true,
  "acceptedPlanExists": true,
  "acceptedMinHours": 48.0,
  "rejectedOk": false,
  "rejectedReady": false,
  "rejectedPlanExists": true
}
```

## Статус 24h funding collect

Output:

```text
exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl
```

Manifest:

```text
exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json
```

Проверка `funding-status`:

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 14,
  "cycles": 288,
  "remaining_cycles": 274,
  "progress_pct": 4.861111111111112,
  "manifest_rows": 312,
  "line_count": 312,
  "line_count_matches_manifest": true,
  "errors": 80,
  "last_write_age_sec": 170.17107486724854,
  "stale_after_sec": 900.0
}
```

Активные процессы на момент проверки:

```json
[
  {"Id": 19088, "ProcessName": "pwsh"},
  {"Id": 22644, "ProcessName": "python"},
  {"Id": 24432, "ProcessName": "python"}
]
```

## Gate

Postprocess не запускать до выполнения всех условий:

- `final=true`
- `completed_cycles=288`
- `line_count_matches_manifest=true`
- процесс завершен штатно
- stderr не содержит критических ошибок

После этого выполнить:

1. `funding-postprocess` с OOS output.
2. Проверить `research_acceptance.accepted`.
3. Если accepted, создать `funding-paper-plan`.
4. Запустить только paper-forward сбор/симуляцию, без live orders.

