# Dense WS host continuity readiness

## Зачем

24-часовой writer бесполезен, если Windows уснёт, часы заметно смещены или закончится диск. Добавлен read-only preflight, который перепроверяет это непосредственно перед запуском.

## Результат сейчас

- Status: `READY`.
- Компьютер подключён к сети; батарея 100%.
- Сон и гибернация от сети отключены.
- Свободно 825070010368 байт; требуется минимум 50000000000 байт.
- Часовой пояс: `Volgograd Standard Time`.
- Фактическое фазовое смещение часов: 0.0000943 секунды при лимите 0.5 секунды.
- Последняя успешная NTP-сверка старше суток, поэтому сохранено предупреждение. Попытка ручного resync получила `ACCESS_DENIED`; настройки и часы не менялись.

## Изменения

- Новый checker: `tools\check_dense_ws_host_readiness.ps1`.
- SHA256: `77e197d1eef209d2ec0bf61f1449efdc285593a2eb46bea199ae99c69882211d`.
- Heartbeat обязан вызвать checker перед actual dense launch и продолжить только при `READY` и пустом списке blockers.

Writer, collector, postrun и evaluator не запускались. Evidence: `docs\agent-log\readiness\dense-ws-host-continuity-readiness-20260802T1946+0300.json`.
