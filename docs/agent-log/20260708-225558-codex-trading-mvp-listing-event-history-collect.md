# Codex trading_mvp listing-event OHLCV history collect

Дата: 2026-07-08 22:55:58 +03:00
Агент: Codex
Запрос пользователя: подтверждаю visible listing-event OHLCV history collect

## Краткий план
- Проверить active-run gate и routing-команды.
- Довести visible listing-event history collect до запуска в отдельном PowerShell-окне.
- Не запускать replay/grid/live/API keys; только public REST research collect.
- После завершения оставить следующий шаг на data-quality gate.

## Что сделано
- Добавлен/исправлен research-only collector: 	rading_mvp/src/listing_event_history_collector.py.
- Добавлен/исправлен visible wrapper: 	ools/start_listing_event_history_collect_visible.ps1.
- Обновлены routing-команды в 	ools/trading_next_goal_step.ps1, 	ools/trading_goal_status.ps1, 	ools/trading_branch_selector.ps1.
- Добавлены/обновлены tests: 	rading_mvp/tests/test_listing_event_history_collector.py, 	rading_mvp/tests/test_visible_ws_collect_wrapper.py.
- Исправлены проблемы запуска:
  - PowerShell Start-Process -ArgumentList теперь quote-ит approval text одним аргументом.
  - STOPPED_INCOMPLETE same-run restart использует preview_path из raw gate.
  - Partial failed artifacts архивируются в ailed_<timestamp> перед fresh restart.
  - Collector retry-ит Windows PermissionError при atomic replace manifest.json.

## Проверки
- Parser check PowerShell wrapper: OK.
- python -m py_compile trading_mvp/src/listing_event_history_collector.py trading_mvp/tests/test_listing_event_history_collector.py: OK.
- Targeted tests collector/wrapper: OK.
- Full suite: python -m unittest discover -s trading_mvp/tests -> 331 tests OK, 13 skipped.

## Visible run result
- Run id: listing_event_history_collect_20260708_210753.
- Gate: READY_FOR_POSTPROCESS.
- Decision: LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY.
- Output: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\listing-history\listing_event_history_collect_20260708_210753\ohlcv.jsonl.
- Manifest: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\listing-history\listing_event_history_collect_20260708_210753\manifest.json.
- Event plan: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\listing-history\listing_event_history_collect_20260708_210753\event_plan.json.
- Rows: 1953 OHLCV rows + 356 placeholder rows = 2309 jsonl lines.
- Requests: 360 planned/completed event-granularity requests; 432 HTTP requests.
- Errors: 216 API errors, mostly 400 for unavailable old/delisted windows.
- Archived failed partial attempt: ailed_20260708_223854 under the run directory.

## Риски и ограничения
- eplay_allowed=false, grid_allowed=false, paper_forward_allowed=false; replay/grid/live/API keys запрещены до отдельного data-quality gate.
- Большая доля placeholder/API errors: нужна data-quality диагностика по exchange/granularity/event window.
- check_active_run_gate.ps1 при RUNNING может ловить краткий Windows file lock на manifest read; run завершился успешно после retry в collector.

## Следующий шаг
Guarded listing-event history data-quality, затем normalizer, и только если quality gate выставит eplay_allowed=true - PlanOnly replay-validation. Не запускать grid/live/API keys.
