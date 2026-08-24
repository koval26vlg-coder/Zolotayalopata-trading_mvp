# Codex Pre-IPO Perpetual Event Automation Fire 2026-08-19 01:02Z

Run time: 2026-08-19T04:07:54+03:00.

Executed exactly one visible scheduled tick from the project root:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_preipo_perpetual_event_automation_visible.ps1 -ScheduledTick -Json
```

Launch returned `VISIBLE_TERMINAL_LAUNCHED` with visible terminal PID `51684`, plan hash `1206bac931f944eb8cb97465ea716ff86bab7423a4f068da2666a0a1609aab86`, expected duration `420` seconds, and launch record `docs\agent-log\run-gates\preipo_perpetual_event_automation.launch.json`.

Final status via `-Status -Json`: `COMPLETE`; worker exit code `0`; `pending_retry=false`; `retry_count=0`; `attempt_count=1`; `last_error=null`.

Per-venue outcomes:

- `okx`: `COMPLETE`; contracts seen/selected `3/3`; events written `2772`.
- `gate`: `COMPLETE`; contracts seen/selected `0/0`; events written `0`.

OKX websocket captures:

- `ANTHROPIC-USDT-SWAP`: `953` events, duration `101.2166793346405` seconds.
- `MOONSHOT-USDT-SWAP`: `1058` events, duration `101.18548202514648` seconds.
- `OPENAI-USDT-SWAP`: `743` events, duration `90.99570536613464` seconds.

Accrual counts: `contracts_seen=3`, `events_written=2772`, `complete_events=0`, `official_events=3`, `proxy_events=0`.

Next interval from final state: `2026-08-19T04:07:25.117574Z`.

Artifacts:

- State: `docs\agent-log\run-gates\preipo_perpetual_event_automation_state.json`
- Ledger: `docs\agent-log\run-gates\preipo_perpetual_event_automation_attempts.jsonl`
- Manifest: `exports\trading-mvp\preipo-perp\manifest.json`
- Events: `exports\trading-mvp\preipo-perp\raw_events.jsonl`
