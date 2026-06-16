# Active Run Gate

Дата: 2026-06-16

## Текущий статус
- Gate status: RUNNING
- Run ID: funding_collect_24h_spotliq_resume_20260616_1130_visible
- Cycles: 142/288
- Rows: 3414
- Errors: 816
- Estimated finish: 2026-06-16 23:59:37 +03:00
- Monitor PID alive: True

## Решение
Пока gate status = RUNNING, следующие шаги цели запрещены: postprocess, grid/search, новые collectors, расширенная аналитика, кодовые правки и любые инженерные задачи, не нужные для контроля текущего прогона.

Разрешено только:
- проверить статус через C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1;
- сообщить cycles/rows/errors/last write/ETA;
- если STOPPED_INCOMPLETE, предложить видимый resume или признать dataset неполным.

После READY_FOR_POSTPROCESS следующий разрешенный шаг:
- funding-rank;
- funding-backtest/postprocess;
- краткая аналитика результата research-only без инвестсовета.

## Механизм
- Gate file: C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json
- Check script: C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1
- Manual visible check wrapper: C:\Users\koval\Documents\ZolotyayLopata\CHECK_ACTIVE_RUN_GATE.cmd
- Heartbeat: trading-mvp-funding-gate-check
