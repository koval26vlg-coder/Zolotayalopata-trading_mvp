# trading_mvp visible WS launch shortcuts

Дата: 2026-06-27 12:17 Europe/Volgograd
Агент: Codex
Запрос: продолжить цель trading_mvp после funding final-review; не запускать долгий прогон без явного подтверждения.

## План
- Проверить active-run gate.
- Выполнить безопасный `PlanOnly` для следующей ветки `spot_maker_liquidity_sweep_reversal_event_quality`.
- Добавить видимые WS shortcut-обертки без скрытого запуска.
- Проверить gates/tests.

## Что сделано
- Gate проверен: `READY_FOR_POSTPROCESS`, активного RUNNING процесса нет.
- Выполнен `tools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly`: `would_start=false`, `requires_confirmed_long_run=true`, branch `NEXT_BRANCH_SPOT_MAKER_LIQUIDITY_SWEEP_REVERSAL`, selected `spot_maker_liquidity_sweep_reversal_event_quality`.
- Создан `TRADING_PREVIEW_6H_WS.cmd`: запускает только PlanOnly и не стартует collector.
- Создан `TRADING_START_6H_WS_CONFIRMED.cmd`: требует ввод `START6H`, затем запускает видимый 6h WS collect через `tools/start_ws_collect_visible.ps1 -ConfirmedLongRun`.
- Обновлен `tools/trading_next_goal_step.ps1`: теперь показывает WS preview/start shortcut paths.
- Проверена отмена start shortcut через ввод `NO`: `Start cancelled`, collector не стартовал.

## Проверки
- `tools/check_active_run_gate.ps1`: gate остался `READY_FOR_POSTPROCESS`, live PIDs нет.
- `tools/trading_edge_preflight.ps1`: 0 failures, 0 warnings.
- `tools/trading_strategy_acceptance_gate.ps1`: `research_only_no_accepted_strategy`, paper/live blocked.
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests`: 198 tests OK.

## Риски и ограничения
- Фактический 6h WS collect не запускался. Его можно запускать только после явного пользовательского подтверждения и только видимо.
- Funding branch на текущем 7d dataset остается заблокирован data-quality gate; это не accepted strategy.
- Не делать channel/P2P/off-ramp/custody/legal анализ в рамках этой цели.

## Следующий шаг
Если пользователь явно подтверждает запуск, открыть видимый `TRADING_START_6H_WS_CONFIRMED.cmd` и ввести `START6H`, либо выполнить:
`pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1 -Hours 6 -Exchanges "mexc,gateio" -MaxSymbols 300 -MaxPairsPerExchange 8 -UpdateInterval "100ms" -ConfirmedLongRun`

После завершения collect: guarded `ws-postprocess`, затем replay/grid/OOS только если data-quality accepts coverage.
