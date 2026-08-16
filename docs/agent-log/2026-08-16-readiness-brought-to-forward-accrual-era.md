# 2026-08-16 — readiness-цепочка переведена в эпоху forward-accrual

Задача: привести readiness и autopilot state в соответствие с фактическим
состоянием после сегодняшних изменений. Выполнено расширением state-machine
(а не обходом): старая identity-цепочка сохранена без изменений.

## Что сделано

1. Guard переработал состояние сам: stale TERMINAL_REJECT v4 сменился на
   `REFRESH_CURRENT_SPRINT_READINESS` (gate чистый, claims нет).
2. Генератор упирался в старый мир («await official identity», decision
   строки, identity flags) — расширен листовым статусом
   `SLOW_LIQUIDITY_LISTING_MOMENTUM_FORWARD_ACCRUAL_STANDING_RESEARCH`:
   - билдер собирает отчёт из фактических артефактов: identity acceptance
     receipt, оба replay-вердикта (REJECTED_NO_ROBUST_EDGE), forward
     monitor/evaluator планы, forward state (tick/window счётчики)
   - резолвер валидирует все хэши заново + gate READY + отсутствие claim
   - активация ветки ограничена gate.next_goal_decision из новой эры
     (синтетические тесты старой цепочки не перехватываются)
3. Readiness v22 записан, pointer обновлён:
   `readiness_hash=4c0e4007540beb59a8330dabb995a1b7fd8f2e6380e6a7825accb1d7de2b7766`
4. Guard итог: **ACTIVE**, `stop_new_actions=false`, readiness READY,
   `next_action=wait_forward_sample_and_run_scheduled_ticks_no_peeking_below_30`
5. Тесты: 35 passed (readiness + autopilot guard), включая старую цепочку.
6. Попутно закоммичены незакоммиченные planonly-артефакты и launchers
   прошлых сессий (docs/plans/*, tools/*) — provenance доли из более
   ранней очистки закрыт.

Замечания:
- guard decision остаётся `AWAIT_EXACT_ONE_WEEK_EDGE_SPRINT_APPROVAL_CHECKPOINT`
  (маппинг WAITING-семантики для accrual-статуса — кандидат на уточнение);
  операционно некритично: stop_new_actions=false, next_action корректен,
  forward-scheduler от guard не зависит
- в v21 была расхождение в 1 hex slow-plan sha (03d3b vs фактический
  0373b) — v22 собирается от фактических файлов
- недельный остаток бюджета ~21% (порог 15%)

## Коммиты
- «Extend readiness machine with forward accrual era»
- «Commit prior-session planonly artifacts and launchers»
