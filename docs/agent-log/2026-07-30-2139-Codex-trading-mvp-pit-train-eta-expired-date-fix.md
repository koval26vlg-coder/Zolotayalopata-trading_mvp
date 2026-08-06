# Trading MVP PIT train ETA expired-date fix

- Дата: 2026-07-30 21:39:34 +03:00
- Агент: Codex
- Запрос: автономно продолжать `trading_mvp One-Week Historical Edge Sprint` без простоя и без чтения закрытых returns/PnL/OOS.

## План

1. Проверить текущий guard, PIT pointer и metadata-only train progress.
2. Найти расхождения между approved schedule и календарной проекцией до `20/20`.
3. Исправить только доказанный control-plane дефект и закрепить его тестами.

## Выполнено

- Обнаружено, что `pit_train_progress_monitor.py` учитывал уже истёкшие uncertified schedule dates как доступные будущие evidence dates.
- `_project_train_eta` теперь принимает authoritative `now_local` и исключает сегмент после `hard_deadline_local`, если его дата отсутствует в accepted quality certifications.
- DUE, countdown и будущие даты остаются доступными в проекции.
- В отчёт добавлены:
  - `expired_uncertified_schedule_dates_excluded`;
  - `expired_uncertified_dates`.
- Добавлены regressions для истёкших дат и открытого DUE-окна.

## Изменённые файлы

- `trading_mvp/src/pit_train_progress_monitor.py`
  - SHA-256: `2a8ec1cab81d9ee8571c065f3817f3ccd3b3b8d6476fa35b845c774587c77246`
- `trading_mvp/tests/test_pit_train_progress_monitor.py`
  - SHA-256: `bc3cddf94a4855820059e0f88b2ad1fbb999e8c44b1a7739ea096e9e3c8f1389`

## Проверки

- Python compile: PASS.
- Связанный regression: `68` tests PASS.
- `git diff --check`: PASS.
- Реальный metadata-only monitor:
  - accepted distinct dates: `4/20`;
  - expired uncertified dates excluded: `2026-07-29`, `2026-07-30`;
  - future approved dates available: `12`;
  - projected accepted dates at current schedule end: `16/20`;
  - minimum additional dates after current schedule: `4`;
  - earliest possible train checkpoint if every future date passes: `2026-08-15`.
- Evidence boundaries: `returns_read=false`, `pnl_read=false`, `signals_read=false`, `market_payloads_read=false`.

## Риски и следующий шаг

- Проекция календарная и не предполагает будущую quality acceptance; rejected future segment увеличит дефицит.
- PIT extension остаётся PlanOnly и не активируется автоматически.
- Следующий market-data action не меняется: exact preapproved n03 запускается видимо только когда `DUE` либо `eta<=300 sec`.
