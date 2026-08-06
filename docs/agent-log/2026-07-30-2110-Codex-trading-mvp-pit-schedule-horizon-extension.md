# Trading MVP PIT schedule horizon extension

- Дата: 2026-07-30 21:09:59 +03:00
- Агент: Codex
- Цель: не допустить календарного простоя PIT shadow-track до train gate 20 distinct dates.

## Вывод

Текущий approved schedule `31b4b6c7...` сам по себе больше не может
достичь train gate:

- accepted distinct dates: 4;
- два окна 29 и 30 июля истекли без accepted certification;
- оставшиеся reachable dates: 12;
- максимум по текущему schedule: 16 из 20;
- подтверждённый дефицит: 4 даты.

Наблюдаемая technical-quality acceptance rate равна 4/5, поэтому PlanOnly
продление содержит 5 дополнительных 20-минутных окон: четыре обязательных и
одно quality-retry окно. Collection-stage guard остановит дальнейшие сегменты,
как только будет достигнуто 20 accepted distinct dates.

## Артефакты

- Horizon audit:
  `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\pit-universe-v2-schedule-horizon-audit-31b4b6c7-v1.json`
- Audit SHA256:
  `81531a36caba9f30f1d8aacb76d35ba0bdd32699a7556dbe9d3eb16073382fac`
- Extension PlanOnly:
  `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_extension_planonly_20260812_from_31b4b6c7_v1.json`
- Extension plan hash:
  `a0b79dbdb9a6ebe5843e118b7e69465eb6a998708eb429b42117379ade7fa491`
- Extension file SHA256:
  `58f84c63d83da30ada0491d7bdd7c51e7202b7d090ab666a0fcb3cc2664b6297`
- Proposed dates: 2026-08-12 through 2026-08-16 at 01:00-01:20 +03:00.

## Control plane

- Proposal добавлен в autopilot policy как inactive candidate.
- `schedule_approved=false`, `automatic_launch_allowed=false`.
- Guard проверяет audit/plan SHA и не запрашивает разрешение до
  2026-08-10 19:00 +03:00.
- Перед запросом разрешения horizon должен быть пересчитан в новые immutable
  versioned paths.
- Heartbeat обновлён для one-shot exact schedule approval.

## Проверки и безопасность

- Extension plan validation: `VALID`.
- Targeted regression: 57 tests PASS.
- Guard: `ACTIVE`, `stop_new_actions=false`.
- Writer count: 0.
- Network, returns/PnL/OOS, signals, grid/retune, paper-forward, live,
  private API keys, leverage и margin не использовались.
