# trading_mvp dense WS swarm L1 and manual review

Дата: 2026-06-28 17:00 +03:00
Агент: Codex

## Запрос
Продолжить цель `trading_mvp`: двигаться к доказательству или отбраковке high-winrate edge, не запуская скрытые/фоновые прогоны и не тратя лимиты во время активных run.

## Gate перед работой
- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`, rows=2745067, errors=0, active monitor не жив.
- `tools/trading_edge_preflight.ps1 -Json`: `READY_FOR_EDGE_PROOF_STEP`, fail_count=0, warn_count=0.
- `tools/trading_strategy_acceptance_gate.ps1 -Json`: `accepted=false`, `live_orders=false`.

## Рой
Workflow: `D:\AionUi-Paperclip\docs\agent-workflows\2026-06-28-164718-083294-trading-mvp-dense-ws-collect-plan-review`.

Сделано:
- Исправлены ошибочные risk flags в `contract.json`: `trading=true`, `long_running=true`, `risk_gate.required=true`, `risk_gate.status=pending`.
- Запущен L1 Antigravity review в read-only режиме.
- Первый output был синтаксически валиден, но нерелевантен: обсуждал `funding_blocked_by_swarm`, а не 72h/32-market dense WS collect.
- Повтор с relevance guard завершился ошибкой: `agy --print returned empty stdout and no DB response was recovered`.
- Зафиксирован `swarm_limited` и blocker в workflow; Antigravity handoff не принят как валидный L1.

## Ручной Codex verdict
Текущий 6h dataset недостаточен для вывода по liquidity sweep/reversal:
- 43 sweep events за ~6h на 16 markets;
- acceptance target: 1000 sweep events;
- false_sweep_rate около 0.6977;
- best grid trades: 11, ниже устойчивого порога.

Планировщик данных:
- 16 markets: ~139.5h до target_sweeps;
- 24 markets: ~93.0h;
- 32 markets: ~69.8h, округлено до 72h;
- 48 markets: ~46.5h, но выше нагрузка.

Ручной вывод: следующий правильный proof-step — не еще один 6h blind run, а видимый 72h dense WS collect на 32 markets через MEXC/Gate, после явного подтверждения пользователя.

## Артефакты
- `exports/trading-mvp/analysis/trading_data_sufficiency_plan_ws_confirmed_research_6h_20260628.json`
- `exports/trading-mvp/analysis/trading_dense_ws_collect_plan_20260628.json`
- `exports/trading-mvp/universe/no_binance_dense_ws_sweep_20260628.csv`
- `exports/trading-mvp/run/ws_collect_6h_plan_preview_latest.json`
- `D:\AionUi-Paperclip\docs\agent-workflows\2026-06-28-164718-083294-trading-mvp-dense-ws-collect-plan-review\tmp-l1-antigravity-relevance-failure.md`

## Обновленный PlanOnly preview
Выполнено без запуска collector:
`pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\start_ws_collect_visible.ps1 -Hours 72 -MaxPairsPerExchange 16 -UniversePath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" -PlanOnly`

Результат preview:
- `would_start=false`;
- `requires_confirmed_long_run=true`;
- `hours=72`;
- `max_pairs_per_exchange=16`;
- `universe_path=exports/trading-mvp/universe/no_binance_dense_ws_sweep_20260628.csv`.

Команда фактического запуска только после отдельного явного подтверждения пользователя:
`pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1" -Hours 72 -MaxPairsPerExchange 16 -UniversePath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" -ConfirmedLongRun`

## Проверки после работы
- Gate: `READY_FOR_POSTPROCESS`.
- Preflight: `READY_FOR_EDGE_PROOF_STEP`, fail=0, warn=0.
- Acceptance gate: `accepted=false`, `live_orders=false`.
- Workflow status: `last_event=swarm_limited`, blocker recorded.

## Ограничения
- Длинный сбор не запускался.
- Нет accepted strategy.
- Нет paper-forward/live/API/leverage/margin.
- Рекомендация не является инвестсоветом; это исследовательский сбор данных для proof pipeline.

## Следующий шаг
Получить явное подтверждение пользователя на 72h visible dense WS collect. После завершения: guarded ws-postprocess, затем replay validation PlanOnly, затем только при валидном postprocess и отдельном подтверждении — ConfirmedResearchRun для replay/grid.
