# 2026-07-14 - Codex - trading_mvp consent policy update

## Исходный запрос

Пользователь попросил внести корректировку в цель: для действий уровня короткого visible owned OOS не требовать отдельного подтверждения каждый раз.

## Что изменено

- В локальный `AGENTS.md` добавлено узкое исключение для `trading_mvp`.
- В `D:\AionUi-Paperclip\AGENTS.md` добавлено такое же исключение для общей памяти агентов.
- В канонический план `docs/plans/2026-07-14-trading-mvp-current-goal.md` добавлено правило runtime/consent.
- В Aion `current-context`, `tasks` и `decisions` зафиксировано новое правило.

## Новое правило

Короткий deterministic owned no-grid evaluation/OOS/postprocess на уже замороженном PlanOnly и существующих локальных данных не требует отдельной фразы-подтверждения, если:

- `active-run gate` не `RUNNING`;
- запуск видимый;
- `MaxRuntimeSec<=1800`;
- нет network collector;
- нет grid, retune, paper-forward, live orders, API keys, leverage или margin.

Команды `продолжи`, `продолжи цель`, `что дальше` или `погнали` в таком состоянии считаются достаточным разрешением.

## Что не изменилось

Collectors, grid-search, paper-forward, live/API keys, leverage/margin, hidden/background runs, ночные запуски и любые runs дольше 1800 секунд всё еще требуют отдельного явного подтверждения.
