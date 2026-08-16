# 2026-08-16 — first-days Listing Momentum proxy-date collect COMPLETED

Видимый public read-only сбор per-venue first-days 1h окон по proxy-датам
(родитель: `PROXY_LISTING_DATE_SOURCE_ACCEPTED`).

- plan `slow_liquidity_listing_momentum_first_days_collect_20260816`
- `plan_hash=c48349500731708b7afa33f7c88c32c75ea2731bf285f7f9d434782b87621134`
- `plan_file_sha256=e086052aeeb230c9…` (полный в плане)
- jobs 795 (mexc 393 / gateio 402), logical_requests 795, MaxRuntimeSec 1800
- факт: 2026-08-16T18:42:14Z → 18:54:53Z UTC (~13 мин), requests 369+retries
- статус `COMPLETED`, `rows_written=26252`
- `output_sha256=a44b7daf8709ed786e0a43fe390ea57a1f2055a17aab6bd870eaaa93b9bab4e8`
- output `E:\trading_mvp\listing-momentum-first-days\slow_liquidity_listing_momentum_first_days_collect_20260816\`
- flag census: `no_data=3, request_error=426, proxy_ts_after_first_bar=0,
  history_truncated=3, short_window=3`; чистых окон 363

## Ключевая находка: лимит глубины Gate

397/402 gateio-джобов → HTTP 400
`INVALID_PARAM_VALUE: "Candlestick too long ago. Maximum 10000 points ago
are allowed"` — Gate v4 spot/candlesticks отдаёт 1h-свечи максимум на
~10000 точек назад (~417 дней). Это жёсткий лимит площадки: ретроспективные
first-days окна на Gate недоступны для universe, где 406/407 имён старше
90 дней. Семантика этих `request_error` = venue depth limit (класс
HISTORY_DEPTH_TRUNCATION, уже зафиксированный в limitations контракта).
Остальные 29 ошибок MEXC — реально исчезнувшие пары (delisted, invalid
symbol).

## Данные

- MEXC: 358 чистых окон по 72 бара (медиана 72, min 70) + 3 truncated
  (CBK, FUSE, HAI) + 3 no_data (PACK, SNT, XCN) + 29 invalid пар
- Gate: только 5 свежих окон; ретроспектива недоступна из-за лимита 10000
- two-venue slow-liquidity рамка деградирует до single-venue (MEXC) для
  ретроспективного first-days; Gate остаётся пригоден только для
  forward/свежих листингов

## Инциденты запуска (технические, исправлены в этом же шаге)

1. первый запуск: PS-редирект в несуществующую output-директорию →
   launcher теперь создаёт директорию до редиректа
2. `KeyError effective_page_sizes` (рассинхрон plan↔collector) → ключ
   добавлен в execution + fail-fast `REQUIRED_EXECUTION_KEYS` +
   контрактный тест
3. `UnboundLocalError requests` в error-ветке (тест маскировал порядком
   джобов) → инициализация до try + тест с падающим первым джобом
4. fatal-error теперь финализирует manifest (`FAILED`, `fatal_error`) и
   возвращает ненулевой exit code

Тесты: 18 passed (`test_slow_liquidity_listing_momentum_first_days_collect.py`).

## Receipt
Родительская авторизация: `docs/agent-log/approvals/2026-08-16-slow-liquidity-listing-momentum-proxy-date-acceptance-approval.json`

## Next
Детерминированный quality census + event-window статистика по 363 MEXC
окнам (класс доказательств PROXY_DATE, лимитации контракта действуют);
Gate-ветка — только forward-мониторинг новых листингов. Evaluator/OOS —
отдельным планом.
