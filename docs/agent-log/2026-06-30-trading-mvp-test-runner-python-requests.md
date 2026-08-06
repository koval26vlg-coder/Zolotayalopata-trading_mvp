# trading_mvp test runner Python requests guard

- Время: 2026-06-30 16:07:37 +03:00
- Агент: Codex
- Исходный запрос пользователя: продолжить цель trading_mvp без запуска нового рыночного прогона.
- План: закрыть проблему тестового runtime, из-за которой bundled Codex Python не имел equests, и зафиксировать безопасную команду тестов в guard/status цепочке.

## Что сделано
- Добавлен 	ools/run_trading_tests.ps1.
- Runner выбирает первый Python runtime с установленным equests.
- Приоритет кандидатов: TRADING_MVP_PYTHON, C:\Program Files\Python313\python.exe, C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe, bundled Codex Python, python.exe из PATH.
- Bundled Codex Python явно детектируется как непригодный для full suite, потому что в нем нет equests.
- 	ools/trading_edge_preflight.ps1 теперь проверяет наличие runner-а и его ключевых markers.
- 	ools/trading_goal_status.ps1 и 	ools/trading_next_goal_step.ps1 теперь показывают команды un_trading_tests.ps1.
- Добавлены regression tests в 	rading_mvp/tests/test_visible_ws_collect_wrapper.py.

## Проверки
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1 -PlanOnly -Json: PASS; selected_python=C:\Program Files\Python313\python.exe, requests=2.32.3.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_edge_preflight.ps1 -Json: PASS; status=READY_FOR_EDGE_PROOF_STEP, fail_count=0, warn_count=0, check 	rading_test_runner=pass.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_goal_status.ps1 -Json: PASS; exposes 	rading_test_runner_command and 	rading_test_full_command.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_next_goal_step.ps1 -Json: PASS; exposes 	rading_test_runner_plan and 	rading_test_full.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1 -TestPath trading_mvp/tests -Pattern test_visible_ws_collect_wrapper.py: PASS; 16 tests OK, skipped=1.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1: PASS; 222 tests OK, skipped=1.

## Gate / ограничения
- Active run gate после работ: READY_FOR_POSTPROCESS, run_id=ws_postprocess_ws_collect_20260630_024437_retry_20260630_1123.
- eplay_allowed=false; replay/grid/postprocess на старом artifact запрещены.
- Новый long WS collect не запускался.
- Следующий рыночный шаг требует явного START72H и видимого запуска.
- Live orders/API keys/leverage/margin не используются.

## Риски
- git недоступен в текущем PowerShell PATH, поэтому git status не проверен.
- Aion memory heartbeat stale; контекст взят через bootstrap/context-pack, лог продублирован вручную.

## Следующий агент
- Перед любым шагом снова запустить 	ools/check_active_run_gate.ps1.
- Для тестов использовать pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1, а не bundled Python напрямую.
- Не запускать market run без явного START72H.
