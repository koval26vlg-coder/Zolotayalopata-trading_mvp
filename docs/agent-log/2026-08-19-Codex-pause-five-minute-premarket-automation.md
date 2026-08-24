# Пауза пятиминутной pre-market automation

Дата: 2026-08-19  
Запрос: остановить пятиминутные запуски.

## Изменение

- Codex automation `zolotyaylopata-pre-market-perpetual-listing-impulse-monitor` переведена в `status = PAUSED` через `automation_update`.
- Её расписание `RRULE:FREQ=MINUTELY;INTERVAL=5` сохранено, но новые fires отключены.
- State, manifest, attempts ledger и launch record не удалялись.
- Проверка launcher status: `worker_alive = false`; активного процесса для остановки нет.

## Не затронуто

- `zolotyaylopata-pre-ipo-perpetual-event-monitor` остаётся ACTIVE: один 5-минутный public capture tick каждые 3 часа.
- `zolotyaylopata-listing-momentum-monitor` остаётся ACTIVE по своему отдельному расписанию.
