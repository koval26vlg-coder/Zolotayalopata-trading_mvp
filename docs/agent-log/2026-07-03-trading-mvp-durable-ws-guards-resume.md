# 2026-07-03 17:32 +03:00 - Codex - durable WS guards/resume

## Запрос

Перед новым 72ч run интегрировать guards старого visible-контура в durable WS path, добавить механизм перезапуска/продолжения после остановки, уведомление об остановке и возможность продолжить из консоли.

## Что сделано

- `tools/start_ws_collect_durable.ps1` заменен на guarded visible monitor-wrapper:
  - `-PlanOnly` не стартует collector и показывает команду actual run;
  - actual run требует `-ConfirmedLongRun`;
  - старый `STOPPED_INCOMPLETE` не заменяется молча: нужен явный `-ReplaceStoppedIncomplete`;
  - wrapper пишет `active-run-gate.json`, `launch.json`, stdout/stderr, `state.json`, stitched manifest path;
  - при остановке пишет `STOPPED_INCOMPLETE.txt`, `notification_required=true`, `alert_path`, `resume_command`;
  - продолжение из консоли: `start_ws_collect_durable.ps1 -RunId <run_id> -Resume -ConfirmedLongRun`.
- В durable path перенесены guards:
  - `trading_edge_preflight.ps1` перед actual start;
  - 72ч readiness hard-gate для long run;
  - zero-line guard;
  - raw JSONL schema probe;
  - early-density guard.
- `trading_mvp/src/ws_durable_collector.py` получил resume-семантику:
  - завершенные `seg_NNN/manifest.json` пропускаются;
  - незавершенный retry target архивируется в `seg_NNN_incomplete_<timestamp>`;
  - stitched manifest игнорирует архивные incomplete dirs;
  - добавлен `plan-symbols` для разрешения universe CSV в `exchange:symbols`.
- `tools/watch_ws_collect_durable.ps1` теперь показывает resume command, stale heartbeat alert и содержимое `STOPPED_INCOMPLETE.txt`.
- `tools/check_active_run_gate.ps1` теперь выводит durable поля: `resume_command`, `durable_status_command`, `state_path`, `alert_path`, `notification_required`.
- `docs/ws-durable-collect-runbook.md` обновлен под v2 visible/durable протокол.
- Тесты сделаны gate-aware для реального `STOPPED_INCOMPLETE`.

## Проверки

- `start_ws_collect_durable.ps1 -TotalSec 7200 -SegmentSec 3600 -PlanOnly` прошел, actual command включает `-ReplaceStoppedIncomplete` при текущем stopped gate.
- `start_ws_collect_durable.ps1 -TotalSec 259200 -SegmentSec 10800 -PlanOnly` прошел, показывает 24 сегмента.
- `python -m py_compile trading_mvp/src/ws_durable_collector.py` прошел через выбранный Python.
- `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/run_trading_tests.ps1`:
  - `Ran 294 tests in 92.235s`
  - `OK (skipped=8)`

## Текущий gate

`active-run-gate.json` остается `STOPPED_INCOMPLETE` для старого run `ws_collect_72h_sweep_visible_20260702_101730`. Новый durable verification run не запускался.

## Следующий шаг

Если пользователь подтверждает verification run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_ws_collect_durable.ps1 -TotalSec 7200 -SegmentSec 3600 -Exchanges "mexc,gateio" -UniversePath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" -MaxSymbols 300 -MaxPairsPerExchange 16 -UpdateInterval "100ms" -ConfirmedLongRun -ReplaceStoppedIncomplete
```

Если run остановится, использовать `resume_command` из gate/launch/alert.
