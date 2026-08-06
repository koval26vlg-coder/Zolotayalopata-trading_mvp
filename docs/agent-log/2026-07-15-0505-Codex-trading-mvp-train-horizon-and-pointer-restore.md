# trading_mvp train horizon and approval pointer restore

Дата: 2026-07-15 05:05 Europe/Volgograd.

## Исходный запрос

Продолжить каноническую цель trading_mvp до следующего доказательного checkpoint, не запуская бесполезный повтор данных на уже принятую дату.

## Найденные разрывы

- Append-only quality ledger содержит `2/20` distinct accepted train dates: `2026-07-14` и `2026-07-15`.
- Текущий утвержденный schedule `34363aef...` покрывает только `2026-07-14..2026-07-27`, то есть максимум `14/20` distinct dates даже при принятии всех оставшихся сегментов.
- После supplemental 3h run active gate сохранил его plan hash `155d211c...`, тогда как heartbeat обслуживает основной schedule `34363aef...`. Без восстановления следующий полезный n03 был бы отклонен visible wrapper из-за несовпадения approval pointer.

## Выполнено

- Создан immutable extension PlanOnly на недостающий календарный горизонт `2026-07-28..2026-08-02`, 6 сегментов по 20 минут:
  - path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_extension_planonly_20260715_0448.json`;
  - plan hash: `d35b65a7415cb37e0fcf6216abc77a204640ba749e19617c355ec43e93570583`;
  - file SHA-256: `edea8e1112e807a4f7203362ee545f70c8c7c795d1d6e22348a446f32b52edfd`;
  - status: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`; collection/network/OOS не запускались.
- Создан coverage bridge `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_bridge_planonly_20260715_0451.json`, SHA-256 `61e7c3694d53319803a572ae56c043e6d04e1ae4f3e207bc1fb4f4bc2b15b1f9`.
- Bridge decision: `TRAIN_ACCRUAL_HORIZON_COVERED_CONDITIONALLY`: `2/20` сейчас, `14/20` после активного schedule и `20/20` после extension при quality acceptance каждой будущей даты.
- Добавлен `tools/restore_trading_night_schedule_pointer.ps1`. Он fail-closed проверяет plan seal, immutable approval, срок, run_id, stage authorization и неизменность gate/approval перед атомарным восстановлением pointer.
- Active gate восстановлен на существующий пользовательский approval schedule `34363aef...` для следующего полезного `pit_universe_v2_forward_20260716_n03`; текущий завершенный run id сохранен.
- Restore audit: `docs/agent-log/2026-07-15-0458-pit-night-schedule-pointer-restore.json`, SHA-256 `4dd1fcfff57597c72262afc92a2ecdcd7d811c2991d73b24b1b5d3d1be41835d`.
- Immutable approval SHA-256 остался `e0d8fffa881056927209ebba904387215e4d315bcf6d7a929860019d804676a4`.
- Heartbeat `pit-visible-night-segments` обновлен: при pointer mismatch после completed supplemental run он использует только restore-инструмент и существующий immutable approval; новое approval не создается.

## Проверки

- Новый TDD shard pointer restore: `3 OK`.
- Schedule/gate shard: `66 OK`.
- Полный regression: `675 OK`, `5 skipped`.
- PowerShell parse и `git diff --check` прошли.
- Исправлена изоляция `test_night_schedule_plan.py`: fixtures больше не читают реальный ledger на `E:`.

## Следующая граница

- Плановый n02 от `2026-07-15` остается штатным duplicate-date skip.
- Следующий полезный market-writing segment: `pit_universe_v2_forward_20260716_n03`, окно `2026-07-16 23:00..23:20 +03:00`, по уже существующему approval.
- Extension `d35b65a7...` не утверждать сейчас: его раннее approval заменило бы активный schedule. Отдельное явное approval допустимо только после завершения текущего schedule и до первого окна `2026-07-28 23:00`.
- До `20/20` train feasibility и OOS остаются закрыты. Returns, signals и PnL не читались; grid/probe/paper/live/API keys не запускались.

