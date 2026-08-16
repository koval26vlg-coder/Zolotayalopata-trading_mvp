# 2026-08-16 — listing announcement discovery visible run

## Result
- Launch: `COMPLETE`
- Discovery: `LISTING_ANNOUNCEMENT_DISCOVERY_INCOMPLETE`
- HTTP: 2 (`https://www.mexc.com/announcements`, `https://www.gate.com/announcements`)
- candidate_count: 1
- selected_bases: `[]` — тикеры не выдуманы
- identity_verdict=false, bing=false, sitemap=false, v7=false, retry=false
- Writer claim released
- Это не identity verdict и не OHLCV collect

Один извлечённый href (MEXC, `evidence_class=OFFICIAL_LISTING_ANNOUNCEMENT_INDEX`):
`https://www.mexc.com/announcements/article/first-in-market-17827791537583`

Gate index: 0 href `/announcements/article/` после фильтров (query/fragment/futures/closed 9).

Slug `first-in-market` не принимается как ticker и не попадает в `selected_bases`.

## Hashes
- plan_hash=`1a7e4505e611b505e23c98cd89be015dc04d14b2da7cf3df12085a21db9ec8db`
- plan_file_sha256=`4ed3124faf5abb26db95963aad316cccd98006945ae0bd5f1bd32ef07325bfa8`
- candidates_sha256=`63782d79b5bbb259dda4832e3dd4692930aa30bbd336d9e435cc43f63078186d`
- manifest_sha256=`47f1d91d8cb905d8c0f0b9a5b02132ddd7ab15a6b575219795008ebf60b2100b`

## Artifacts
- `E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-listing-announcement-discovery\slow_liquidity_listing_announcement_discovery_20260816\listing-announcement-candidates.json`
- `E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-listing-announcement-discovery\slow_liquidity_listing_announcement_discovery_20260816\manifest.json`
- `docs\agent-log\run-gates\slow_liquidity_listing_announcement_discovery_20260816.launch.json`
- `docs\agent-log\approvals\2026-08-16-slow-liquidity-listing-announcement-discovery-approval.json`
