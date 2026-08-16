# 2026-08-16 — proxy listing-date source accepted (user contract decision)

Пользователь выбрал «принять proxy-источник даты листинга» вместо закрытия
ветки slow-liquidity как incomplete. Это materially new acceptance-contract
решение; по standing policy оно привязывает план receipt-ом без повторной
approval-фразы.

- `plan_hash=d78ff507d5e53e7cccf78a6ecf676cf85dbb70ab3b67f4dced1fec1cef86be31`
- `plan_file_sha256=90084296cec1ec3ed739c00d21f32981b2bcb93e00dd32d303429ecaeffcd43f`
- receipt `PROXY_LISTING_DATE_SOURCE_ACCEPTED`
- `receipt_hash=6ef9ea95f94bfb4f58f7b972ecf47877a68ae98c6329c86ca78b20368eb8da18`
- `receipt_file_sha256` см. файл receipt
- proxy class `PROXY_TRADING_START_NOT_OFFICIAL_ANNOUNCEMENT`:
  primary = замороженный calendar `listed_ts` (mexc `firstOpenTime`, gateio
  `min_nonzero_buy_start_sell_start`), корроборация earliest available 1h open
  при сборе; per-venue ts сохранены в records
- retrospective first-days windows: 407/407 имён имеют proxy_event_ts
- agreement buckets: le_1h=9, le_24h=5, gt_24h=374, one_venue_only=19, missing=0
- materialization `exports/trading-mvp/analysis/slow_liquidity_listing_momentum_proxy_date_materialization_20260816.json`
  (`materialization_hash=2a8e8d870a9250488d7851204c246b407afe1fc56fd3226ef6aa92fe43c5bc13`)
- limitations в acceptance contract: survivorship current-snapshot, trading-start
  не announcement (нет lead time), history-depth truncation, same-ticker pairing,
  proxy-evidence не переворачивает prior listing_event rejection сама по себе
- ACCEPT на proxy-evidence capped at `PROXY_DATE`; terminal ACCEPT требует
  forward/announcement-grounded sample

Не авторизовано этим шагом: network run, OHLCV collect, replay, evaluator/OOS,
grid/retune, paper/live, private API. Сбор first-days OHLCV — отдельный
hash-bound PlanOnly + видимый запуск.

Известное состояние: два теста незавершённого spot-v2/v3 refreeze из предыдущей
сессии падают (`test_checked_in_spot_v2_freeze_matches_generator`,
`test_offline_refreeze_readiness_resolves_without_execution_artifacts`) — не
связано с этим шагом; незакоммиченные правки тех модулей остаются в рабочем
дереве для отдельного technical rebind.

## Receipt
`docs/agent-log/approvals/2026-08-16-slow-liquidity-listing-momentum-proxy-date-acceptance-approval.json`

## Next
Подготовить collector PlanOnly first-days OHLCV (per-venue windows, page caps,
truncation flags, visible launcher), затем тесты и видимый запуск.
