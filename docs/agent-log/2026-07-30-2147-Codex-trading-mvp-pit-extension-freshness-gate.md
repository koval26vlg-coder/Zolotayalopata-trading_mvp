# Trading MVP PIT extension freshness gate

- Дата: 2026-07-30 21:47:32 +03:00
- Агент: Codex
- Запрос: продолжать One-Week Historical Edge Sprint по continuous-production policy и не выдавать stale approval packet для будущего PIT schedule extension.

## Проблема

`pit_schedule_extension_candidate` декларировал
`requires_fresh_horizon_audit_before_approval=true`, но guard проверял только
неизменность audit/plan SHA. На открытии approval window 10 августа он мог
показать phrase из PlanOnly, основанного на quality ledger snapshot от 30 июля.

## Исправление

- `resolve_pit_schedule_extension` теперь fail-closed проверяет:
  - schema/mode horizon audit;
  - source schedule hash;
  - extension path, file SHA, plan hash, nights и inactive state;
  - способность proposed nights покрыть текущий audited train shortfall;
  - audit timestamp не раньше approval window;
  - audit age не более `3600` секунд;
  - audit quality-ledger SHA равен текущему ledger SHA.
- До окна freshness получает статус
  `REFRESH_REQUIRED_AT_APPROVAL_WINDOW`, а approval phrase скрыта.
- В окне stale audit переводит extension в
  `REFRESH_REQUIRED / BLOCKED_STALE_HORIZON`.
- Autopilot выдаёт routine action
  `REFRESH_PIT_SCHEDULE_EXTENSION_HORIZON`, без user notification.
- Exact approval request появляется только для `DUE + FRESH`.
- В standing policy добавлены explicit freshness limits и bindings.

## Изменённые файлы

- `trading_mvp/src/autopilot_guard.py`
  - SHA-256: `adc903e5d83318741aa9d1ea12552e97cbec0463413b67e783f6270872cb3e6b`
- `docs/plans/trading-mvp-autopilot-policy-v1.json`
  - SHA-256: `9c343f5cdc12225b9d86bc084f3d9dc1580f8921a52362d5681b34bc7251be84`
- `trading_mvp/tests/test_autopilot_guard.py`
  - SHA-256: `94cd947ae35eb0e211fade477fec8ccce0a278e115e78b5b87674a4717668491`
- `trading_mvp/tests/test_pit_schedule_horizon.py`
  - SHA-256: `69aed0c89636f61579c353ca9deaa2a796bff32a98ce604282d6fc70d94c59bd`
- `trading_mvp/tests/test_pit_postrun_policy.py`
  - SHA-256: `01da6f9115f0b63542dcd6eab16dba0bec0472129b79f6d9f674f1fd97540e94`

## Проверки

- Python compile: PASS.
- Policy JSON parse: PASS.
- Linked regression: `80` tests PASS.
- `git diff --check`: PASS.
- Реальный current-state guard:
  - extension `READY_FOR_APPROVAL / NOT_DUE`;
  - freshness `REFRESH_REQUIRED_AT_APPROVAL_WINDOW`;
  - current ledger SHA совпадает с audit ledger SHA;
  - approval phrase не раскрыта;
  - `schedule_approved=false`;
  - `automatic_launch_allowed=false`.
- Future-state simulation на `2026-08-10 19:10 +03:00`:
  - status `REFRESH_REQUIRED`;
  - approval `BLOCKED_STALE_HORIZON`;
  - reasons `audit_predates_approval_window`,
    `audit_age_exceeds_limit`;
  - approval phrase не раскрыта.

## Ограничения и следующий шаг

- Immutable audit/extension v1 не изменялись.
- При открытии approval window нужно построить новый PlanOnly audit/plan на
  текущем ledger, затем запросить одно exact hash-bound разрешение.
- До этого продолжать exact preapproved PIT schedule; n03 запускается только
  видимо при `DUE` либо `eta<=300 sec`.
- Returns/PnL/OOS, market payloads, grid/retune, live/private API не читались и
  не запускались.
