# trading_mvp autonomous PIT autopilot

- Time: 2026-07-28 11:15 +03:00
- Agent: Codex
- Request: remove routine confirmations and idle blocking, automate continuation, stop new work when the weekly Codex quota has 15% or less remaining, and resume after reset.

## Implemented

- Added account-wide weekly quota telemetry for the Codex 10080-minute window.
- Added an inclusive guard: `remaining_percent <= 15` produces `PAUSED_WEEKLY_LIMIT`.
- Added one-time pause notification state and automatic `ACTIVE` transition after fresh post-reset telemetry reports more than 15% remaining.
- Added a standing autonomous policy and canonical project goal.
- Added a dynamic immutable schedule pointer.
- Added a visible post-run chain:
  `collector -> quality dry-run -> sealed quality commit -> WAITING_EVENT / same-hypothesis continuation / train-feasibility verdict`.
- Updated the visible PIT countdown to re-check weekly quota immediately before collector launch and to run postprocess in the same visible terminal.
- Updated heartbeat `pit-visible-night-segments` to read the dynamic pointer, stay active as a low-frequency reset watchdog, avoid repeated confirmations, and stop only at a critical checkpoint.

## Current State

- Active gate: `READY_FOR_POSTPROCESS`.
- Last run: `pit_universe_v2_forward_20260728_n01`, final `4/4`, `7012` rows, `0` errors.
- Accepted PIT dates: `4/20`.
- Current approved plan: `31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7`.
- Next due segment: `pit_universe_v2_forward_20260729_n01`, 2026-07-29 01:00-01:20 +03:00.
- Current weekly telemetry at verification: used `23%`, remaining `77%`, reset 2026-08-04 08:32:35 +03:00.
- No collector, OOS, grid, replay, probe, paper-forward, live order or private API action was started during this change.

## Verification

- New weekly/autopilot unit tests: `10/10 PASS`.
- Night-schedule and PIT-quality regression tests: `40/40 PASS`.
- Visible-wrapper and collector regression tests: `17/17 PASS`.
- Post-run and countdown PlanOnly smoke: `2/2 PASS`.
- Full legacy discovery over 157 test files exceeded 10 minutes and left a child test process; PID 10548 was verified by command line and stopped. No data writer was involved.

## Next Agent

- Do not ask for daily approval.
- At 00:55 +03:00 the active heartbeat must run the weekly guard and exact due-segment authorization.
- At weekly remaining quota `<=15%`, start nothing new and retain the heartbeat as a minimal reset watchdog.
- At a hypothesis-level accept/reject verdict, integrity conflict, or before any live/private-key/capital action, stop and request user review.

## 17:59 Follow-up

- Fixed a false pause caused by a two-hour telemetry freshness window. Daily
  watchdog telemetry is now valid for 30 hours; an authoritative completed
  `resets_at` infers a fresh weekly window until the first post-reset event.
- Real guard returned to `ACTIVE`, weekly remaining `75%`.
- Added a read-only completion auditor and `5` focused tests.
- Verified all `7/7` closed-branch evidence hashes.
- Deterministic completion audit repeated with identical input Merkle and state
  hash.
- Current objective remains active at
  `HISTORICAL_SPRINT_TERMINAL_PIT_TRAIN_ACCRUAL`, PIT `4/20`.

## 18:09 Preflight Hardening

- Validated immutable schedule
  `31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7`
  and authorization for `pit_universe_v2_forward_20260729_n01`.
- Added mandatory `authorize-segment` enforcement inside the visible countdown
  wrapper at initial preflight and again when the collection window opens.
- Duplicate/certified dates now fail closed even if the wrapper is invoked
  outside the heartbeat; the exact Python rejection reason is preserved.
- Verified the future segment with a mutation-free PlanOnly smoke and verified
  rejection of the already accepted `2026-07-28` segment.
- Regression result: `38/38 PASS`; PowerShell parser result: `VALID`.
- Preflight created no launch record, countdown metadata or output directory.
- Weekly quota at final verification: `66%` remaining; autopilot remains
  `ACTIVE`. No collector was started before the approved window.

## 18:14 Recovery Audit

- Verified that transient MEXC/Gate endpoint failures are captured inside the
  public probe as per-venue errors; they do not terminate the 20-minute
  collector.
- Verified append-safe same-run resume: immutable run identity, manifest
  schema, contiguous cycle journal, stale lock ownership and remaining active
  duration are validated before append.
- Kept disk, schema, missing-journal and data-integrity failures fail-closed.
  A blind automatic retry would hide the failure mode and is not allowed.
- Recovery/collector tests: `10/10 PASS`; public-probe tests: `12/12 PASS`;
  quota/countdown tests: `13/13 PASS`.
- Final state: no writer process, gate `READY_FOR_POSTPROCESS`, quota `63%`,
  next approved segment remains `20260729_n01` at `01:00`.

## 18:19 Event-Driven Guard

- Fixed the guard state from the ambiguous
  `CONTINUE_NEXT_ALLOWED_ACTION` to `WAITING_SCHEDULE_WINDOW` while the next
  immutable segment is not due.
- Added deterministic schedule-pointer resolution with plan-hash matching,
  accepted-date filtering, expired-segment skipping, exact run id, ETA and
  hard deadline.
- Added `action_due`: `false` while waiting, `true` only after the approved
  window opens. This is separate from `stop_new_actions`, so postrun remains
  available and weekly/safety pauses retain priority.
- Invalid pointer/plan/ledger state now returns
  `CRITICAL_STOP_INVALID_SCHEDULE` fail-closed.
- Real guard result: `WAITING_EVENT`, next run
  `pit_universe_v2_forward_20260729_n01`, PIT `4/20`, no writer.
- Regression result: `42/42 PASS`; Python compile check passed.
