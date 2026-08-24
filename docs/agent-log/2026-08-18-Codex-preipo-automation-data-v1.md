# Pre-IPO automation data v1 — bounded implementation

Дата: 2026-08-18  
Ветка: `preipo_perpetual_event`  
Статус: `READY_FOR_VISIBLE_PUBLIC_PAPER_RESEARCH_NOT_TICKED`

## Реализовано

- `trading_mvp/src/preipo_adapters.py`
  - pure fixture-friendly normalizers для OKX и Gate;
  - только explicit equity/pre-IPO markers, чтобы обычный crypto prelaunch не попал в этот трек;
  - REST endpoints и public WebSocket subscriptions;
  - BBO/depth/trades/ticker/mark/index/funding/open-interest normalization;
  - exchange timestamp и received timestamp хранятся раздельно;
  - official announcement parser не принимает proxy как official.
- `trading_mvp/src/preipo_raw_event_store.py`
  - append-only JSONL;
  - deterministic `event_id`, duplicate suppression без перезаписи;
  - stale/out-of-order updates сохраняются с `causal_status=stale`;
  - hash-bound manifest.
- `trading_mvp/src/preipo_automation.py`
  - bounded discovery/snapshot tick;
  - optional bounded public WebSocket slice;
  - отдельные state/attempts/manifest paths;
  - `RETRY_NEXT_INTERVAL` и `PARTIAL_RETRY_NEXT_INTERVAL` без tight-loop;
  - writer claim helpers и duplicate protection.
- `tools/start_preipo_perpetual_event_automation_visible.ps1`
  - отдельный visible `-ScheduledTick`, `-Status`, `-PreflightOnly` и worker;
  - exact PlanOnly hash check;
  - active-run gate check;
  - visible terminal через `Start-Process -WindowStyle Normal`;
  - сохранение state/ledger/launch record при ошибках.
- PlanOnly обновлён: OKX/Gate active, Bybit candidate-only, все новые implementation bindings зафиксированы.

## Тесты и проверки

- TDD RED: импорты новых модулей падали ожидаемым `ModuleNotFoundError` до реализации.
- New package: `25 passed`.
- Existing crypto pre-market regression: `21 passed`.
- `py_compile` для пяти Python-модулей: exit code 0.
- PowerShell parser: `PS_PARSE_OK`.
- `-Status -Json`: `IDLE`, worker отсутствует, accrual counters нулевые.
- `-PreflightOnly -Json`: `ok=true`, `PLAN_OK`, gate `READY_FOR_POSTPROCESS`.

## Immutable bindings

Plan hash: `f4fb50bb8c97c86ec729bd1ad9727aa69b3ce7ea53063112fc88e837c33a1ca4`  
Plan file SHA-256: `4e4d2db78120463e640f7ee0a453084aff36abf390f424528275ba82d61c31a9`  
Visible launcher SHA-256: `a965e03396a0dcfe8b51b6b21c7d9c6e7bea9ea4796e5d0ef0d8d1c3b0b1948e`

## Граница запуска

`-ScheduledTick` и network collector в этой bounded фазе не запускались. Внешнее состояние, raw event store и retry state останутся неизменными до отдельного явного запуска. Crypto pre-market и spot Listing Momentum automation не вызываются этим orchestrator и не блокируются его ошибками.
