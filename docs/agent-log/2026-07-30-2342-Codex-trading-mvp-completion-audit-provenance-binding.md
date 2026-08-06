# trading_mvp completion-audit provenance binding

Observed at: `2026-07-30 23:41 +03:00`

## Request

Continue the active One-Week Historical Edge Sprint autonomously while the next
approved PIT segment is not yet due.

## Guard

- Autopilot: `ACTIVE`
- Weekly remaining: `46%`
- PIT schedule: `WAITING`
- Next run: `pit_universe_v2_forward_20260731_n03`
- ETA at final audit launch: `4703 sec`
- Long-campaign checkpoint remained unchanged and already notified:
  `critical_checkpoint_notification_required=false`

## Gap

The completion audit consumed `trading-mvp-autopilot-state.json`, including its
status, quota, and schedule context, but did not:

- include that source file in `evidence_hashes` / input Merkle;
- fail closed when its `schedule_window` referred to another pointer, plan,
  contract, stage, accepted-date count, target, or run;
- bind the audit result to the implementation files that computed schedule and
  quality state.

## Change

Updated:

- `trading_mvp/src/one_week_sprint_completion_audit.py`
- `trading_mvp/tests/test_one_week_sprint_completion_audit.py`

Added:

- schema/project/timezone validation for the autopilot state;
- exact pointer/plan/hash/hypothesis/data/stage/contract/count/run binding;
- fail-closed handling for inconsistent pending/no-pending states;
- `autopilot_state` SHA-256 in `evidence_hashes`;
- implementation SHA-256 values for:
  - `one_week_sprint_completion_audit.py`
  - `night_schedule_status.py`
  - `night_schedule_quality.py`
- regression coverage for valid binding, zero accepted dates, naive timestamps,
  foreign plan hashes, foreign run ids, and contradictory no-pending states.

## Verification

- Focused completion-audit tests: `16/16` passed.
- Linked audit/status/guard/postrun/visible-pipeline tests: `77/77` passed.
- Python compile check passed.
- Deterministic repeat matched both input Merkle and deterministic state hash.

Canonical new immutable audit:

- path:
  `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\reports\one_week_sprint_completion_audit_20260730_234138.json`
- file SHA-256:
  `c5306129bbdb109fa238763ed778fa113c2d0645f0c7bc19fea8fb096665a973`
- input Merkle:
  `4f9764213c7e44b9cabb4f1231f2a4de351bd7221a05420396a202e322ce5263`
- deterministic state hash:
  `cf4c71b32e50d204bef1b2b8233f81948cf706a06503f22c3db99e68597f5151`
- completion:
  `HISTORICAL_SPRINT_TERMINAL_PIT_TRAIN_ACCRUAL`
- accepted dates: `4/20`
- next run: `pit_universe_v2_forward_20260731_n03`

The earlier same-checkpoint audit files remain immutable historical snapshots;
the `234138` artifact supersedes them because it includes complete code
provenance.

No returns/PnL were read, OOS was not run, and no collector, grid, retune,
paper/live action, private API key, leverage, or margin action occurred.

## Next

Keep the goal active. Re-read the guard at the next checkpoint and start only
the exact n03 segment when it is `DUE` or within five minutes of its approved
window.
