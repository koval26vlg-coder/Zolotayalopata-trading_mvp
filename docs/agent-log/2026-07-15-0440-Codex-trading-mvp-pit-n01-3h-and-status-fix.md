# trading_mvp PIT n01 3h and status fix

Дата: 2026-07-15 04:40 Europe/Volgograd.

## Результат сегмента

- Видимый supplemental run `pit_universe_v2_forward_20260715_n01` завершен по `duration_sec=10800`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\pit_universe_v2_forward_20260715_n01\manifest.json`.
- Получено `36/36` cycles, `61,092` rows, `0` API/cycle errors и `0` MEXC depth errors.
- MEXC и Gate присутствовали во всех cycles; MEXC L1 depth coverage равен `1.0`.
- Hash-bound quality decision: `PARTIAL_PIT_QUALITY_CERTIFIED`; segment accepted без rejection reasons.
- Quality report: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\pit_universe_v2_quality_report_20260715_n01.json`.
- Certification id: `a2edc63bca8ee8efab732be8c2c54ce01384aafdc415fb77d00ac373c4b3ae42`.
- Append-only ledger теперь содержит `2/20` distinct accepted train dates: `2026-07-14` и `2026-07-15`.
- Returns, signals, PnL и OOS не читались; replay/grid/probe/paper/live/API keys не запускались.

## Исправление статуса

- Устранена ошибка `tools/check_active_run_gate.ps1`: PIT progress/ETA больше не берутся из stale gate полей `total_cycles=2` и `actual_duration_sec=13.266`.
- Checker использует manifest-native `duration_sec`, `interval_sec`, `elapsed_active_sec` и `cycle_count`.
- Реальный status теперь корректно показывает `36/36`, remaining `0`, requested duration `10800`, actual duration `10800.0735`.
- Добавлен regression test `test_pit_gate_infers_progress_from_manifest_duration_and_interval`.
- Verification: `test_active_run_gate` 14 OK; совместный PowerShell tooling shard 33 OK.

## Следующая граница

- Запуск планового `pit_universe_v2_forward_20260715_n02` fail-closed заблокирован: дата `2026-07-15` уже quality accepted.
- Heartbeat `pit-visible-night-segments` обновлен: duplicate certified date получает `SKIP_DUPLICATE_CERTIFIED_DATE`, терминал и collector не запускаются.
- Следующая полезная distinct train-дата по утвержденному schedule: `pit_universe_v2_forward_20260716_n03`, окно `2026-07-16 23:00..23:20 +03:00`.
- До `20/20` разрешено только train accrual/status/quality certification. Train feasibility, OOS и дальнейшие proof stages остаются закрыты.

