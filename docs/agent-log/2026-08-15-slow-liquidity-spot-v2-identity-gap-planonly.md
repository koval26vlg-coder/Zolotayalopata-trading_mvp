# 2026-08-15 — spot v2 identity gap PlanOnly

Currency JSON не повторялся. r5 page locator не строился. Сеть не открывалась.

## Почему gap, а не новый locator
- r1–r4: 0 official-page URL
- Currency JSON: 4 unique Gate EVM (STETH/WEETH/OKB/MNT); EDGE/RAIN fail-closed; CC/USDD/BDX не уникальны
- Frozen HTML consumer: 18 пар, minimum 8 two-venue bases, MEXC `/support/articles/`
- Максимум официальных идентификаторов сейчас: 4 Gate-only → 8 two-venue bases недостижимы
- MEXC unsigned contract JSON в public spot docs нет

## Frozen
- `plan_hash=df92867aa836c6a03092d49895207ffac5260674bdcbf2b1d17a3912d0b58973`
- `plan_file_sha256=bdea19b374e845064513fa1261265a2922666c456ad2cb9ffaef1d02cc5c3279`
- network_authorized=false, identity_verdict=false, rescope_authorized=false

## Files
- `docs/plans/slow-liquidity-spot-v2-identity-gap-planonly-20260815.json`
- `trading_mvp/src/slow_liquidity_spot_v2_identity_gap.py`
- `trading_mvp/tests/test_slow_liquidity_spot_v2_identity_gap.py`
