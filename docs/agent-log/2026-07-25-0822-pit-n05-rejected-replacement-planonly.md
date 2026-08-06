# PIT n05 rejection and replacement PlanOnly

- Recorded: 2026-07-25 08:20:38 +03:00
- Rejected run: `pit_universe_v2_forward_20260724_n05`
- Resolution: `REJECTED_INCOMPLETE`; 3/4 cycles and 5,247 rows remain diagnostic-only.
- Failure: `OSError [Errno 22] Invalid argument`; old schedule plan `32aa73fe5af72c18eda78f6010165debd8be8b8a19d38101da97a484cf95bd61` is not resumable because its sealed collector SHA no longer matches the corrected collector.
- Archived gate: `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\archived-gates\active-run-gate.pit_universe_v2_forward_20260724_n05.rejected-incomplete.20260725_081822035.json`.
- Source preserved: manifest SHA-256 `3e1f1cdb142429a4fbe05f63ec406edf6fa49ae3b21e330955c20154e55970cc`; snapshots SHA-256 `2abcf543315e7c5994e3205fe1219e49f46e34848016e67d3e7e1e747bbff315`.
- Replacement PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_replacement_planonly_20260725_0820.json`.
- Replacement plan hash: `9a888ce80c9cd7ba53eb803195bf28f03d77ec3e9a10b4357abca6418c1fc165`; file SHA-256 `7ca3b4c97d1d219826f10abdf9ac55487178190e9c6c54a80634796aacceef0a`.
- Replacement segment: `pit_universe_v2_forward_20260725_n01`, 2026-07-25 23:00-23:20 +03:00, 4 expected cycles.
- Corrected collector SHA-256 sealed in plan: `442c65ee0ba5aa924e7fc7ea77d94b4067e3d3d9169a16a193af0cbd933c1b93`.
- Validation: `VALID`; current accepted distinct dates 3; 17 dates remain before train feasibility.
- Tests: 24/24 passed (`test_resolve_active_run`, `test_night_schedule_plan`, `test_pit_universe_snapshot_collector`).
- Authority boundary: `schedule_approved=false`, `collection_started=false`. No countdown, collector, returns, PnL, OOS, grid, live orders or private API keys were used.
- Next action: exact hash-bound approval of the replacement schedule, then rebind the night automation and launch only the visible segment in its sealed window.
- Read-only segment authorization preflight: `AUTHORIZED`; this does not constitute schedule approval.
- Stale heartbeat `pit-visible-night-segments` was paused because it remained bound to invalid plan `32aa73fe...`; rebind and reactivate only after approval of `9a888ce8...`.
