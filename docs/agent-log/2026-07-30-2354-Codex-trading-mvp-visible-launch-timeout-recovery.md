# trading_mvp visible-launch timeout recovery

Observed at: `2026-07-30 23:53 +03:00`

## Scope

Bound the heartbeat behavior around the new visible-terminal ownership
handshake without starting the not-yet-due n03 segment.

## Decision

No additional owner-checker tool was created. The existing exact invocation:

`tools\start_approved_pit_segment_countdown_visible.ps1 -PreflightOnly`

already revalidates the pointer, plan/hash, guard, disk, gate, and process
owners and returns `NO_RUN_OR_OUTPUT_WRITES`. Reusing it avoids a second,
potentially divergent ownership implementation.

## Automation

Updated `trading-continuous-production` while preserving:

- status: `ACTIVE`
- cadence: every 20 minutes
- target thread and all existing safety/approval limits

Actual launch now requires:

- top-level countdown invocation without `-VisibleChild`;
- tool timeout of at least 60 seconds for the 30-second ownership handshake;
- exact `VISIBLE_TERMINAL_LAUNCHED`,
  `terminal_ownership_verified=true`, and matching run id.

Any timeout or ambiguous result must first be resolved by exact
`-PreflightOnly` plus guard/metadata. Actual launch cannot be repeated until
those sources prove that no live exact countdown/writer owner exists.

## Verification

- Automation file contains the 60-second timeout requirement.
- Automation file binds timeout recovery to exact `-PreflightOnly`.
- `NO_RUN_OR_OUTPUT_WRITES` and no-repeat-until-owner-proof are explicit.
- Final guard:
  - autopilot: `ACTIVE`
  - weekly remaining: `45%`
  - n03 status: `WAITING`
  - n03 ETA: `3993 sec`
  - action due: `false`
  - critical notification required: `false`

No collector, output, returns/PnL/OOS, grid, retune, paper/live action, private
API key, leverage, or margin action occurred.
