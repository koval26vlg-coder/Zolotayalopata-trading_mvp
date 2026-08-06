# trading_mvp replay-validation PlanOnly NoGrid

Дата: 2026-07-08
Агент: Codex

## Запрос
Следующий проектный шаг: visible replay-validation PlanOnly, без grid/live/API keys.

## Сделано
- Проверен active-run gate: READY_FOR_POSTPROCESS, next_goal_decision был READY_FOR_REPLAY_VALIDATION_PLANONLY.
- Исправлен `tools/run_ws_replay_validation_visible.ps1`:
  - market-filter postprocess mode допускается как входной artifact;
  - большие normalized-файлы не хэшируются полностью в PlanOnly, фиксируются size/mtime/path и `sha256_skipped=file_too_large`;
  - `-SkipWsGrid` теперь реально убирает `ws_grid` из outputs/commands и автоматически отключает зависимый `sweep_gate`.
- Обновлен regression-тест `trading_mvp/tests/test_visible_ws_collect_wrapper.py`.
- Запущен visible PlanOnly NoGrid в отдельном PowerShell-окне.

## Проверки
- `python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_ws_market_filter` через bundled Python: 21 OK, skipped=3.
- Финальный PlanOnly artifact: `exports/trading-mvp/backtests/ws_replay_validation_plan_ws_durable_72h_2exchange_pregap_planonly_nogrid_20260708_132712.json`.
- PlanOnly result: `ok=true`, `would_run=false`, `replay_allowed=true`, `ws_grid=null`, `sweep_gate=null`.
- Data quality in plan: 51,278,447 rows, 2 exchanges, 32 markets, 47.89h, max_gap_sec=215.22.

## Ограничения
- Никакой replay/grid/live/API key не запускался.
- Следующий шаг требует отдельного подтверждения пользователя: visible confirmed replay-validation без grid/live/API keys.
