# Trading MVP PIT countdown preflight

- Дата и время: 2026-07-30 21:18 +03:00
- Агент: Codex
- Запрос: продолжать continuous-production автономно, не запускать PIT-сегмент раньше exact окна и исключить дубликат visible writer.

## План

1. Проверить hash-bound countdown launcher и active schedule pointer.
2. Добавить fail-closed runtime preflight без запуска writer.
3. Проверить exact сегмент `pit_universe_v2_forward_20260731_n03`.

## Выполнено

- В `tools/start_approved_pit_segment_countdown_visible.ps1` добавлен `-PreflightOnly`.
- Preflight сверяет dynamic pointer, active-run gate, autopilot guard, exact run/plan/hash, approval binding, deadline, свободное место, launch/output absence и другие живые countdown owners.
- Обычный запуск теперь fail-closed разрешен только при `DUE` либо `eta_sec <= 300`.
- Повторный countdown или уже живой exact writer не дублируются.
- Preflight не пишет run/output artifacts.

## Измененные файлы

- `tools/start_approved_pit_segment_countdown_visible.ps1`
- `trading_mvp/tests/test_autopilot_visible_pipeline.py`

## Проверки

- PowerShell parser: PASS.
- 49 targeted unit tests: PASS.
- Exact `-PreflightOnly` для n03: `READY_NOT_DUE`, `checks_passed=true`, `launch_allowed_now=false`.
- Свободно на output drive: 779.851 GiB при минимуме 5 GiB.
- Ранний обычный запуск корректно отклонен до записи metadata/launch/output.
- Финальный guard: `ACTIVE`, weekly remaining 60%, n03 `WAITING`.
- Active-run gate: `READY_FOR_POSTPROCESS` для завершенного public-readonly probe.
- Живых PIT writers: 0.

## Риски и ограничения

- n03 нельзя запускать ранее 2026-07-31 00:55 +03:00; точное окно начинается в 01:00.
- Long-campaign branch остается на отдельном `USER_REVIEW_REQUIRED_CONTRACT_FREEZE` и не влияет на preapproved PIT.
- `STOPPED_INCOMPLETE` по-прежнему требует нового exact user approval.

## Следующему агенту

- В начале checkpoint повторить `tools/check_trading_mvp_autopilot.ps1 -Json`.
- При exact n03 `DUE` или `eta_sec <= 300` запустить один visible countdown тем же plan path/hash/run id.
- Не запускать второй countdown/writer; при `RUNNING` только контролировать status/ETA.
