# Codex trading_mvp listing availability public probe

Дата: 2026-07-09
Агент: Codex
Запрос пользователя: подтверждаю expanded listing-event history availability public probe

## Что сделано
- Выполнен Aion bootstrap.
- Проверен active-run gate: READY_FOR_POSTPROCESS, replay/grid заблокированы.
- Запущен подтвержденный short public REST probe:
  `tools/trading_listing_event_history_availability_preflight.ps1 -MaxEventsPerExchange 20 -Granularities 1h -ConfirmedPublicProbe -UpdateGate -Json`
- Артефакт probe:
  `exports/trading-mvp/analysis/listing_event_history_availability_preflight_20260709_072952.json`

## Результат
- Decision: LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_RESAMPLE_OR_GATE_FIX
- Slots: 40
- OK events: 27
- OK by exchange: gateio=7, mexc=20
- API errors: 13, all on Gate older listing-event windows
- API error slot rate: 0.325
- Max single exchange OK fraction: 0.7407407407407407, above limit 0.70

## Диагноз
- Failed Gate pairs are still tradable and current candles are available.
- Historical candles around old listing windows return Gate HTTP 400.
- Current CSV has only 7 active Gate USDT listing events after 2025-07-23.
- Therefore current MEXC+Gate listing-history branch cannot reach strict balanced >=30 event sample with existing two collectors.

## Gate state
- Gate updated to LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_RESAMPLE_OR_GATE_FIX.
- Collect/replay/grid/paper-forward/live/API keys remain blocked.

## Следующий безопасный шаг
- Do not start OHLCV collect.
- Either add a third public spot OHLCV/listing venue to listing-event history research, or explicitly downgrade evidence requirements for a weaker MEXC-heavy sample.
