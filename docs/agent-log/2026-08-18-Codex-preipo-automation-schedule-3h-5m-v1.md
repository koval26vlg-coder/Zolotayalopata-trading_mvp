# Pre-IPO automation schedule — 3-hour interval / 5-minute capture

Дата: 2026-08-18  
Ветка: `preipo_perpetual_event`  
Статус: `ACTIVE_SCHEDULE_READY_IDLE`

## Зафиксированный режим

- один visible `ScheduledTick` каждые 10 800 секунд (3 часа);
- каждый тик ограничен 300 секундами (5 минут) public WebSocket capture с REST fallback;
- 300 секунд — общий бюджет тика, распределяемый между eligible-контрактами, а не 300 секунд на каждый контракт;
- OKX и Gate active, Bybit остаётся candidate-only;
- spot Listing Momentum и crypto pre-market automation этим расписанием не запускаются;
- при ошибке сохраняются append-only attempt, state, manifest и claim; retry переносится на следующий трёхчасовой интервал без tight-loop.

## Automation

- Codex automation id: `zolotyaylopata-pre-ipo-perpetual-event-monitor`;
- kind: project cron, status `ACTIVE`;
- schedule: every 3 hours;
- command: `pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_preipo_perpetual_event_automation_visible.ps1 -ScheduledTick -Json`;
- project target: `local-67524eb34e2cae2fcbc3c7e431f00843`.

## Verification

- PlanOnly: `PLAN_OK`;
- plan hash: `1206bac931f944eb8cb97465ea716ff86bab7423a4f068da2666a0a1609aab86`;
- plan file SHA-256: `4d1ab8ddbb5eb9fae6dc6aea5813e2f0e7825351a08f71063baf2fe7143f1e4b`;
- active-run gate: `READY_FOR_POSTPROCESS`;
- PowerShell parser: `PS_PARSE_OK`;
- focused pre-IPO and crypto pre-market regression tests: `40 passed`;
- launcher status after setup: `IDLE`, worker absent, accrual counters zero (no tick has fired yet).

State and attempt paths remain:

- `docs/agent-log/run-gates/preipo_perpetual_event_automation_state.json`;
- `docs/agent-log/run-gates/preipo_perpetual_event_automation_attempts.jsonl`;
- `exports/trading-mvp/preipo-perp/raw_events.jsonl`;
- `exports/trading-mvp/preipo-perp/manifest.json`.
