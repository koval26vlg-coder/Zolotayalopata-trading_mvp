# trading_mvp productive fallback autopilot

## Запрос

Устранить простой до будущих календарных PIT-окон: выполнять полезные действия
последовательно, без повторных подтверждений и без дублирования закрытых
прогонов.

## Результат

- Добавлена one-shot `productive_fallback_queue`.
- Добавлен append-only ledger и allowlist runner без произвольного shell.
- `WAITING_SCHEDULE_WINDOW` теперь переходит в
  `CONTINUE_PRODUCTIVE_FALLBACK`, пока есть невыполненная задача.
- Heartbeat обновлен до 20-минутного event loop.
- Сохранен code-only baseline из 437 файлов:
  `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\code-baseline-689b46ea182d3b4e.json`.
- Gate official archive и Tardis повторно не запускались: локальная и внешняя
  проверка подтвердила, что эти источники уже исчерпаны для закрытых веток.

## Проверки

- Targeted autopilot tests: `23 OK`.
- Paper OMS/reconciliation shard: `25 OK`.
- Full regression: `1170 OK`, `5 skipped`, runtime `785.299 sec`.
- Costs, identity, execution и frozen evaluator shards: exit code `0`.
- Weekly remaining at final guard check: `52%`, stop threshold `15%`.
- Active market-data gate: `READY_FOR_POSTPROCESS`; live writer отсутствует.

## Риски

- Новый независимый PIT sample физически нельзя получить повтором в ту же дату.
- После исчерпания one-shot queue допустимо только честное
  `WAITING_SCHEDULE_WINDOW_NO_FALLBACK`; искусственный busy-loop запрещен.
- Edge не доказан, replay/live/private API keys/leverage/margin не разрешены.

## Следующему

В due-окно запустить только exact-approved PIT segment. До due-окна выполнять
первую невыполненную fallback-задачу. Не повторять Gate archive/Tardis и
закрытые strategy branches.
