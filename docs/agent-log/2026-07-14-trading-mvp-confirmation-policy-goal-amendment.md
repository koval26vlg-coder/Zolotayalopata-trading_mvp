# trading_mvp confirmation policy goal amendment

Date: 2026-07-14
Agent: Codex

## User request
Внести корректировку в цель: короткие owned no-grid OOS/evaluation/postprocess/report действия по frozen PlanOnly не должны требовать отдельного подтверждения.

## Decision
Короткий deterministic owned no-grid evaluation/OOS/postprocess/report по уже замороженному PlanOnly и существующим локальным данным больше не требует отдельной фразы `подтверждаю`, если одновременно выполнены условия:

- `active-run gate` не `RUNNING`;
- есть frozen PlanOnly artifact, expected plan hash и input Merkle hash;
- evaluator/readiness валидирован и имеет статус `*_EVALUATOR_READY_OOS_NOT_RUN`;
- запуск видимый или через visible monitor;
- `MaxRuntimeSec<=1800`;
- нет network collector, grid/search, retune, paper-forward, live orders, API keys, leverage, margin, hidden/background run или auto-chain в рискованный этап.

В этом состоянии команды `продолжи`, `продолжи цель`, `что дальше`, `погнали`, `давай дальше` являются достаточным разрешением. Цель нельзя переводить в `blocked` только из-за отсутствия отдельного подтверждения для такого короткого proof-step.

## Changed files
- `AGENTS.md`
- `docs/plans/2026-07-14-trading-mvp-current-goal.md`

## Verification
- Active-run gate checked before edits: `READY_FOR_POSTPROCESS`.
- No OOS, collector, grid, probe, paper-forward, live/API or long process was started.

## Next agent note
Current project state remains v6 PlanOnly: `FAST_FIRST_V6_PLAN_FROZEN`. Next engineering step is still to implement/test the hash-bound no-grid v6 evaluator. After evaluator readiness, the visible owned no-grid v6 OOS can be run without asking for a separate confirmation if all policy conditions above hold.
