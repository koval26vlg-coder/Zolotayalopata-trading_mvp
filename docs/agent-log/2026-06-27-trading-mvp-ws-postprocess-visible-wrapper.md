# trading_mvp WS postprocess visible wrapper

Дата: 2026-06-27 12:23 Europe/Volgograd
Агент: Codex
Запрос: продолжать цель trading_mvp без явного запуска долгого 6h collector.

## План
- Проверить active-run gate.
- Найти пробел после visible WS collect.
- Добавить guarded visible wrapper для postprocess последнего WS manifest.
- Проверить PlanOnly, smoke, preflight, acceptance и tests.

## Что сделано
- Gate проверен: `READY_FOR_POSTPROCESS`, активного RUNNING процесса нет.
- Добавлен `tools/run_ws_postprocess_visible.ps1`:
  - запрещает работу при `RUNNING` или `STOPPED_INCOMPLETE` active-run gate;
  - берет `ws_collect_*.json` manifest из active-run gate, если он WS, либо требует явный `-ManifestPath`;
  - поддерживает `-PlanOnly`;
  - вызывает `trading_mvp/run_mvp.ps1 -Action ws-postprocess`;
  - пишет normalized JSONL, data-quality JSON, postprocess JSON и console log;
  - выводит `replay_allowed`; если false, запрещает replay/grid на dataset.
- Добавлен `TRADING_WS_POSTPROCESS_FROM_GATE.cmd` для видимого запуска postprocess после завершенного WS collect.
- Обновлен `tools/start_ws_collect_visible.ps1`: next-after-collect теперь указывает на `tools/run_ws_postprocess_visible.ps1`.
- Обновлен `tools/trading_next_goal_step.ps1`: показывает WS postprocess command/shortcut.
- Обновлен `tools/trading_edge_preflight.ps1`: добавлены checks `ws_postprocess_wrapper` и `ws_postprocess_quality_gate`.

## Проверки
- `tools/run_ws_postprocess_visible.ps1 -PlanOnly -NoPause`: при текущем funding gate возвращает `ws_manifest_required` и ничего не запускает.
- `tools/run_ws_postprocess_visible.ps1 -ManifestPath ...ws_collect_20260603_170009.json -PlanOnly`: строит корректный план и output paths.
- Smoke на старом маленьком WS manifest с relaxed thresholds: normalize/data-quality/postprocess artifacts созданы, `replay_allowed=true` только в smoke-конфигурации.
- `tools/check_active_run_gate.ps1`: gate остался `READY_FOR_POSTPROCESS`, active process нет.
- `tools/trading_edge_preflight.ps1`: 0 failures, 0 warnings; WS postprocess checks passed.
- `tools/trading_strategy_acceptance_gate.ps1`: `research_only_no_accepted_strategy`, live/paper blocked.
- `tools/trading_next_goal_step.ps1`: показывает WS collect и WS postprocess команды.
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m unittest discover -s trading_mvp/tests`: 198 tests OK.

## Артефакты smoke
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_normalized_ws_postprocess_wrapper_smoke_20260627.jsonl`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_data_quality_ws_postprocess_wrapper_smoke_20260627.json`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_postprocess_ws_postprocess_wrapper_smoke_20260627.json`

## Решение
- Новый долгий WS collect не запускался.
- Следующий фактический шаг цели по-прежнему требует явного подтверждения пользователя: visible 6h WS collect через `TRADING_START_6H_WS_CONFIRMED.cmd` с вводом `START6H`.
- После завершения collect следующий agent должен запускать `TRADING_WS_POSTPROCESS_FROM_GATE.cmd` или `tools/run_ws_postprocess_visible.ps1`; replay/grid разрешены только если postprocess artifact содержит `replay_allowed=true`.

## Риски
- Не ослаблять strict WS quality defaults для реального 6h dataset без отдельного labeled relaxed experiment.
- Не запускать скрытые collectors/replay/grid/paper-forward.
- Не считать smoke на старом 5-second dataset доказательством edge.
