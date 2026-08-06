# trading_mvp collect approval contract guard

Дата: 2026-06-30 14:47:02 +03:00
Агент: Codex
Запрос пользователя: продолжить цель после rejected WS postprocess без запуска долгого collect.

## План
- Проверить Aion memory bootstrap и active-run gate.
- Не запускать collect/replay/grid, пока нет явного START72H.
- Добавить reusable approval-contract verifier для согласованности gate/next-goal/goal-status/branch/readiness.
- Проверить targeted tests и preflight.

## Что сделано
- Добавлен 	ools/trading_collect_approval_contract.ps1.
- В 	ools/trading_edge_preflight.ps1 добавлен статический check collect_approval_contract_verifier и JSON-команда collect_approval_contract_command.
- В 	rading_mvp/tests/test_visible_ws_collect_wrapper.py добавлены проверки approval contract и preflight readback.

## Проверки
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_collect_approval_contract.ps1 -Json: ok=true, status=APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT, fail_count=0, warn_count=0.
- python -m unittest ...test_collect_approval_contract... ...test_preflight_locks...: 2 tests OK using bundled Python.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_edge_preflight.ps1 -Json: ok=true, READY_FOR_EDGE_PROOF_STEP, fail_count=0, warn_count=0.
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: 14 tests, OK, skipped=1 using bundled Python.

## Текущий статус цели
- Gate status: READY_FOR_POSTPROCESS.
- Current WS postprocess remains rejected: replay_allowed=false / min_duration_ratio.
- Replay/grid on this artifact remain blocked.
- Next real proof step remains visible 72h dense WS collect only after explicit user approval phrase START72H.
- No live orders, API keys, leverage or margin.

## Риски и ограничения
- Full python -m unittest discover -s trading_mvp/tests was not rerun in this turn because previous full run timed out and this change touched only visible collect/preflight contract tests.
- Aion memory watcher heartbeat was stale/locked during bootstrap, so this checkpoint is written manually to both logs.

## Следующий агент должен проверить
- Before any next goal work: run 	ools/check_active_run_gate.ps1.
- If user explicitly says START72H, run the guarded visible shortcut/command only in a visible terminal.
- If no START72H, continue only short guard/readiness work.
