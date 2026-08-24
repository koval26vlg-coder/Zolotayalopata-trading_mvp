# Pre-IPO Perpetual Event v1 — bounded implementation

Дата: 2026-08-18  
Ветка: `preipo_perpetual_event`  
Статус: `BOUNDED_IMPLEMENTATION_READY_NOT_AUTOMATED`

## Scope

- Отдельный research-only контракт для pre-IPO equity perpetual.
- Активные venue: OKX и Gate.
- Bybit оставлен candidate-only: активация возможна только при официальном pre-IPO контракте и отдельном методе точного timestamp.
- Crypto Listing Momentum и crypto pre-market perpetual namespaces не изменяются и не смешиваются.
- Только public data и paper-модель: 25 USDT, primary 1x-equivalent, stress 2x/5x только на бумаге.
- LONG и SHORT — независимые стороны; entry cohorts: `first_tradable` и `last_1_4h`.
- Fixed exits: IPO open, +5s, +15s, +60s и conversion; peak-aware/hindsight exits отсутствуют.
- Rebase моделируется value-neutral (цена и количество изменяются обратно пропорционально; PnL credit = 0).
- Точная дата/время first trade обязательна для acceptance; expected IPO date без точного времени остаётся proxy.

## Реализация

- `trading_mvp/src/preipo_perp_event.py` — lifecycle, official/proxy parser, causal entry cohorts, rebase, LONG/SHORT replay, partial/unfilled fills, fee/slippage/funding fields и deterministic result hash.
- `trading_mvp/src/preipo_plan.py` — отдельный immutable PlanOnly validator.
- `docs/plans/preipo-perpetual-event-planonly-20260818-v1.json` — hash-bound contract, state namespace и acceptance gates.
- `trading_mvp/tests/test_preipo_perp_event.py` — 10 behavioral tests.
- `trading_mvp/tests/test_preipo_plan.py` — 3 PlanOnly/hash/venue-bound tests.

Plan hash: `a4a74581adf664c79a3ac6fb83fa38d18d4bd8bc2a3b9fe99db0aeaaed458ebd`  
Plan file SHA-256: `34c46e215ef521799066938208ece553c70f8826a83f137cf108869910a31b56`  
Event module SHA-256: `19696460d6a0a4b7470d76fdc8a779154385053be70c3c2522d502ad25c3eb62`  
Plan validator SHA-256: `3b06cfcfdb82b3c3c58c8a411c6e4d20adf2762e3af0fa96878eac2020a10708`

## TDD/verification evidence

- RED: `python -m pytest trading_mvp/tests/test_preipo_perp_event.py -q` завершился ожидаемым `ModuleNotFoundError: preipo_perp_event` до реализации.
- RED: PlanOnly тест после добавления файла показал только ожидаемые placeholder/hash mismatches.
- GREEN: `C:\Program Files\Python313\python.exe -m pytest trading_mvp/tests/test_preipo_perp_event.py trading_mvp/tests/test_preipo_plan.py -q` — `13 passed`.
- Regression: `C:\Program Files\Python313\python.exe -m pytest trading_mvp/tests/test_premarket_perp.py trading_mvp/tests/test_premarket_listing_resolver.py -q` — `21 passed`.
- Compile: `C:\Program Files\Python313\python.exe -m py_compile trading_mvp/src/preipo_perp_event.py trading_mvp/src/preipo_plan.py trading_mvp/tests/test_preipo_perp_event.py trading_mvp/tests/test_preipo_plan.py` — exit code 0.
- Active-run gate перед работой: `READY_FOR_POSTPROCESS`; старый slow-liquidity replay остаётся запрещённым и не использовался.

## Не запускалось

Отдельный visible pre-IPO collector/orchestrator, network discovery и scheduled automation в этой bounded фазе не запускались. Для них нужен следующий отдельный технический пакет с public adapters, raw event store, recovery state/ledger и видимым orchestrator; существующие crypto и spot automation остаются независимыми.
