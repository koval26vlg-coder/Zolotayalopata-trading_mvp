# 2026-08-16 — спот-тикер identity принята пользователем, v6 разблокирован

Пользователь принял контракт спот-тикер identity (вариант 1 из
предложенных, аналог решения по proxy-датам листинга):

- фраза: «Принять спот-тикер identity (аналог proxy-дат) — разблокирует
  fixed-signal → replay исходной slow-liquidity гипотезы на готовых
  данных;»
- план `slow_liquidity_spot_ticker_identity_acceptance_20260816`
- `plan_hash=47d6ddaa0d50a6b1572056141e966994e313d7c6bc169e13153ca17742e0ad33`
- `plan_file_sha256=321f07af…` (полный в плане)
- receipt `SPOT_TICKER_IDENTITY_ACCEPTED`
  (`receipt_hash=4df0ff0d…`, файл `2026-08-16-slow-liquidity-spot-ticker-identity-acceptance-approval.json`)

## Правило identity

- класс `SPOT_TICKER_MATCH_BOTH_VENUES_COLLECTED`: одинаковая строка
  тикера, свидетельство — собранные clean two-venue full-coverage 1h4h
  данные точного v6 реколлекта (одновременная торговля пары на обоих
  venue)
- fail-closed: **EDGE, RAIN** исключены (коллизионные имена)
- вердикт: **7 баз принято** (BDX, CC, MNT, OKB, STETH, USDD, WEETH),
  2 исключены; `verdict_hash=3c5345f0…`
  (`exports/trading-mvp/analysis/slow_liquidity_spot_ticker_identity_verdict_20260816.json`)
- это НЕ canonical-asset/official identity claim; ветка official identity
  остаётся закрытой как incomplete — снят только её блокирующий эффект

## Разблокировка конвейера v6

- deterministic quality-rebind:
  `slow_liquidity_history_recollect_quality_v6_identity_accepted_rebind.json`
  — decision → `SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_IDENTITY_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY`
  (исходный quality-артефакт не изменён, hash-bound)
- `trading_slow_liquidity_fixed_signal_planonly.ps1` расширен: принимает
  новую decision-строку (минимальный патч gate-условия)
- fixed-signal PlanOnly выполнен: decision
  `SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER`
  (packet `slow_liquidity_fixed_signal_planonly_20260816_231913.json`,
  привязан в gate через -UpdateGate)
- тесты: 8 passed
  (`test_slow_liquidity_spot_ticker_identity_acceptance.py`)

## Важно для downstream

Fixed-signal packet берёт clean_bases из clean_markets (все 9). По
контракту identity PRIMARY-статистики downstream (feature normalizer →
replay) должны использовать 7 identity-принятых баз; EDGE/RAIN — только
с флагом исключения. Список принятых баз доступен в rebind-артефакте
(`identity_acceptance.accepted_bases`).

## Next

Feature normalizer PlanOnly → replay v1 PlanOnly (на 7 базах), затем
evaluator — каждый своим планом по standing policy.
