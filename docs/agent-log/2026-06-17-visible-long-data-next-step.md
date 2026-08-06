# Visible Long Data Next Step

Дата: 2026-06-17

## Что сделано

- Проверен active-run gate: текущий 24h funding collect завершен, живых PID нет.
- Синхронизирован `docs/agent-log/active-run-gate.json`: статус обновлен с `RUNNING` на `READY_FOR_POSTPROCESS`, stale `process_ids` очищены.
- Зафиксирован checkpoint в `docs/plans/2026-06-15-trading-mvp-research-goal.md`: 24h funding ветка rejected по экономике.
- Создан план следующего этапа: `docs/plans/2026-06-17-trading-mvp-visible-long-data-plan.md`.
- Создан видимый launcher: `tools/start_funding_collect_visible.ps1`.

## Почему не запущен новый прогон

7d funding collect является длительным процессом. По правилу Visible Run Rule он запускается только в видимом терминале/monitor и только после явного подтверждения пользователя.

## Следующий шаг после подтверждения

Запустить видимый 7d funding/basis collect:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun
```

Во время `RUNNING` не выполнять другие шаги по цели, кроме коротких status/ETA проверок:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1
```

## Критерий продолжения цели

После `manifest.final=true` и `completed_cycles >= cycles`: запускать postprocess/final-review/OOS/walk-forward/stress/cost-sensitivity и обновлять вывод по жизнеспособности стратегии.


