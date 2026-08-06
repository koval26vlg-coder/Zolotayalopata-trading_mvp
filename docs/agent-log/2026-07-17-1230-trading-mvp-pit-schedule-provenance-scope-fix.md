# trading_mvp PIT schedule provenance scope fix

Date: 2026-07-17 12:30 +03:00

## State

- Active run gate is `READY_FOR_POSTPROCESS` for `gate_historical_membership_v2_20260717_055756`.
- The v2 public probe was not launched again: its existing final artifact has 1/1 cycle, 1,387 rows, and 0 transport errors.
- The v2 source remains terminally rejected: delisted-end coverage is 0.3830 versus the frozen 0.90 quality gate. Returns, OOS, grid, and live actions remain forbidden for that branch.

## Change

- Updated `trading_mvp/src/night_schedule_plan.py` so current-hash enforcement is limited to the collection data plane: visible wrapper, collector, and public probe client.
- Governance-only planner/status/quality tools and unrelated `CostProfile` changes are retained as recorded provenance but no longer invalidate an already sealed collection schedule.
- The current sealed hypothesis contract is still compared against the recorded contract, so material strategy drift remains fail-closed.
- Added regression tests for tolerated governance drift, rejected collector drift, tolerated unrelated hypothesis-bank drift, and rejected sealed-contract drift.

## Verification

- Night schedule tests: 35 passed.
- Full suite: 1,040 passed, 5 skipped, 0 failed in 314.710 seconds.
- Ratefix schedule status now returns `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`, not a false source-hash mismatch.
- Ratefix primary plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_primary_immutable_sources_planonly_20260716_234212.json`.
- Ratefix plan hash: `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1`.
- No collector, OOS, replay, grid, paper-forward, live order, or private API action was launched.

## Next boundaries

- Gate archive-membership v3 is the only next network action for the rejected membership-v2 branch and requires its exact hash-bound approval.
- PIT ratefix nightly accrual is a separate shadow-track and requires the exact schedule approval before any segment can be authorized.
