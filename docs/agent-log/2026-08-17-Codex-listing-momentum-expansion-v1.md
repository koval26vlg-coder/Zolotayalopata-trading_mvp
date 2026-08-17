# Listing Momentum expansion v1 — compatibility и PlanOnly

Дата: 2026-08-17
Агент: Codex

## Решение

Пользователь подтвердил отдельный expansion-контур для Binance Spot, Bybit Spot, OKX Spot и Bitget Spot. Текущий immutable MEXC + Gate v2 не расширялся и не перезаписывался.

## Compatibility preflight

Запуск выполнен видимым launcher-скриптом:

`tools/start_listing_momentum_exchange_expansion_preflight_visible.ps1 -Json`

Receipt: `exports/trading-mvp/analysis/listing_momentum_exchange_expansion_preflight_20260817.json`

- status: `PASS`
- receipt_hash: `fb4be6e1d02a2a276f52d518004c6396d6ae4e7bb706e5bda3f759f09f2aa8b9`
- file_sha256: `85fb8f0c56c88060a0eb0e185bb2e109704f97634ff5ee99efef4e65ee41179c`
- request_count: `8` — один public snapshot и один 1h OHLCV probe на каждую площадку
- elapsed_sec: `6.863`
- raw payload persistence: `false`

| venue | snapshot rows | active rows | timestamp coverage | sample | parsed candles |
|---|---:|---:|---:|---|---:|
| Binance | 733 | 484 | 0.0 | BTCUSDT | 2 |
| Bybit | 409 | 409 | 0.0 | BTCUSDT | 2 |
| OKX | 367 | 366 | 1.0 | BTC-USDT | 2 |
| Bitget | 1189 | 1182 | 1.0 | BTCUSDT | 2 |

Timestamp caveats are part of the contract: Binance and Bybit use an explicit detection-time proxy when the current public spot snapshot has no trustworthy listing timestamp; OKX uses `listTime`; Bitget retains `openTime` only as a separately flagged deprecated timestamp with fallback to proxy.

## Expansion PlanOnly

Plan: `docs/plans/slow-liquidity-listing-momentum-forward-expansion-planonly-20260817.json`

- plan_id: `slow_liquidity_listing_momentum_forward_expansion_20260817_v1`
- plan_hash: `5c52d2d637d97280ba03204cc9da35fa024063ae3d13b4697b163d8ea5c00084`
- file_sha256: `5b5f32f807e107cefd00d500a7dec6d1497763a6786ec713f57d0d3cd7c58e6a`
- status: `READY_FOR_VISIBLE_EXPANSION_TICKS`
- replay/evaluator/OOS: forbidden
- output namespace: `E:\trading_mvp\listing-momentum-forward-expansion`
- separate from v2: `true`

Implementation is in separate files so the v2-bound parser/client hashes remain intact:

- `trading_mvp/src/listing_momentum_exchange_expansion.py`
- `trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py`
- `trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_plan.py`
- `tools/start_listing_momentum_exchange_expansion_preflight_visible.ps1`

## Проверки

- active-run gate immediately before the public preflight: `READY_FOR_POSTPROCESS`; no live writer PID
- targeted regression suite: `27` tests passed
- Python compile: passed for all expansion modules and tests
- PowerShell parser: `POWERSHELL_PARSE_OK`
- expansion preflight `--check`: `PASS`
- expansion monitor `--plan-check`: `PLAN_OK`
- original MEXC + Gate v2 monitor `--plan-check`: `PLAN_OK`, plan hash `d98d402fb08065bef58859522b938ec064b2bc4a223f269aa0218cce502e5afb`
- original v2 plan file SHA remains `33da4a8bc9ece1f43055dbb833afa49f068328f4c192bdcad690a7421968c0ee`

Длительный expansion tick в этой итерации не запускался; создан только короткий public compatibility receipt и готовый hash-bound PlanOnly.
