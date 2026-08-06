# trading_mvp listing-event OHLCV collect checkpoint

Дата: 2026-07-09 00:41:50 +03:00
Агент: Codex

## Запрос пользователя
Подтвержден visible listing-event OHLCV history collect.

## Что сделано
- Проверен active-run gate и Aion bootstrap.
- Исправлен MEXC spot 1h interval mapping на 60m.
- Добавлен availability-driven collect preview: explicit event plan строится из accepted probe_rows вместо старого календарного выбора.
- Collector теперь использует explicit selection.sample_events только при vent_plan_source=explicit_sample_events.
- Approval packet принимает reduced verified availability set при accepted preflight, сохраняя блок replay/grid/live/API.
- Запущен visible PowerShell collector window PID 33964.
- Новый collect завершился: listing_event_history_collect_20260709_002533, 1088 OHLCV rows, 0 placeholders, 0 errors.
- Data-quality выполнен и отклонен только по размеру выборки: 15 events/bases/slots < gate minimum 30/20/30.
- Подготовлен expanded availability PlanOnly checkpoint: 40 planned slots, 20 Gate + 20 MEXC, 1h; public probe требует отдельного подтверждения.

## Артефакты
- Availability accepted: exports/trading-mvp/analysis/listing_event_history_availability_preflight_20260709_001823.json
- Collect preview: exports/trading-mvp/analysis/listing_event_history_collect_preview_20260709_002533.json
- Approval packet: exports/trading-mvp/analysis/listing_event_history_collect_approval_packet_current.json
- Collect output: exports/trading-mvp/listing-history/listing_event_history_collect_20260709_002533/ohlcv.jsonl
- Collect manifest: exports/trading-mvp/listing-history/listing_event_history_collect_20260709_002533/manifest.json
- Data quality: exports/trading-mvp/analysis/listing_event_history_data_quality_20260709_002932.json
- Expanded availability PlanOnly: exports/trading-mvp/analysis/listing_event_history_availability_preflight_20260709_003024.json

## Проверки
- Targeted tests: 15 OK before collect.
- Previous failures fixed: 4 OK.
- Full test suite: 342 OK, 4 skipped.
- Active gate: LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE; replay_allowed=false.

## Риски и ограничения
- Новый clean collect технически качественный, но мал для replay/normalizer gates.
- Следующий шаг только после подтверждения: public availability probe на 40 planned slots.
- Не запускать replay/grid/live/API/paper-forward до eplay_allowed=true.
