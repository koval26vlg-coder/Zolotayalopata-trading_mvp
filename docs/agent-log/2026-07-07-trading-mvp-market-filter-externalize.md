# trading_mvp market-filter and external data migration

Дата: 2026-07-07 23:40 +03:00
Агент: Codex

## Запрос пользователя
Продолжить текущий шаг: market-level quality filter для clean slice, затем data-quality, и только если replay_allowed=true — replay-validation PlanOnly. После появления внешнего диска E: перенести тяжелые trading_mvp data/export файлы туда для экономии места.

## Что сделано
- Добавлен `trading_mvp/src/ws_market_filter.py`: потоковый двухпроходный market-level filter по `bbo/depth/trade`, per-market gap, coverage, duration ratio, exchange count и итоговый guarded postprocess.
- Добавлен `trading_mvp/tests/test_ws_market_filter.py`.
- Добавлен `tools/run_ws_market_filter_visible.ps1` для видимого запуска market-filter с progress JSONL.
- Запущен visible market-filter на clean slice `ws_durable_72h_clean_window0_basepy_20260707_1842`.
- Добавлен и использован `tools/move_trading_mvp_exports_to_external.ps1` для переноса `exports/trading-mvp` на внешний диск `E:` с junction на старом пути.
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp` теперь junction на `E:\ZolotyayLopata-data\exports\trading-mvp`.
- Старый `D:\ZolotyayLopata-data\raw-durable` удален после byte/file verification с новой копией на `E:`.
- `docs/agent-log/active-run-gate.json` обновлен: `replay_allowed=false`, `next_goal_decision=BLOCK_REPLAY_MARKET_FILTER_REJECTED`.

## Результат market-filter
- input rows: 52,578,045.
- output rows: 34,131,510.
- accepted_markets: 16.
- rejected_markets: 16.
- output_exchanges: 1.
- output_markets: 16.
- data_quality max_gap_sec: ~197.99.
- markets_with_gap_over_limit: 0.
- replay_allowed: false.
- block reason: `min_accepted_exchanges` / `min_exchanges`.

## Результат переноса данных
- Старый путь сохранен как junction: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp` -> `E:\ZolotyayLopata-data\exports\trading-mvp`.
- Проверены ключевые артефакты через старые `C:` пути.
- `C:` free после переноса: ~51.7 GB.
- `D:` free после удаления старого raw-durable: ~50.5 GB.
- `E:` free после переноса: ~818 GB.

## Проверки
- `python -m unittest trading_mvp.tests.test_ws_market_filter trading_mvp.tests.test_ws_data_quality trading_mvp.tests.test_ws_slice_postprocess trading_mvp.tests.test_ws_gap_audit` -> 9 OK.
- `tools/check_active_run_gate.ps1 -Json` -> READY_FOR_POSTPROCESS, but warning says replay/grid blocked because replay_allowed=false.
- File verification for raw-durable before deleting D target: 140 files, 39,782,319,362 bytes matched.

## Риски и ограничения
- Replay-validation PlanOnly не запускался, потому что текущий filtered clean slice не прошел cross-exchange quality gate.
- Текущий dataset полезен для диагностики feed/venue coverage, но не является допустимым входом для strategy replay по прежним gate-правилам.
- Следующий исследовательский шаг должен решить проблему cross-exchange survival: новый clean-slice policy, отдельный per-exchange replay только как weaker evidence при явном разрешении, или новый сбор/universe adjustment.

## Следующий агент
- Не запускать replay/grid по текущему artifact без изменения gate/явного решения пользователя.
- Начать с `tools/check_active_run_gate.ps1`.
- Все heavy exports теперь физически на `E:`; старые `C:` пути должны работать через junction.
