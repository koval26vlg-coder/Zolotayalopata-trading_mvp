# Trading MVP PIT post-run hardening

- Дата и время: 2026-07-30 21:26 +03:00
- Агент: Codex
- Запрос: продолжать One-Week Historical Edge Sprint без простоя, сохраняя exact hash-bound PIT schedule, embargo и ручное согласование schedule extensions.

## План

1. Проверить post-run orchestration для ближайшего n03.
2. Найти fail-open пути до quality commit, train gate и schedule continuation.
3. Исправить их и выполнить bounded dry verification.

## Выполнено

- `run_trading_mvp_pit_postrun.ps1` теперь до любой мутации проверяет active dynamic pointer: status, plan path/hash, hypothesis, data type, collection stage и sealed ledger path.
- Runtime post-run требует совпадающий `current-run`, `READY_FOR_POSTPROCESS`, `final=true`, `expected_outputs_complete=true`, `stop_reason=completed`, exact manifest path и exact approved schedule binding.
- Удалён fail-open путь, который сам вызывал `-ConfirmedNightScheduleApproval` и продвигал pointer на continuation schedule.
- При исчерпании approved schedule post-run теперь ставит `PIT_SCHEDULE_EXTENSION_REQUIRES_EXACT_USER_APPROVAL`, не выдаёт approval и не меняет pointer.
- Quality ledger дополнительно проверяется по frozen `hypothesis_contract_sha256`, а не только по hypothesis/data track.
- `Get-AcceptedDates` в orchestration fail-closed отклоняет записи другого frozen contract.

## Измененные файлы

- `tools/run_trading_mvp_pit_postrun.ps1`
- `trading_mvp/src/night_schedule_quality.py`
- `trading_mvp/src/night_schedule_quality_dry_run.py`
- `trading_mvp/tests/test_night_schedule_quality.py`
- `trading_mvp/tests/test_pit_postrun_policy.py`

## Проверки

- PowerShell parser: PASS.
- Python compile: PASS.
- 67 linked regression tests: PASS.
- Exact n03 post-run `-PlanOnly`: `PLAN_VALIDATED`.
- Exact plan hash: `31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7`.
- Accepted train dates: 4/20.
- `returns_read=false`, `pnl_read=false`, `mutation=false`.
- Guard: `ACTIVE`, weekly remaining 59%, n03 `WAITING`.
- Живых PIT writers: 0.

## Риски и ограничения

- n03 остаётся календарно независимым наблюдением и не запускается ранее `DUE` либо `eta_sec <= 300`.
- Schedule extension требует свежего horizon audit и exact user approval; post-run больше не может обойти это правило.
- Train feasibility запускается только ровно при 20 accepted distinct dates; OOS остаётся закрытым до отдельного hypothesis-level checkpoint.
- Long-campaign branch `dense_ws_microstructure_regime_filter_v1` не изменён и всё ещё требует отдельного contract freeze.

## Следующему агенту

- В начале checkpoint перечитать autopilot guard.
- При n03 `DUE` или `eta_sec <= 300` запустить один visible countdown exact plan/hash/run.
- После writer позволить countdown вызвать hardened exact post-run; при `RUNNING` не запускать второй process.
