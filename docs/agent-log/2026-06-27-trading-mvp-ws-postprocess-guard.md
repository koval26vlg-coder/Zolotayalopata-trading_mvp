# trading_mvp guarded WS postprocess

Дата/время: 2026-06-27 11:58 +03:00
Агент: Codex
Исходный запрос: продолжить активную цель `trading_mvp` без скрытого long-run.

## План
- Проверить active-run gate и Aion/SML context.
- Не запускать 6h WS collect без явного approval.
- Добавить guarded `ws-postprocess`, который выполняет `ws-normalize` + `ws-data-quality` и блокирует replay/grid при rejected quality.
- Проверить TDD red/green, CLI wrapper smoke, PlanOnly и полный unittest suite.

## Что сделано
- Добавлен `trading_mvp/src/ws_postprocess.py`.
- Добавлены тесты `trading_mvp/tests/test_ws_postprocess.py`.
- Подключен CLI subcommand `ws-postprocess` в `trading_mvp/src/cli.py`.
- Подключен PowerShell action `-Action ws-postprocess` в `trading_mvp/run_mvp.ps1`.
- Обновлен `tools/start_ws_collect_visible.ps1`: after collect теперь ведет к guarded `ws-postprocess`.
- Обновлен `tools/trading_next_goal_step.ps1`: allowed actions включают `run_guarded_ws_postprocess_after_collect`.
- Long collector, replay, grid, paper-forward и live не запускались.

## Проверки
- Active-run gate: `READY_FOR_POSTPROCESS`, live PIDs нет.
- RED: `python -m unittest trading_mvp.tests.test_ws_postprocess` падал на `ModuleNotFoundError: No module named 'ws_postprocess'`.
- Targeted: `python -m unittest trading_mvp.tests.test_ws_postprocess trading_mvp.tests.test_ws_data_quality trading_mvp.tests.test_ws_normalizer` -> 8 tests OK.
- Wrapper smoke: `run_mvp.ps1 -Action ws-postprocess` на маленьком raw manifest `ws_collect_20260603_170009.json` -> normalized_rows=158, quality accepted=true, replay_allowed=true.
- PlanOnly smoke: `start_ws_collect_visible.ps1 -Hours 6 -PlanOnly` -> would_start=false, requires_confirmed_long_run=true, next_after_collect mentions guarded `ws-postprocess`.
- Full suite: `python -m unittest discover -s trading_mvp/tests` -> 198 tests OK.

## Артефакты smoke
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_postprocess_smoke_20260627.jsonl`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_postprocess_quality_smoke_20260627.json`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_postprocess_smoke_20260627.json`

## Риски и ограничения
- Это не acceptance стратегии и не инвестиционный совет.
- No live orders, no API keys, no leverage/margin.
- Следующий 6h collect требует явного approval и видимого терминала.
- Если future `ws-postprocess` возвращает `replay_allowed=false`, нельзя запускать replay/grid; dataset должен быть rejected/inconclusive или нужно собрать cleaner visible dataset.

## Следующий шаг
После явного approval пользователя запускать видимый collect:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1" -Hours 6 -Exchanges "mexc,gateio" -MaxSymbols 300 -MaxPairsPerExchange 8 -UpdateInterval "100ms" -ConfirmedLongRun
```

После collect: найти `ws_collect_*.json`, запустить `trading_mvp/run_mvp.ps1 -Action ws-postprocess -InputPath <manifest> ...`, затем replay/OOS только если `replay_allowed=true`.
