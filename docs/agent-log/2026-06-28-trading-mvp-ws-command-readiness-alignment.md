# trading_mvp WS command readiness alignment

Дата: 2026-06-28 17:08 +03:00
Агент: Codex

## Запрос
Продолжить активную цель `trading_mvp`: двигаться к доказательству или честной отбраковке high-winrate edge, не запуская длинные прогоны без явного подтверждения.

## Маршрут
High-risk trading workflow, но выполнена только короткая инженерная правка readiness/readback. Длинный collector/backtest/replay/grid не запускался.

## Gate перед работой
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`, rows=2745067, errors=0.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, fail_count=0, warn_count=0.

## Найденная проблема
После подготовки 72h dense WS PlanOnly preview некоторые status/readiness контроллеры все еще отдавали stale-команды:
- `visible_ws_collect_command = ... -Hours 6 -ConfirmedLongRun`;
- `visible_collect_command = ... -Hours 6 -ConfirmedLongRun`.

Это создавало риск, что следующий агент или оператор запустит короткий 6h прогон вместо рассчитанного 72h dense collect.

## Что изменено
Обновлены:
- `tools/trading_edge_preflight.ps1`
- `tools/trading_goal_status.ps1`
- `tools/trading_next_goal_step.ps1`
- `trading_mvp/tests/test_visible_ws_collect_wrapper.py`

Добавлен resolver WS collect команд:
- читает `exports/trading-mvp/run/ws_collect_6h_plan_preview_latest.json`;
- если preview валиден и `would_start=false`, использует его `hours`, `max_pairs_per_exchange`, `universe_path`, `command_after_explicit_approval`;
- fallback на 6h сохраняется только если preview отсутствует или битый;
- в JSON readback добавлено `visible_ws_collect_command_resolution`.

## Проверенное текущее состояние
Все три контроллера теперь показывают:
- `source=latest_plan_preview`;
- `effective_hours=72`;
- `effective_max_pairs_per_exchange=16`;
- `effective_universe_path=exports/trading-mvp/universe/no_binance_dense_ws_sweep_20260628.csv`;
- actual command содержит `-Hours 72`, `-UniversePath ...no_binance_dense_ws_sweep_20260628.csv`, `-ConfirmedLongRun`.

## Проверки
- `python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate`: `16 OK, 1 skipped`.
- `python -m unittest discover -s trading_mvp\tests`: `214 OK, 1 skipped`.
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, fail_count=0, warn_count=0.
- `tools/trading_goal_status.ps1 -Json`: readback uses `latest_plan_preview` and 72h command.
- `tools/trading_next_goal_step.ps1 -Json`: `primary_command` is 72h PlanOnly; `visible_collect_after_approval` is 72h ConfirmedLongRun.

## Ограничения
- Collector не запускался.
- Нет accepted strategy.
- Нет paper-forward/live/API/leverage/margin.
- `Рой` для этого checkpoint ранее зафиксирован как `swarm_limited`; Codex продолжает ручное управление до следующего meaningful checkpoint.

## Следующий шаг
Нужно отдельное явное подтверждение пользователя на видимый 72h dense WS collect. После завершения collect: guarded ws-postprocess, затем replay validation PlanOnly, затем ConfirmedResearchRun только при валидном postprocess и отдельном подтверждении.
