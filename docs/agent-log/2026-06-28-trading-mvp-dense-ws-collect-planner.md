# trading_mvp dense WS collect planner

Дата: 2026-06-28 16:47 +03:00
Агент: Codex

## Запрос
Продолжить цель `trading_mvp`: доказать или отбросить рабочий high-winrate edge на non-Binance markets через данные, backtest, OOS/walk-forward/stress/economics/paper-forward gates.

## Gate перед работой
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`, активного RUNNING процесса нет.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, `fail_count=0`, `warn_count=0`.

## Что сделано
- Добавлен `tools/trading_dense_ws_collect_plan.ps1`.
- `tools/start_ws_collect_visible.ps1` теперь поддерживает `-UniversePath` и в `-PlanOnly` включает `dense_collect_plan`.
- `tools/trading_edge_preflight.ps1` теперь проверяет `dense_ws_collect_planner`.
- Обновлены тесты `trading_mvp/tests/test_visible_ws_collect_wrapper.py`.
- Сохранены artifacts:
  - `exports/trading-mvp/analysis/trading_dense_ws_collect_plan_20260628.json`;
  - `exports/trading-mvp/universe/no_binance_dense_ws_sweep_20260628.csv`;
  - `exports/trading-mvp/run/ws_collect_6h_plan_preview_latest.json`.

## Ключевые расчеты
Текущий 6h dataset:
- `total_sweeps=43`;
- `market_count=16`;
- `sweep_rate_per_market_hour=0.44787282`;
- acceptance target: `1000` sweep events.

Dense planner options:
- 16 рынков: около `139.549h`, округление до `144h`, не проходит `TargetMaxHours=72`;
- 24 рынка: около `93.032h`, округление до `96h`, не проходит `TargetMaxHours=72`;
- 32 рынка: около `69.774h`, округление до `72h`, выбранный вариант;
- 48 рынков: около `46.516h`, округление до `48h`, быстрее, но выше нагрузка на WS.

Выбранный conservative/balanced вариант:
`Hours=72`, `MaxPairsPerExchange=16`, `UniversePath=exports/trading-mvp/universe/no_binance_dense_ws_sweep_20260628.csv`.

Команда, только после явного подтверждения пользователя:
`pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1" -Hours 72 -MaxPairsPerExchange 16 -UniversePath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" -ConfirmedLongRun`

## Рой
Создан checkpoint:
- `workflow_id=2026-06-28-164718-083294-trading-mvp-dense-ws-collect-plan-review`;
- state: `planned`;
- current_level: `L1`;
- allowed_next_agents: `Antigravity CLI`.

Цель checkpoint: независимая проверка dense collect plan перед любым длинным сбором.

## Проверки
- `tools/trading_dense_ws_collect_plan.ps1 -Json -OutputPath exports/trading-mvp/analysis/trading_dense_ws_collect_plan_20260628.json`: OK.
- `tools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly`: OK, collector не запускался.
- `C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate`: `16 OK, 1 skipped`.
- `C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests`: `214 OK, 1 skipped`.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, `fail_count=0`, `warn_count=0`.
- `tools/trading_strategy_acceptance_gate.ps1 -Json`: `accepted=false`, `live_orders=false`.

## Ограничения
- Actual collector не запускался.
- Нет accepted strategy.
- Нет paper-forward разрешения.
- Нет live/API/leverage/margin.
- Расчет для новых рынков использует assumption same sweep rate per market-hour; это нужно проверить фактическим collect.

## Следующий шаг
Перед стартом 72h dense collect желательно дождаться L1 review от `Рой`. Если review недоступен или лимиты исчерпаны, Codex может продолжить ручное управление, но long run все равно требует явного подтверждения пользователя и видимого терминала.
