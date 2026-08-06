# trading_mvp basis-v2 visible launcher ready

- recorded_at: 2026-07-16T10:12:18.2405695+03:00
- agent: Codex
- goal_state: active
- hypothesis_id: cross_venue_perp_basis_convergence_1h_v2
- plan_path: E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_094355.json
- plan_hash: 710307b8dbb49f05089e1f3bccbb597c7107bfc505d2cf3e9488d7fa738c7faa
- plan_file_sha256: c864ceebb531f7614cb9c97fce34e25140f98dbe9edaba7dbaf22aab18bb25e9
- launcher: C:\Users\koval\Documents\ZolotyayLopata\tools\start_historical_basis_v2_collect_visible.ps1
- launcher_guards: hash-bound plan validation, explicit approval window, visible terminal, unbuffered progress, hard deadline, disk guard, single-writer lease, PIT schedule overlap guard, immutable launch record, STOPPED_INCOMPLETE on interruption, resume-only continuation.
- gate_fix: owned_run_gate now preserves approved_night_schedule and rejects conflicting immutable schedule pointers.
- parser_check: POWERSHELL_PARSE_OK
- targeted_regression: 29/29 passed
- full_regression_partition_1: 691/691 passed across 94 modules
- full_regression_partition_2: 137/137 passed across 17 modules
- full_regression_total: 828/828 passed across 111 modules
- real_planonly_decision: AWAIT_EXPLICIT_BASIS_V2_HISTORY_COLLECT_APPROVAL
- real_planonly_requests: 360
- real_planonly_estimated_runtime_sec: 750
- real_planonly_max_runtime_sec: 1200
- real_planonly_free_gb: 780.535
- real_planonly_integrity: active gate SHA256 unchanged; no launch record; no run directory; collector_started=false; network_access=false.
- collector_status: NOT_STARTED
- next_step: one explicitly approved visible public-history collect on run_id basis_v2_history_20260716_a01; no grid/OOS/live/private API keys.
- independent_shadow_track: PIT schedule hash 14f687e8e8491bb58c1e697d9a467d89ab360f6b683782caca43f8b33a0684a0 must remain immutable.

