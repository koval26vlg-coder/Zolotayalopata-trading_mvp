# trading_mvp funding final-review self-refuse hardening

Дата: 2026-06-27 14:24 +03:00
Агент: Codex
Исходный контекст: продолжение active goal `trading_mvp`; Рой до этого завершил checkpoint `2026-06-27-141101-415397-trading-mvp-preflight-branch-selector-funding-block-checkpoint` с `approve`.

## Цель шага
Закрыть остаточный риск из L5: прямой запуск funding final-review/rank/backtest на dataset, который уже заблокирован guard review по `data_quality:min_min_rows_per_cycle`.

## Что изменено
- `tools/run_funding_final_review_visible.ps1`
  - добавлен switch `-AllowBlockedFundingDataset` для явной guard/debug регенерации;
  - по умолчанию wrapper проверяет `check_active_run_gate.ps1 -Json`;
  - если текущий input/manifest совпадает с dataset в `postprocess_block`, wrapper падает до запуска runner и не создает rank/backtest/paper-forward artifacts;
  - сообщение отказа указывает `min_rows_per_cycle` и переводит оператора к `tools/trading_next_goal_step.ps1` / guarded WS proof path.
- `tools/trading_edge_preflight.ps1`
  - добавлен check `final_review_blocked_dataset_self_refuse`.
- `trading_mvp/tests/test_visible_ws_collect_wrapper.py`
  - добавлен runtime regression: прямой `run_funding_final_review_visible.ps1 -NoPause` на текущем blocked funding dataset должен завершаться ошибкой с self-refuse текстом;
  - preflight должен видеть `final_review_blocked_dataset_self_refuse=pass`.

## Проверки
- `python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper` -> 6 tests OK.
- `python -m unittest discover -s trading_mvp/tests` -> 206 tests OK.
- `trading_edge_preflight.ps1 -Json` -> `ok=true`, `status=READY_FOR_EDGE_PROOF_STEP`, `final_review_blocked_dataset_self_refuse=pass`, `branch_selector_funding_block_override=pass`.
- `run_funding_final_review_visible.ps1 -NoPause` -> expected failure: `Funding dataset is blocked by guard review (... min_rows_per_cycle=9). Refusing funding final-review/rank/backtest/paper-forward...`.
- `trading_next_goal_step.ps1 -Json` -> primary command remains visible WS `-PlanOnly`; after explicit approval command is `start_ws_collect_visible.ps1 -Hours 6 -ConfirmedLongRun`.
- `start_ws_collect_visible.ps1 -Hours 6 -PlanOnly` -> `would_start=false`, `requires_confirmed_long_run=true`.

## Риски и ограничения
- Долгий WS collect не запускался; для старта требуется явное подтверждение пользователя.
- Funding dataset `funding_collect_7d_spotliq_visible_20260617_185732` остается заблокированным для rank/backtest/paper-forward.
- Research-only: no live orders, no API keys, no leverage/margin, no investment advice.
- `git` в shell недоступен; состояние зафиксировано через readback и tests.

## Следующий шаг
Показать пользователю точную команду visible 6h WS collect и ждать явного подтверждения:
`pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_visible.ps1 -Hours 6 -ConfirmedLongRun`
