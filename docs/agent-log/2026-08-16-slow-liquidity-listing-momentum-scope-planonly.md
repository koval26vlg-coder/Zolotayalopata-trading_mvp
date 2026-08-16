# 2026-08-16 — Listing Momentum scope remapped away from v6 postprocess

Сеть не открывалась. OHLCV не открыт. Replay/evaluator/returns не считались. Closed 9 не переоткрыты.

Dashboard-описание «ACTIVE / READY_FOR_POSTPROCESS, сбор 13.08, 30 021 строк, ждёт финальный постпроцессинг» не совпадает с Listing Momentum.

## Что есть на самом деле
- v6 `slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6`: 30 021 строк, 56 дней 1h/4h, 9 баз BDX/CC/EDGE/MNT/OKB/RAIN/STETH/USDD/WEETH. Technical quality accepted. `replay_allowed=false`, `normalizer_allowed=false`, `fixed_signal_plan_allowed=false`.
- Эти 9 баз — закрытая identity-unreachable девятка. Их listed_at в календаре — 2019–2025, не «первые дни». STETH/USDD/WEETH в frozen calendar нет.
- Предыдущий `listing_event_drift_reversal`: MEXC/Gate quality rejected; Bitget quality accepted; replay `LISTING_EVENT_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE`. Retune запрещён.
- Two-venue official identity уже `CLOSED_AS_INCOMPLETE`. Identity до OHLCV остаётся.

## Calendar census (as of 2026-08-16)
- Frozen calendar sha256=`d01f86646eaebfd4df5a738a754f021bb3a7b0dcd192cfa104057eb29a3f4abb`
- Источник: public API snapshot, не official announcement
- Two-venue USDT names exclude closed 9: 407
- Event rows: 814
- First 3 days: 0
- 4–7 days: 0
- 8–30 days: 0
- 31–90 days: 1
- >90 days: 406

## Frozen
- `plan_hash=4c89ce8e9a6d1065da4f6987ebee04ae8357481a4596084239796f78197a848b`
- `plan_file_sha256=a31cc2850f4ba38443ac328f4014c62407e24fab0b106918ce9ecfa01c64b178`

## File
`docs/plans/slow-liquidity-listing-momentum-scope-planonly-20260816.json`
