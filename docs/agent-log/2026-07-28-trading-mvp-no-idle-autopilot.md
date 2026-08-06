# trading_mvp no-idle autopilot

Date: 2026-07-28

## Current state

- Active-run gate: `READY_FOR_POSTPROCESS`.
- Last PIT run: `pit_universe_v2_forward_20260728_n01`.
- Technical result: `4/4` cycles, `7012` rows, `0` errors.
- PIT accepted dates: `4/20`.
- Replay remains blocked: `replay_allowed=false`.
- Weekly quota guard: `PAUSED_WEEKLY_LIMIT`, `14%` remaining at final verification, reset at `2026-08-04 08:32:35 +03:00`.
- Next research task remains unclaimed: `paper_code_provenance_merkle_v2`.

## Implemented

- Added the repository-wide no-idle rule to `AGENTS.md`.
- Added deterministic catalog derivation from immutable readiness-audit recommendations.
- Activated research catalog `trading_mvp_autopilot_research_catalog_20260728_v3`.
- Updated heartbeat `pit-visible-night-segments` to `Trading MVP no-idle autopilot`.
- The heartbeat remains active during quota pause and resumes the queue automatically after an authoritative reset reports more than `15%` remaining.
- While an approved PIT segment is waiting and quota is above the threshold, the heartbeat processes bounded offline tasks instead of waiting.
- Only critical contract changes, terminal hypothesis verdicts, integrity failures, or live/private-capital decisions require user participation.

## Verification

- Autopilot guard/backlog/catalog/queue/visible-pipeline tests: `31/31` passed.
- Catalog v3 file SHA-256: `029522cc54b755ff8150102b66f7d5ba9d5a674771454e057f15140571d525e7`.
- At and below the `15%` boundary, guard correctly refused to claim a new research task.

## Resume behavior

The heartbeat checks the guard every 20 minutes. After the weekly reset, it resumes automatically if `remaining_percent > 15`, prioritizes an exact due PIT segment, otherwise claims the next bounded offline task. It must not start live orders, private API work, leverage, margin, grid, retune, or unapproved OOS.
