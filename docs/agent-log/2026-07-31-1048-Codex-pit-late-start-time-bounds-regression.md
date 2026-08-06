# PIT late-start time-bounds regression

- Checked at: `2026-07-31T10:47:44+03:00`
- Scope: local deterministic tests only; no collector, network, replay, returns/PnL/OOS, grid, retune, paper, live, private API, leverage, or margin.
- Production runtime contract: unchanged.
- Dense-WS contract/PlanOnly: unchanged and not launched.

## Change

- Extended the night-schedule quality fixture with a minute-level timestamp shift.
- Added a positive regression proving a delayed segment remains certifiable when every artifact timestamp stays within `start_local..hard_deadline_local` plus the sealed clock-skew allowance.
- Added a fail-closed regression proving artifacts after the hard deadline are rejected with `segment_time_bounds_mismatch`.

## Verification

- `test_night_schedule_quality.py` plus linked schedule plan/status/approval and visible-pipeline suites: `47 passed`.
- Authoritative guard after verification: `ACTIVE`; PIT postrun disposition `COMPLETE`.
- Long-campaign branch remains review-gated and was not modified.
