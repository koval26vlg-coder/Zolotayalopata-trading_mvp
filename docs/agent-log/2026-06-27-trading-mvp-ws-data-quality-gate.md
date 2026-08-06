# trading_mvp WS data-quality gate

Дата/время: 2026-06-27 11:51 +03:00
Агент: Codex
Исходный запрос: продолжить активную цель `trading_mvp` без скрытого long-run.

## План
- Проверить active-run gate и Aion/SML контекст.
- Не запускать 6h WS collect без явного пользовательского approval.
- Добавить read-only data-quality gate для WS JSONL, чтобы после будущего collect не запускать replay/grid на плохом dataset.
- Проверить targeted tests, CLI smoke, PlanOnly и полный unittest suite.

## Что сделано
- Добавлен `trading_mvp/src/ws_data_quality.py`.
- Добавлены tests `trading_mvp/tests/test_ws_data_quality.py` по TDD: сначала RED на отсутствующем модуле, затем GREEN.
- Добавлен CLI subcommand `ws-data-quality` в `trading_mvp/src/cli.py`.
- Добавлен `-Action ws-data-quality` и параметры `WsQuality*` в `trading_mvp/run_mvp.ps1`.
- Обновлен `tools/start_ws_collect_visible.ps1`: после future collect порядок теперь `ws-normalize -> ws-data-quality -> replay/grid только если quality accepted`.
- Обновлен `tools/trading_next_goal_step.ps1`: allowed action включает `run_ws_data_quality_gate_after_normalize`.
- Фактический long collector не запускался.

## Проверки
- Active-run gate: `READY_FOR_POSTPROCESS`, live PIDs нет.
- RED: `python -m unittest trading_mvp.tests.test_ws_data_quality` падал на `ModuleNotFoundError: No module named 'ws_data_quality'`.
- Targeted: `python -m unittest trading_mvp.tests.test_ws_data_quality trading_mvp.tests.test_ws_normalizer trading_mvp.tests.test_ws_collector` -> 10 tests OK.
- CLI smoke: `run_mvp.ps1 -Action ws-data-quality` на `ws_normalized_20260604_085056.jsonl` -> accepted=true, rows=158, exchanges=1, markets=1, event_kinds=3.
- PlanOnly smoke: `start_ws_collect_visible.ps1 -Hours 6 -PlanOnly` -> would_start=false, requires_confirmed_long_run=true, next_after_collect содержит `ws-data-quality`.
- Full suite: `python -m unittest discover -s trading_mvp/tests` -> 196 tests OK.

## Артефакты
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_data_quality_smoke_20260627.json`

## Риски и ограничения
- Это не acceptance стратегии и не торговая рекомендация.
- No live orders, no API keys, no leverage/margin.
- Следующий 6h collect все еще требует явного approval и видимого терминала.
- После будущего collect partial/incomplete dataset должен быть rejected/inconclusive до replay/grid.

## Следующий шаг
После явного approval пользователя запускать видимый collect:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1" -Hours 6 -Exchanges "mexc,gateio" -MaxSymbols 300 -MaxPairsPerExchange 8 -UpdateInterval "100ms" -ConfirmedLongRun
```

После collect: `ws-normalize`, затем `ws-data-quality` с manifest, затем только при accepted=true переходить к event-quality/OOS/replay.
