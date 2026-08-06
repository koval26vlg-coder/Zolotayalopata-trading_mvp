# 2026-07-14 - Codex - trading_mvp confirmation policy correction

## Исходный запрос
Пользователь указал: внести корректировку в цель, что короткие действия вроде owned OOS/evaluation не нужно подтверждать отдельно.

## Что сделано
- Обновлен канонический документ цели `docs/plans/2026-07-14-trading-mvp-current-goal.md`.
- Добавлен раздел `Confirmation policy correction`.
- Обновлены `docs/agent-log/active-run-gate.json` и `docs/agent-log/current-run.json`.
- Текущее состояние зафиксировано как `FAST_FIRST_V5_EVALUATOR_READY_OOS_NOT_RUN`.
- `evaluation_allowed=true` только для короткого visible deterministic owned no-grid OOS/evaluation/postprocess/report на frozen PlanOnly и существующих локальных данных.

## Новое правило
Отдельное подтверждение пользователя не требуется, если одновременно выполнено:
- active-run gate не `RUNNING`;
- frozen PlanOnly + expected plan hash + input Merkle уже есть;
- evaluator/readiness валидирован;
- запуск видимый;
- `MaxRuntimeSec<=1800`;
- нет collector, public/execution probe, grid, retune, paper-forward, live orders, API keys, leverage/margin, hidden/background или run >1800 sec.

В этом состоянии `продолжи`, `продолжи цель`, `что дальше`, `погнали`, `давай дальше` достаточно для следующего short proof-step.

## Что все еще требует отдельного подтверждения
Collectors, public probes, execution probes, grid/search, retune, paper-forward, long/night runs, hidden/background runs, live/API keys, leverage/margin, и любые запуски дольше 1800 секунд.

## Проверки
- Aion memory bootstrap выполнен.
- Active-run gate проверен перед изменениями: `READY_FOR_POSTPROCESS`.
- JSON gate/current-run обновлены без запуска OOS, collector, grid, paper или live-действий.

## Следующий шаг
Продолжать v5 proof pipeline: подготовить/использовать visible owned no-grid OOS evaluation wrapper. Отдельная фраза `подтверждаю` для этого short-step больше не нужна при соблюдении условий выше.
