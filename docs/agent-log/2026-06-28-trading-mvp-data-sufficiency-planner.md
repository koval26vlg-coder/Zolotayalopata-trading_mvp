# trading_mvp data sufficiency planner

Дата: 2026-06-28 16:33 +03:00
Агент: Codex

## Запрос
Продолжить цель `trading_mvp`: искать и доказывать/отбрасывать trading edge через данные, backtest, OOS/walk-forward/stress/economics, без live orders/API keys/leverage/margin.

## Проверенный gate
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`, `expected_outputs_complete=true`, `rows=2745067`, `errors=0`.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, `fail_count=0`, `warn_count=0`.

## Что сделано
- Добавлен read-only planner `tools/trading_data_sufficiency_plan.ps1`.
- Planner читает текущие WS/event-quality/acceptance/grid artifacts и считает:
  - `sweep_rate_per_hour`;
  - `sweep_rate_per_market_hour`;
  - требуемые часы/market-hours до `target_sweeps`;
  - требуемые часы до `target_trades`;
  - сценарии для 16/24/32/48 рынков.
- Planner встроен в `tools/trading_edge_preflight.ps1` как check `data_sufficiency_planner`.
- Добавлен regression/unit test в `trading_mvp/tests/test_visible_ws_collect_wrapper.py`.
- Сохранен artifact: `exports/trading-mvp/analysis/trading_data_sufficiency_plan_ws_confirmed_research_6h_20260628.json`.

## Ключевой результат
Текущий 6h WS dataset:
- `observed_hours=6.000587`;
- `market_count=16`;
- `total_sweeps=43`;
- acceptance target: `target_sweeps=1000`;
- `sweep_rate_per_hour=7.165965`;
- `sweep_rate_per_market_hour=0.44787282`.

Оценка до 1000 sweep-событий:
- 16 рынков: около `139.549` часов / `5.815` дней;
- 24 рынка: около `93.032` часов / `3.876` дней;
- 32 рынка: около `69.774` часов / `2.907` дней;
- 48 рынков: около `46.516` часов / `1.938` дней.

Вывод planner: повторный 6h collect почти наверняка недостаточен для event gate; следующий сбор нужно планировать по market-hours и плотности событий, а не как еще один короткий прогон.

## Проверки
- `tools/trading_data_sufficiency_plan.ps1 -Json`: OK.
- `tools/trading_data_sufficiency_plan.ps1 -Json -OutputPath exports/trading-mvp/analysis/trading_data_sufficiency_plan_ws_confirmed_research_6h_20260628.json`: OK.
- `C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate`: `15 OK, 1 skipped`.
- `C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests`: `213 OK, 1 skipped`.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, `fail_count=0`, `warn_count=0`.
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`.

## Ограничения
- Нет accepted strategy.
- `paper_forward_allowed=false`.
- `live_orders=false`, `api_keys=false`, `leverage_or_margin=false`.
- Расчет assumes same sweep rate per market-hour for alternative market counts; перед длинным сбором нужно выбрать более плотные markets, иначе market-hour estimate будет оптимистичным.

## Следующий шаг
Не запускать еще один слепой 6h collect. Следующий инженерный шаг: сделать/обновить visible dense collect preview так, чтобы он выбирал более плотные рынки и целился в достаточные market-hours; фактический долгий запуск только в видимом терминале и только после явного подтверждения пользователя.
