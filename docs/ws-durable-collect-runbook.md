# Runbook: durable сегментированный WS-сбор

Дата: 2026-07-03
Автор: Claude Code
Назначение: замена хрупкой связки «visible terminal владеет процессом» на durable-протокол из ревью падений ран 20260702_012710 и 20260702_101730.

## Архитектура

- **Коллектор** (`trading_mvp/src/ws_durable_collector.py`) — detached-процесс, сам владеет своим состоянием:
  - режет ран на сегменты (по умолчанию 3ч); каждый сегмент — отдельная папка `seg_NNN/` с raw-файлами и **собственным финальным manifest.json**;
  - пишет `state.json` атомарно (tmp+replace) каждые 30с: heartbeat, текущий сегмент, размеры raw, ошибки, exit_reason;
  - на выходе (нормальном или по сигналу) — stitched run-manifest `ws_collect_<run_id>.json` с gap accounting.
- **Watcher** (`tools/watch_ws_collect_durable.ps1`) — отдельный процесс, только читает state.json. Закрытие окна watcher **не влияет** на сбор. Подсвечивает stale heartbeat (>90с) как признак смерти коллектора.
- **Starter** (`tools/start_ws_collect_durable.ps1`) — видимый monitor-wrapper. По умолчанию не запускает hidden/detached long run: пишет `active-run-gate.json`, `launch.json`, stdout/stderr, показывает progress и guarded stop/restart команды. Фоновый/detached запуск не является стандартным путем.

## Почему так

Оба падения 72ч ранов: процесс-дерево убито извне (закрытие окна/kill) при живой сети — все WS-потоки замолкали одновременно, manifest не создавался, gate чинился вручную. Durable-протокол: (а) завершённые сегменты — самостоятельная ценность с manifest'ами; (б) смерть процесса оставляет state.json с последним heartbeat; (в) постфактум-finalize закрывает gate штатно.

## Команды

PlanOnly без запуска:

```powershell
pwsh -NoProfile -File tools\start_ws_collect_durable.ps1 `
  -TotalSec 7200 -SegmentSec 3600 -PlanOnly
```

Старт verification 2ч с боевым universe после явного решения заменить старый `STOPPED_INCOMPLETE`:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\start_ws_collect_durable.ps1 `
  -TotalSec 7200 -SegmentSec 3600 `
  -Exchanges "mexc,gateio" `
  -UniversePath "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" `
  -MaxSymbols 300 -MaxPairsPerExchange 16 `
  -ConfirmedLongRun -ReplaceStoppedIncomplete
```

Старт 72ч после успешного verification:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\start_ws_collect_durable.ps1 `
  -TotalSec 259200 -SegmentSec 10800 `
  -Exchanges "mexc,gateio" `
  -UniversePath "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" `
  -MaxSymbols 300 -MaxPairsPerExchange 16 `
  -ConfirmedLongRun
```

Статус (в любой момент, из любого окна):

```powershell
pwsh -NoProfile -File tools\watch_ws_collect_durable.ps1 -RunDir <run_dir>
# или разово:
python trading_mvp\src\ws_durable_collector.py status --run-dir <run_dir>
```

Resume после остановки из консоли:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\start_ws_collect_durable.ps1 `
  -RunId <run_id> -Resume -ConfirmedLongRun
```

Где взять команду resume:

- `tools\check_active_run_gate.ps1 -Json` → поля `resume_command`, `durable_status_command`, `alert_path`.
- `exports\trading-mvp\raw-durable\<run_id>\launch.json`.
- `exports\trading-mvp\raw-durable\<run_id>\STOPPED_INCOMPLETE.txt`, если wrapper успел записать alert.

Постфактум-финализация после смерти рана (stitched manifest + inferred exit reason):

```powershell
python trading_mvp\src\ws_durable_collector.py finalize --run-dir <run_dir> --expected-total-sec <sec>
```

## Интерпретация collector_exit_reason

- `completed_all_segments` — штатное завершение.
- `terminated_by_signal_N` — остановлен сигналом (Ctrl+C/kill с обработкой).
- `collector_exception_<Type>` — упал с исключением (детали в state.errors и stderr-логе).
- `killed_externally_inferred_stale_heartbeat` — процесс убит без шанса записать причину (закрытие окна, hard kill, выключение): status=running, heartbeat старше 120с.
- `no_state_file` — ран не успел стартовать или папка не та.

## Gate-протокол для durable-ранов

1. Данные из run считаются proof-кандидатом только по stitched manifest: `completed=true`, `coverage_ratio` и `gaps` в пределах data-quality gate.
2. Неполный ран: `finalize` → stitched manifest честно перечисляет полные сегменты; их можно принимать как partial research sample по явному решению (segments со своими manifest'ами валидны сами по себе).
3. Автовыбор входа в ws-normalize/ws-postprocess теперь защищён (`cli.py::_latest_ws_input`): отказ при raw новее последнего manifest или manifest c completed=false — вход указывать явно.
4. Если старый gate имеет `STOPPED_INCOMPLETE`, новый actual durable run не стартует молча. Нужен `-ReplaceStoppedIncomplete`, который архивирует старый gate в `docs/agent-log/archived-gates/` и только после этого запускает новый видимый wrapper.
5. Если durable run остановился, wrapper переводит gate в `STOPPED_INCOMPLETE`, пишет `notification_required=true`, `alert_path` и `resume_command`. Следующий шаг цели запрещён до resume или явного признания dataset неполным.

## Verification 2026-07-03

- **Happy path** (`ws_durable_verify1`, 2×60с, mexc+gateio по 2 символа): оба сегмента с manifest'ами, stitched manifest `completed=true`, coverage 0.9984, 9,418 событий, `exit_reason=completed_all_segments`. Найден и исправлен баг порядка: финальный state теперь пишется ДО stitch (иначе в манифест попадал `still_running`).
- **Kill test** (`ws_durable_killtest`, 3×60с, hard kill посреди сегмента 2): см. результат ниже в истории agent-log — процесс убит без шанса на finally, state остался running/unknown, `finalize` постфактум собрал stitched manifest и вывел `killed_externally_inferred_stale_heartbeat`.

## Guards в durable wrapper

- `trading_edge_preflight.ps1 -Json` перед actual start, кроме resume.
- `trading_ws_collect_readiness.ps1` hard-gate для длинных запусков от 24ч; короткий verification 2-3ч помечается как `skipped_for_short_verification_run`, чтобы проверить runtime без ложной 72ч-readiness ошибки.
- Zero-line guard: стоп, finalize и `STOPPED_INCOMPLETE`, если к порогу нет raw lines.
- Schema probe: проверка JSONL полей `recv_ts/exchange/event_type/channel/symbol/payload`.
- Early density guard: проверка raw files, raw lines и lines/minute.
- Resume не склеивает дырку: завершенные `seg_NNN/manifest.json` пропускаются, незавершенный `seg_NNN` архивируется в `seg_NNN_incomplete_<timestamp>`, затем сегмент повторяется.

## Ограничения v2

- Между сегментами есть технологический gap ~секунды (reconnect+resubscribe) — учитывается в stitched manifest как `gaps`; для микроструктурных исследований границы сегментов исключать из event-окон.
- Сигнальный останов прерывает ран на границе сегмента; внутри сегмента процесс дорабатывает segment duration.
