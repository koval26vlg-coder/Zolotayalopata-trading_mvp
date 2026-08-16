# 2026-08-16 — forward monitor новых листингов: план готов, первый тик COMPLETED

Forward-ветка после закрытия ретроспективы как descriptive (survivorship
доминирует): accrual survivorship-clean выборки новых листингов MEXC+Gate.

- план `slow_liquidity_listing_momentum_forward_monitor_20260816`
- `plan_hash=bc55d56faea5e456426757e5d8e3f724a37fd4eedea12fae4dc6857cc102d2c9`
- `plan_file_sha256=1e8020dd…` (полный в плане; файл
  `docs/plans/slow-liquidity-listing-momentum-forward-monitor-planonly-20260816.json`)
- tick-контракт: repeatable bounded visible tick, `MaxRuntimeSec=600`,
  2 снапшот-запроса (MEXC exchangeInfo + Gate currency_pairs) + ≤1 страницы
  на новый листинг, cap 50 новых листингов/тик
- семантика: `new_listing_window_complete` / `new_listing_in_progress`
  (listed_ts ≥ baseline 2026-08-16T00:00Z) / `backfill_or_relist_skip`
  (старый ts: записывается, не собирается)
- guards: gate не RUNNING, writer claim отсутствует, видимый запуск, один
  тик за раз, tick-директория новая, никакого фонового демона
- acceptance: `NONE_ACCRUAL_ONLY`; evaluator — отдельный план при
  достаточном числе complete окон

## Первый тик (end-to-end валидация, живой)

- `forward_tick_20260816T194911Z` — COMPLETED, 3 запроса, exit 0
- найден реальный новый листинг: **MARSCOIN1/USDT на MEXC**
  (proxy_ts=1786886700, сегодня), окно идёт: 6 баров, флаги
  `window_in_progress`+`short_window` — семантика корректна
- state: `ACCRUING`, tick_count=1, window_count=1, complete=0,
  `state_hash=0b67e2a055704691c80c4a4d435d9182afadeaeaea6ece64e98b3fad66731854`
- (`exports/trading-mvp/analysis/slow_liquidity_listing_momentum_forward_state_20260816.json`)
- длинный skip-лист gateio — пары вне baseline-universe со старыми
  buy_start: классифицированы `backfill_or_relist_skip`, не собираются
- pointer READY_FOR_POSTPROCESS, launch record COMPLETE, claim освобождён

## Инцидент запуска (исправлен в шаге)

Первый тик упал до claim: `float('')` на пустом `listed_ts` в строках
снапшота (rows_from_* пишут "" вместо None). Исправлено
(`str.strip()==''` → skip) + юнит-тест. Также launcher дополнен
финальной записью pointer/launch record после тика (иначе pointer
зависал бы в RUNNING).

Тесты: 10 passed (`test_slow_liquidity_listing_momentum_forward_monitor.py`).
Preflight launcher: ok=true. `--plan-check`: PLAN_OK.

## Cadence

Рекомендация плана: ручной тик по «продолжай» или scheduler, не чаще 1
тика в 3 часа (окно 3 дня ⇒ пропуск листинга исключён при любой разумной
частоте). Фоновый демон без явного разрешения пользователя запрещён.

## Next

Периодические тики (каждые несколько часов/дни) до накопления complete
окон; затем — evaluator план для forward-выборки.
