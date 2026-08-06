# trading_mvp Fast-First v5 PlanOnly

## Дата и время
2026-07-14 14:10 Europe/Volgograd

## Агент
Codex

## Исходный запрос пользователя
Продолжить цель после корректировки, что короткие deterministic owned no-grid проверки на frozen local data не требуют отдельного подтверждения.

## Контекст перед началом
Active-run gate был `READY_FOR_POSTPROCESS` после v4 OOS `fast_first_v4_funding_pressure_reversal_oos_20260714_132100`. V4 получила `INSUFFICIENT_DATA` и отрицательную price-only экономику; retune/probe/paper/live запрещены. Следующий разрешенный маршрут: новая независимая Fast-First hypothesis PlanOnly.

## План
1. Проверить gate и Aion bootstrap.
2. Создать новую независимую PlanOnly-гипотезу без OOS/grid/collector/live.
3. Добавить unit tests.
4. Собрать immutable PlanOnly artifact и обновить gate/docs.

## Что сделано
- Добавлен модуль `trading_mvp/src/wick_rejection_reversal.py`.
- Добавлен wrapper `tools/build_fast_first_v5_planonly.ps1`.
- Добавлены tests `trading_mvp/tests/test_wick_rejection_reversal.py`.
- Заморожена новая гипотеза `venue_local_wick_rejection_reversal_v1`.
- Artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\plans\fast_first_wick_rejection_reversal_planonly_20260714_140353.json`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\manifests\fast_first_v5_wick_rejection_planonly_20260714_140353.manifest.json`.
- Gate/current-run обновлены на `FAST_FIRST_V5_PLAN_FROZEN`.

## Измененные файлы
- `trading_mvp/src/wick_rejection_reversal.py`
- `trading_mvp/tests/test_wick_rejection_reversal.py`
- `tools/build_fast_first_v5_planonly.ps1`
- `docs/plans/2026-07-14-trading-mvp-current-goal.md`
- `docs/agent-log/active-run-gate.json`
- `docs/agent-log/current-run.json`
- `docs/agent-log/fast_first_v5_wick_rejection_planonly_20260714_140353.launch.json`

## Проверки
- `python -m unittest trading_mvp.tests.test_wick_rejection_reversal` -> `Ran 5 tests ... OK`.
- `python -m unittest discover -s trading_mvp/tests` -> `Ran 574 tests ... OK (skipped=5)`.
- `tools/check_active_run_gate.ps1` -> `READY_FOR_POSTPROCESS`, `run_id=fast_first_v5_wick_rejection_planonly_20260714_140353`, `evaluation_allowed=false`, `replay_allowed=false`.

## Решения
- Активная новая ветка: `venue_local_wick_rejection_reversal_v1`.
- V5 использует daily wick/rejection reversal внутри venue и не использует funding/carry, cross-venue, HFT/orderbook, listing-event, slow-liquidity, residual dispersion или MAX20.
- OOS не запускался; следующий шаг только hash-bound no-grid evaluator + readiness.

## Риски и ограничения
- PlanOnly не доказывает edge и не содержит OOS/PNL метрик.
- Нельзя запускать replay/grid/probe/paper/live/API keys до прохождения evaluator readiness и последующего short no-grid OOS.
- Рабочее дерево содержит много старых unrelated dirty/untracked файлов; они не трогались.

## Что должен проверить следующий агент
- Реализовать deterministic hash-bound no-grid evaluator для v5.
- Добавить tests на causal OHLC usage, next-open/next-close execution, costs, split/folds, verdict ordering и deterministic repeat hash.
- До OOS получить readiness artifact: input hashes match, OOS not read, grid=false, parameter combinations=1.
