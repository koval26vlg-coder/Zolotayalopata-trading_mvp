# Codex trading_mvp Bitget listing-history expansion checkpoint

Дата: 2026-07-09
Агент: Codex
Запрос: продолжить цель после MEXC/Gate listing-event availability rejection.

## План
- Не запускать collect/replay/grid/live/API keys.
- Расширить listing-event history ветку третьей биржей, чтобы убрать MEXC-heavy перекос.
- Подготовить PlanOnly availability probe gate.

## Что сделано
- Добавлен Bitget в research-only listing calendar через public `GET /api/v2/spot/public/symbols` (`openTime`, `offTime`).
- Добавлен Bitget OHLCV client для listing-event collector через public `GET /api/v2/spot/market/candles`.
- Добавлен маппинг granularity `1m -> 1min`, `5m -> 5min`, `1h -> 1h`.
- `listing_event_history_collect_plan.py` теперь по умолчанию видит `mexc`, `gateio`, `bitget` и поддерживает `min_exchange_count`.
- `trading_listing_event_history_collect_preview.ps1` получил `-MinExchangeCount`.
- `trading_listing_event_history_availability_preflight.ps1` теперь сохраняет в gate параметризованную команду confirmed public probe, чтобы не сбрасываться в дефолты.

## Артефакты
- Calendar: `exports/trading-mvp/listings/non_binance_listing_events_bitget_20260709_073937.csv`
- Calendar summary: `exports/trading-mvp/listings/non_binance_listing_events_bitget_20260709_073937.summary.json`
- Preview: `exports/trading-mvp/analysis/listing_event_history_collect_preview_20260709_074228.json`
- Availability PlanOnly: `exports/trading-mvp/analysis/listing_event_history_availability_preflight_20260709_074318.json`

## Результаты
- Bitget calendar build: 1427 rows total, 3 exchanges, timestamp coverage 0.9797, Bitget rows 188.
- Three-venue preview: 90 selected events, 86 unique bases, exchanges: bitget=26, mexc=41, gateio=23.
- Availability PlanOnly: planned public probe 60 slots: bitget=20, gateio=20, mexc=20, granularity=1h.
- Gate: `LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE`.
- Replay/grid/collect/live/API keys remain blocked.

## Проверки
- Targeted tests: 23 OK.
- Full unit suite: 346 OK, 4 skipped.

## Следующий шаг
- Только после явного подтверждения пользователя запустить сохраненную confirmed public probe command из active-run-gate.
- Если probe accepted: build revised approval packet; actual collect still requires explicit approval phrase.
- Если probe rejected: не collect/replay; диагностировать Bitget/Gate availability и изменить selection.
