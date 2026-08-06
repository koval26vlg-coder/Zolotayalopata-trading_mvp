# PIT night schedule immutable reseal

Дата: 2026-07-16 08:30 +03:00

Статус: `AWAIT_PRIMARY_EXPLICIT_APPROVAL`

## Причина

Утвержденный plan `34363aef...` стал невалидным после изменения полного файла hypothesis bank. Целевой hypothesis contract не менялся, но exact approved wrapper обязан fail-closed проверять полный source hash. Старый approval record сохранен без изменений и не переиспользован.

## Выполнено

- Active gate проверен: `READY_FOR_POSTPROCESS`, активных collectors нет.
- Returns, PnL, signals и market rows не читались.
- В quality ledger подтверждены 2 разные даты: `2026-07-14`, `2026-07-15`.
- Созданы read-only snapshots текущего hypothesis bank и canonical goal.
- Создан новый primary PlanOnly на 14 непересекающихся дат: `2026-07-16..2026-07-29`.
- Создан unapproved extension PlanOnly на 4 даты: `2026-07-30..2026-08-02`.
- Combined coverage: `2 accepted + 14 primary + 4 extension = 20` train dates при условии quality acceptance каждой новой даты.
- Оба плана проходят strict source/runtime/hash validation.
- Первый primary segment возвращает технический verdict `AUTHORIZED`, но collector не запускается без approval record.

## Артефакты

- Primary: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_reseal_primary_immutable_sources_planonly_20260716_082454.json`
- Primary plan hash: `14f687e8e8491bb58c1e697d9a467d89ab360f6b683782caca43f8b33a0684a0`
- Extension: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_reseal_extension_immutable_sources_planonly_20260716_082454.json`
- Extension plan hash: `bba084f7a81dd4c19abab108ab18e1b0cfe33e968d4269c9d55b1f8b14cd84e4`
- Bridge: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_reseal_bridge_planonly_20260716_082454.json`
- Bridge SHA-256: `8149f88e17864fe134d25c557f69cf722bbe456eae0aca4102196152fd74af15`
- Source snapshot manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\source-snapshots\pit_train_reseal_20260716_082454\source_snapshot_manifest.json`

Первые планы, созданные с mutable source paths в том же checkpoint, считать diagnostic/superseded. Canonical являются только файлы с `immutable_sources` в имени.

## Следующий разрешенный шаг

Требуется approval только primary плана:

```text
Подтверждаю ночное расписание trading_mvp plan_hash=14f687e8e8491bb58c1e697d9a467d89ab360f6b683782caca43f8b33a0684a0 на 2026-07-16T23:00:00+03:00..2026-07-29T23:20:00+03:00, data_type=PIT_UNIVERSE_V2_FORWARD, stage=train_accrual, visible terminal, без grid/live/API keys.
```

Extension остается неутвержденным до исчерпания primary либо до пересчета фактически принятых дат. Automation не создавалась. Collector, feasibility и OOS не запускались.
