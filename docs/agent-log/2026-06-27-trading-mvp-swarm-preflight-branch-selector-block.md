# trading_mvp swarm preflight branch-selector block checkpoint

Дата: 2026-06-27 14:20 +03:00
Агент: Codex
Запрос пользователя: использовать Рой и возобновить цель trading_mvp без запуска лишних прогонов.

## Цель
Подтвердить через Рой и локальные проверки, что после блокировки 7d funding dataset по качеству данных нет stale funding next-action leakage в текущем proof pipeline, и что следующий шаг остается research-only visible WS collect только после явного подтверждения пользователя.

## Что сделано
- Проверен active run gate: `READY_FOR_POSTPROCESS` только формально; funding postprocess заблокирован guard review по `data_quality:min_min_rows_per_cycle`, `min_rows_per_cycle=9`; rank/backtest/paper-forward на этом dataset запрещены.
- Усилен preflight: `tools/trading_edge_preflight.ps1` теперь проверяет наличие funding-block override markers в `tools/trading_branch_selector.ps1` без рекурсивного запуска branch selector.
- Усилен test coverage: `trading_mvp/tests/test_visible_ws_collect_wrapper.py` проверяет preflight marker и runtime branch selector regression.
- Запущен и завершен Aion Agent Swarm workflow: `2026-06-27-141101-415397-trading-mvp-preflight-branch-selector-funding-block-checkpoint`.
- Рой прошел L1/L2 Antigravity, L3/L4 Codex, L5 Claude Code; итоговое решение: `approve`.

## Проверки
- `python -m unittest discover -s trading_mvp/tests` -> 205 tests OK.
- `trading_edge_preflight.ps1 -Json` -> `ok=true`, `status=READY_FOR_EDGE_PROOF_STEP`, `branch_selector_funding_block_override=pass`.
- `start_ws_collect_visible.ps1 -Hours 6 -PlanOnly` -> `would_start=false`, `requires_confirmed_long_run=true`; фактический долгий запуск не стартовал.
- Workflow final status -> `state=done`, final agent `Claude Code`, risk gate passed.

## Вывод Роя
- Funding dataset `funding_collect_7d_spotliq_visible_20260617_185732` не использовать для rank/backtest/paper-forward.
- Блокировка funding dataset подлинная: `min_rows_per_cycle=9` против требуемых 20.
- Branch selector корректно архивирует старый scorecard action в `original_scorecard_next_action`, но current funding action переводит в blocked path.
- WS collect является корректным следующим research-only data step, но только через видимый запуск и `-ConfirmedLongRun` после предметного подтверждения пользователя.
- Результат WS collect не является приемкой стратегии; далее нужны guarded postprocess, replay validation, OOS/walk-forward/stress/economics.

## Риски
- Сырой `active-run-gate.json` еще содержит старый `next_step_after_ready` про funding final-review, но `check_active_run_gate.ps1` переопределяет effective next step, а final-review wrapper уже отказывается создавать artifacts. Это управляемый не-блокер.
- Прямые funding wrappers можно позже усилить self-refuse guard, но это не должно блокировать WS branch.
- Нельзя запускать live orders, API keys, leverage/margin или выдавать инвестсовет.

## Следующий шаг
Показать пользователю точную команду visible 6h WS collect и ждать явного подтверждения. Без подтверждения не запускать:
`pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1 -Hours 6 -ConfirmedLongRun`
