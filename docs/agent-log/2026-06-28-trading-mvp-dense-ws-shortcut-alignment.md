# trading_mvp dense WS shortcut alignment

Дата: 2026-06-28 17:17 +03:00
Агент: Codex

## Запрос
Продолжить активную цель `trading_mvp`: двигаться к доказательству или отбраковке high-winrate edge, не запуская длинные прогоны без явного подтверждения.

## Маршрут
High-risk trading workflow, но выполнена только короткая инженерная hardening-правка. Collector/backtest/replay/grid не запускались.

## Gate перед работой
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`, rows=2745067, errors=0.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, fail_count=0, warn_count=0.

## Найденная проблема
После выравнивания JSON readback на 72h dense collect старые `.cmd` shortcuts все еще могли увести оператора в 6h path:
- `TRADING_PREVIEW_6H_WS.cmd` запускал `-Hours 6 -PlanOnly`;
- `TRADING_START_6H_WS_CONFIRMED.cmd` требовал `START6H` и запускал `-Hours 6 -ConfirmedLongRun`.

Это противоречило текущему data-sufficiency выводу: повторный blind 6h collect недостаточен для acceptance target 1000 sweep events.

## Что изменено
Добавлены active dense shortcuts:
- `TRADING_PREVIEW_DENSE_WS.cmd` — PlanOnly для `Hours=72`, `MaxPairsPerExchange=16`, dense universe.
- `TRADING_START_DENSE_WS_CONFIRMED.cmd` — видимый 72h research-only collect, требует `START72H`, без live/API/leverage/margin.

Старые 6h shortcuts обезврежены:
- `TRADING_PREVIEW_6H_WS.cmd` теперь явно сообщает, что superseded, и делегирует в dense preview.
- `TRADING_START_6H_WS_CONFIRMED.cmd` больше не запускает collector; сообщает, что нужен dense shortcut, и завершает `exit /b 1`.

Обновлены readback controllers:
- `tools/trading_edge_preflight.ps1` валидирует dense shortcuts и возвращает их paths.
- `tools/trading_goal_status.ps1` active WS shortcut fields указывают на dense shortcuts.
- `tools/trading_next_goal_step.ps1` active WS shortcut fields указывают на dense shortcuts и UI text говорит `START72H`.

Обновлены тесты:
- `trading_mvp/tests/test_visible_ws_collect_wrapper.py` проверяет dense shortcuts, `START72H`, dense universe и что старый 6h confirmed shortcut не содержит `-ConfirmedLongRun`.

## Проверки
- `C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate`: `17 OK, 1 skipped`.
- `C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests`: `215 OK, 1 skipped`.
- Gate: `READY_FOR_POSTPROCESS`.
- Preflight: `READY_FOR_EDGE_PROOF_STEP`, fail_count=0, warn_count=0.
- Preflight shortcut evidence: `Dense WS preview/confirmed shortcuts call the guarded visible wrapper; confirmed shortcut requires START72H, dense universe and -ConfirmedLongRun.`

## Ограничения
- Длинный сбор не запускался.
- Нет accepted strategy.
- Нет paper-forward/live/API/leverage/margin.
- `Рой` для этого checkpoint ранее был `swarm_limited`; Codex продолжает ручное управление до следующего meaningful checkpoint.

## Следующий шаг
Только после явного подтверждения пользователя: запуск видимого `TRADING_START_DENSE_WS_CONFIRMED.cmd` с вводом `START72H` или эквивалентной команды `tools/start_ws_collect_visible.ps1 -Hours 72 ... -ConfirmedLongRun`.
