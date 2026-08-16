# 2026-08-15 — spot v2 official currency JSON PlanOnly

r1–r4 page locators не повторялись. Сеть не открывалась. Это не r5.

## Почему не r5
- r4: 18/18 LISTED, 1839 locs, 1000 titles, 0 ticker matches, `request_plan=[]`
- Ещё один sitemap/search/Bing прогон не даст 18-item official-page request plan
- Identity execution по HTML consumer по-прежнему закрыт

## Новый locator
- Official unsigned Gate `GET /api/v4/spot/currencies/{BASE}`
- Поле `chains[].addr`; уникальный EVM addr
- EDGE/RAIN fail-closed
- MEXC unsigned contract JSON в public spot docs нет; undocumented endpoint запрещён
- Output: Gate records only; status всегда `SPOT_V2_OFFICIAL_CURRENCY_JSON_INCOMPLETE`
- Не identity verdict и не HTML request plan

## Frozen hashes
- `plan_hash=b6db2d430d42728681594701e00ddeb95f302f5728e99f198daccadc930fc9fc`
- `plan_file_sha256=7e0820f23dd34cf8a70084193e97505650191bc2e9ed9ee3e0a4d713282d5f48`
- Parent r4 `plan_hash=2f8cb14b747e582c54b1749a5ff2f5955774b427d2792d31b3853af9c3cd5de9`
- Parent r4 `plan_file_sha256=05187e3be802a5f2d53d00866f342c1a3f4a0c9d29f70932831ec16973203cce`
- Parent r4 manifest `1e602cff2f97e34f169965b7c7f86459a547a1698a7e270c895a63a542fa825f`

## Files
- `docs/plans/slow-liquidity-spot-v2-official-currency-json-planonly-20260815.json`
- `trading_mvp/src/slow_liquidity_spot_v2_official_currency_json.py`
- `trading_mvp/tests/test_slow_liquidity_spot_v2_official_currency_json.py`
- `tools/start_exact_approved_slow_liquidity_spot_v2_official_currency_json_visible.ps1`
