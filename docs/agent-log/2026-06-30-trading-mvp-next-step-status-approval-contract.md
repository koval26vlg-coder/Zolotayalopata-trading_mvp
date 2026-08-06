# trading_mvp next-step/status approval contract readback

Дата: 2026-06-30 14:58:31 +03:00
Агент: Codex
Запрос пользователя: продолжить активную цель trading_mvp без запуска долгого market-прогона.

## План
- Проверить Aion memory bootstrap и active-run gate.
- Не запускать collect/replay/grid без START72H.
- Сделать короткую инженерную правку, которая повышает качество proof pipeline.
- Проверить targeted/full regression и preflight.

## Что сделано
- В 	ools/trading_goal_status.ps1 добавлен collect_approval_contract_command.
- В 	ools/trading_next_goal_step.ps1 добавлен commands.collect_approval_contract и вывод в человекочитаемом режиме.
- В 	rading_mvp/tests/test_visible_ws_collect_wrapper.py обновлены проверки goal-status и next-goal readback.
- Долгий сбор, replay, grid-search, postprocess и live/paper-forward не запускались.

## Проверки
- 	ools/check_active_run_gate.ps1: status=READY_FOR_POSTPROCESS, replay_allowed=false, requires_explicit_user_approval_for_actual_collect=true.
- 	ools/trading_goal_status.ps1 -Json: содержит collect_approval_contract_command.
- 	ools/trading_next_goal_step.ps1 -Json: содержит commands.collect_approval_contract.
- 	ools/trading_collect_approval_contract.ps1 -Json: ok=true, status=APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT, fail_count=0, warn_count=0.
- Targeted unittest: 3 tests OK.
- Full visible-wrapper unittest: 14 tests OK, skipped=1.
- 	ools/trading_edge_preflight.ps1 -Json: ok=true, READY_FOR_EDGE_PROOF_STEP, fail_count=0, warn_count=0.

## Текущий статус цели
- Прогон сейчас не идет.
- Текущий WS postprocess artifact остается rejected: replay_allowed=false / min_duration_ratio.
- Replay/grid на этом artifact запрещены.
- Следующий реальный proof step: visible 72h dense WS collect только после явного START72H.
- No live orders, no API keys, no leverage/margin, no investment advice.

## Риски и ограничения
- Full python -m unittest discover -s trading_mvp/tests не запускался, потому что изменение ограничено operator readback/visible-wrapper тестами; полный discover раньше мог занимать больше лимита и таймаутиться.
- Aion memory watcher stale/locked; checkpoint вручную продублирован в Aion agent-log.

## Следующий агент должен проверить
- Перед любым следующим шагом: 	ools/check_active_run_gate.ps1.
- Если пользователь не сказал START72H: разрешены только короткие guard/readiness/contract улучшения.
- Если пользователь сказал START72H: сначала 	ools/trading_collect_approval_contract.ps1 -Json, затем видимый guarded старт через TRADING_START_DENSE_WS_CONFIRMED.cmd или command_after_explicit_approval.
