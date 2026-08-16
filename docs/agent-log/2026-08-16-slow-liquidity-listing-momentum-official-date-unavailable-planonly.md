# 2026-08-16 — Listing Momentum official date method unavailable PlanOnly

Сеть не открывалась. URL не изобретён. OHLCV не открыт. Calendar listed_at не принят как official announcement.

In-repo audit:
- Official HTML indexes `www.mexc.com/announcements` и `www.gate.com/announcements` уже прочитаны; selected_bases=[].
- Один article `first-in-market-17827791537583`: title не ticker, publish timestamp не извлечён.
- Listing-first name discovery закрыт как unreachable.
- Documented unsigned announcement JSON endpoint в репозитории нет.
- `firstOpenTime` / `buy_start` / `sell_start` уже в frozen calendar как public API snapshot, не official announcement; first-days sample = 0.
- Gate unsigned `/spot/currencies/{BASE}` — identity, не listing date.

## Frozen
- `plan_hash=02883ef427104f25f36be1bfc349b6f41671ba5df0f96162bfa44ee4fb000337`
- `plan_file_sha256=b169583600aba0aff3f10723494b0ea82d7e03f04dad822670d5cde9f2ddbc57`

## File
`docs/plans/slow-liquidity-listing-momentum-official-date-unavailable-planonly-20260816.json`
