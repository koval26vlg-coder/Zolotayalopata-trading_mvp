# Все исследовательские треки стратегии — 2026-08-19

## Решение

Для проверки исполнимости listing-стратегии включён полный публичный research-контур. Треки остаются независимыми: результаты не объединяются в одну выборку и не дают live-разрешение.

1. Spot Listing Momentum v2: MEXC + Gate.
2. Spot Listing Momentum expansion: Binance + Bybit + OKX + Bitget.
3. Crypto pre-market perpetual: Bybit + OKX + Gate; теперь активен, ранее был явно `PAUSED`.
4. Pre-IPO equity perpetual: OKX + Gate.
5. Pre-IPO candidate: Bybit; discovery/candidate-only, без acceptance, пока не появятся официальный контракт и официальный timestamp-метод.

## Общий контракт

- Каждая automation просыпается каждые 5 минут, но делает network/write только при наступлении собственного `next_interval_at_utc`.
- Не наступившее окно возвращает `NOT_DUE` без collector, writer claim и отчёта.
- Public data only; private API, ключи, реальные ордера, real capital, leverage, margin, evaluator/OOS/live trading запрещены.
- При ошибке сохраняется `RETRY_NEXT_INTERVAL`; частичный результат — `PARTIAL_RETRY_NEXT_INTERVAL`.
- Lifecycle, official/proxy timestamps, raw market events и causal paper execution остаются в отдельных namespaces.

## Recovery

Перед активацией pre-market обнаружен stale claim от мёртвого worker PID `25868`. PID проверен как несуществующий; claim не удалён, а перемещён в `docs/agent-log/global-writer-claim-archive/premarket_perp_listing_automation.claim.stale.20260819T145429Z.json`. State и launch record переведены в `RETRY_NEXT_INTERVAL`, recovery записан в append-only attempts ledger.

## Ограничение candidate-трека

Bybit pre-IPO не активируется автоматически: PlanOnly требует официального pre-IPO контракта и официального timestamp-метода. До этого Bybit учитывается только как candidate/discovery и не смешивается с OKX/Gate acceptance.

## Проверка

- Active Run Gate перед recovery: `READY_FOR_POSTPROCESS`.
- Worker PID `25868`: dead до release.
- После release нет активного pre-market claim; следующий due тик оставлен на `2026-08-19T18:26:33.3791851+00:00`.
- Listing, pre-market и Pre-IPO app automations переведены в standalone local project cron, активны, с минимальным reasoning budget и failed-runs-only notifications.

## Дополнительная проверка запуска

- Первый вызов с прямым `-InlineWorker` был остановлен логически после короткого bounded worker: он завершился с exit code `0`, claim освобождён, записи сохранены.
- Scheduler prompt исправлен на обычный `-ScheduledTick -Json`; `-InlineWorker` больше не вызывается расписанием напрямую.
- После исправления обычный pre-market scheduler smoke вернул `NOT_DUE` при следующем интервале `2026-08-19T15:58:55.888792Z`, без нового worker.
- Последний bounded pre-market capture завершил Bybit/OKX/Gate с `events_written=417` суммарно в этом состоянии, `complete_events=0`; это accrual, не acceptance.
