# Fast-First v4 PlanOnly

## Дата и время

2026-07-14 12:38 Europe/Volgograd

## Агент

Codex

## Исходный запрос пользователя

Продолжить доказательный цикл `trading_mvp Fast-First v4` с frozen-кандидатом
`venue_local_funding_pressure_reversal_v1`, без grid/retune и без запуска OOS до
готовности hash-bound evaluator.

## План

1. Проверить active-run gate и канонический PlanOnly.
2. Подтвердить seal, coverage, runtime policy и отсутствие OOS/PnL access.
3. Добавить append-only provenance reconciliation.
4. Выполнить targeted и fast regression tests.

## Что сделано

- Канонический PlanOnly:
  `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\plans\fast_first_funding_pressure_reversal_planonly_night_policy_20260714_121647.json`.
- Plan hash: `5396885aa9abf77a461f20aa190c843b86be098b76abd6f3a5655a8f725eee60`.
- File SHA-256: `6da5792f6ff75cfef49bd3ad9ff97acc7ebac7eaafece081ba3f5799d18cc490`.
- Input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`.
- Goal SHA-256: `627a3a2fdd33d723cfdb8e302115193190605d39f9449491b1758a9148e0d45b`.
- Seal подтвержден для 195 файлов; missing files: 0.
- Coverage: 97 markets, MEXC 43 (40 с минимум 60 closed daily bars), Gate 54
  (51 с минимум 60 bars).
- `oos_metrics={}`, `observed_performance={}`, `evaluation_allowed=false`;
  funding rates, prices/volumes, signal scores и PnL для performance не читались.
- Runtime policy: daytime `<=10800s`; candidate-specific night window
  `23:00-07:00 Europe/Volgograd` `<=28800s`, только visible/owned и с точными
  duration/deadline/stop conditions. Night exception не разрешает grid, retune,
  hidden execution, live, API keys, leverage или margin.
- Append-only ledger reconciliation:
  `exp_20260714_092119_a8d0043610c0`. Предыдущая запись
  `exp_20260714_085202_0e573c896df3` сохранена и superseded только по runtime
  scheduling policy; signal/economics/split/folds/gates не изменялись.
- Gate: `READY_FOR_POSTPROCESS`, decision `FAST_FIRST_V4_PLAN_FROZEN`, errors 0.

## Измененные файлы

- `trading_mvp/src/funding_pressure_reversal.py`
- `trading_mvp/tests/test_funding_pressure_reversal.py`
- `trading_mvp/src/experiments.py`
- `trading_mvp/tests/test_experiments.py`
- `tools/build_fast_first_v4_planonly.ps1`
- `docs/plans/2026-07-14-trading-mvp-current-goal.md`
- `docs/agent-log/active-run-gate.json`
- append-only experiment ledger на `E:`

## Проверки

- Canonical validator: `valid=true`, `evaluation_allowed=false`.
- Targeted: 14 tests passed.
- Fast regression shard: 175 tests passed.
- Manifest final: 1/1 cycle, output complete, errors 0.

## Риски и ограничения

- Это не результат стратегии: OOS, walk-forward, stress и economics еще не
  вычислялись.
- Current-universe survivorship остается ограничением; максимальный исторический
  verdict только `ACCEPT_FOR_SHORT_EXECUTION_PROBE`.
- OOS нельзя запускать до готового evaluator/readiness и отдельного явного
  разрешения на visible owned run.

## Что должен проверить следующий агент

Реализовать hash-bound deterministic no-grid evaluator через TDD. До этого не
запускать OOS, execution probe, paper-forward, live orders или API keys.
