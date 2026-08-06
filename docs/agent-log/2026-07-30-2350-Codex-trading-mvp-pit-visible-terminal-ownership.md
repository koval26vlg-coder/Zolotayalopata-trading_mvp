# trading_mvp PIT visible-terminal ownership

Observed at: `2026-07-30 23:49 +03:00`

## Request

Continue the One-Week Historical Edge Sprint without idle work and preserve the
mandatory visible-writer contract for the next preapproved PIT segment.

## Finding

`tools/start_approved_pit_segment_countdown_visible.ps1` streamed progress to
its current console, but a heartbeat can invoke that script inside an invisible
tool process. In that call path, the script name alone did not guarantee that
the countdown, writer, and postrun were visible to the user.

The 12 frozen runtime tools and the immutable schedule were not changed.

## Change

Updated:

- `tools/start_approved_pit_segment_countdown_visible.ps1`
- `trading_mvp/tests/test_autopilot_visible_pipeline.py`
- heartbeat automation `trading-continuous-production`

The top-level countdown now:

1. Performs all existing read-only exact pointer/plan/hash/guard/disk/duplicate
   checks.
2. Refuses launch before `DUE` or the five-minute threshold.
3. Opens a separate `pwsh` with `WindowStyle Normal` and `-NoExit`.
4. Passes internal `-VisibleChild` only to that terminal.
5. Waits up to 30 seconds for exact countdown metadata whose
   `countdown_pid` equals the spawned terminal PID.
6. Returns `VISIBLE_TERMINAL_LAUNCHED` only after ownership is verified.
7. Keeps collector and postrun execution inside that visible child.

The heartbeat prompt now explicitly forbids passing `-VisibleChild` itself or
running a writer inline inside its invisible tool process.

## Verification

- PowerShell parser: passed.
- Focused visible-pipeline tests: `11/11` passed.
- Linked visible/guard/postrun/status/completion tests: `78/78` passed.
- Exact n03 `-PreflightOnly`:
  - status: `READY_NOT_DUE`
  - launch allowed: `false`
  - sealed runtime tools: `12/12`
  - side effects: `NO_RUN_OR_OUTPUT_WRITES`
- Final guard:
  - autopilot: `ACTIVE`
  - weekly remaining: `45%`
  - schedule: `WAITING`
  - next run: `pit_universe_v2_forward_20260731_n03`
  - ETA: `4228 sec`
  - action due: `false`
- n03 countdown metadata, launch record, and output directory remain absent.
- Automation remains `ACTIVE` on its existing 20-minute cadence.

No collector, returns/PnL/OOS, grid, retune, paper/live action, private API key,
leverage, or margin action occurred.

## Next

At `DUE` or within five minutes, invoke the top-level countdown without
`-VisibleChild`. Accept a new launch only when it returns exact
`VISIBLE_TERMINAL_LAUNCHED`, matching `run_id`, and
`terminal_ownership_verified=true`; otherwise re-read guard/metadata and do not
create a duplicate.
