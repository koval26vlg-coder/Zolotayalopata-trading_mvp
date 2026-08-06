# trading_mvp membership-momentum-v2 execution-probe runtime ready

- Date: 2026-07-17 13:25 +03:00
- Agent: Codex
- Scope: bounded offline implementation and verification only

## Source gate readback

- `gate_historical_membership_v2_20260717_055756` was not relaunched.
- The final source verdict remains `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Delisted-end coverage remains `0.3830`, below the frozen `0.90` gate.
- Active-run gate remains `READY_FOR_POSTPROCESS`; `replay_allowed=false`.
- No membership-v3 source probe, archive payload collection, OOS, grid, paper or live action ran.

## Implemented

- Added a hash-bound execution-probe window PlanOnly, public Gate depth collector and raw-depth evaluator.
- Each accepted window is frozen to 20 minutes, 5-second cadence and 240 cycles.
- The evaluator recomputes quote age, timestamp skew, both-side depth impact and capacity from raw JSONL.
- All three frozen windows must pass for every causally selected asset; partial or missed windows cannot produce ACCEPT.
- Added `run_mvp.ps1` routes for window planning, visible collect handoff and offline evaluation.
- Added a visible PowerShell wrapper with progress, active-run gate ownership, immutable outputs and `STOPPED_INCOMPLETE` handling.
- Direct network execution through `run_mvp.ps1` is fail-closed and only prints the exact visible-wrapper command.

## Verification

- Targeted execution-probe tests: `20 OK`, then wrapper/route smoke: `7 OK`.
- Adjacent OOS/train/selection/market-snapshot/gate tests: `56 OK`.
- Full regression: `1052 OK`, `5 skipped`, `0 failures`, runtime `321.111 sec`.
- PowerShell AST parse passed for `run_mvp.ps1` and the new visible wrapper.
- PlanOnly smoke did not mutate gate/current-run and did not create samples or manifest.

## Boundaries and next step

- This implementation is infrastructure, not evidence of a profitable edge.
- A real execution-probe PlanOnly cannot be created until a real hash-valid historical OOS ACCEPT exists.
- The only currently permitted next network action remains the separately approved visible membership-v3 archive-source probe with plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- The user's v2 approval cannot authorize v3 or any execution window because run_id and plan hash differ.
