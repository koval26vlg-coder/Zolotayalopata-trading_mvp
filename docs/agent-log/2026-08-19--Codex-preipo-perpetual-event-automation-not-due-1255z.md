# Codex pre-IPO perpetual event automation not due 12:55Z

Time: 2026-08-19T12:55:23Z

Heartbeat wake ran exactly one scheduled visible orchestrator from `C:\Users\koval\Documents\ZolotyayLopata`:

`pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_preipo_perpetual_event_automation_visible.ps1 -ScheduledTick -Json`

The orchestrator returned `NOT_DUE`, `pending_retry=false`, next interval `2026-08-19T13:50:35.751909Z`. This wake did not launch a collector, retry loop, or writer claim.

Status readback showed the prior due launch `preipo_automation_20260819T124528Z` completed successfully with `worker_exit_code=0`, `worker_alive=false`, visible terminal PID `24980`.

Latest due outcomes: OKX `COMPLETE`, 3 contracts seen/selected, 2789 events written. Contract counts: `ANTHROPIC-USDT-SWAP=1046`, `MOONSHOT-USDT-SWAP=1042`, `OPENAI-USDT-SWAP=683`. Gate `COMPLETE`, 0 contracts, 0 events, no retry reason.

Cadence: `CONFIRMED`, reason `official_event_confirmed_without_near_exact_time`, interval `3600s`. Accrual readback: `contracts_seen=3`, `events_written=2789`, `official_events=3`, `proxy_events=0`, `complete_events=0`. Final state has `pending_retry=false`, `retry_count=3`, `attempt_count=6`, `last_error=null`.
