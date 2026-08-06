# trading_mvp: visible 10-date PIT futility worker

Timestamp: `2026-07-17T02:28:00+03:00`

## Result

- Added `tools/run_pit_futility_visible.ps1`.
- Added owned child-action gate support in `trading_mvp/run_mvp.ps1` for:
  - `fast-edge-pit-futility-plan`
  - `fast-edge-pit-futility-evaluate`
- Added `trading_mvp/tests/test_pit_futility_visible.py`.
- The worker is visible, deadline-bounded (`MaxRuntimeSec <= 1800`), immutable-output and ownership-token guarded.
- It seals the earliest 10 accepted PIT dates and reads event frequency / executable-entry eligibility only.
- It never reads returns or PnL and never runs OOS, grid, retune, network collection, execution probe, paper-forward or live actions.
- Final decisions:
  - `PIT_FUTILITY_BRANCH_CLOSED`
  - `PIT_FUTILITY_CONTINUE_TRAIN_ACCRUAL`
- Default checkpoint identity is derived from the earliest ten accepted certification IDs, not from the mutable full ledger hash.
- Appending dates after the checkpoint cannot change its `run_id` or artifact paths.
- `PlanOnly` validates and reuses an existing final checkpoint instead of proposing a duplicate run.
- The state machine fails closed if the ten-date checkpoint was missed or accepted dates exceed the 20-date train boundary.

## Current real state

- `active-run gate`: `READY_FOR_POSTPROCESS`.
- Accepted quality dates: `2` (`2026-07-14`, `2026-07-15`).
- Real PlanOnly decision: `wait_for_tenth_quality_date`.
- No futility plan/result/manifest was written by the real PlanOnly check.
- Corrected rate-fix schedule remains unapproved:
  - plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_primary_immutable_sources_planonly_20260716_234212.json`
  - plan hash: `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1`
- Stale automation `pit-visible-night-segments` remains `PAUSED`; no collector was started.

## Verification

- TDD RED: new suite failed because wrapper/ownership wiring did not exist.
- New wrapper tests: `9/9 OK`.
- Affected regression suites: `42/42 OK`.
- PowerShell parser: `OK` for wrapper and `run_mvp.ps1`.
- Python compile: `OK`.
- Sealed rate-fix schedule runtime tools: `12/12` hashes match.
- Full suite: `910` tests ran, `5` skipped, one unrelated transient Windows `WinError 5` during `os.replace` in the existing execution-probe collector test.
- The single failing execution-probe test passed immediately in isolation: `1/1 OK`; no unrelated production change was made.

## File hashes

- `tools/run_pit_futility_visible.ps1`: `bb376467145ae461f1c7e4c04bf924c9935ddec7fb326209a70af89413105f80`
- `trading_mvp/run_mvp.ps1`: `6009d0af2e5c93e3ed79acd7b7cdf1ee1aa24836ca155cd5dc2c3f9d4c3749b1`
- `trading_mvp/tests/test_pit_futility_visible.py`: `6d4db9f1ac641790c766bc277ad3ec77389dc213fc6f389de073dc92ea214f86`

## Next allowed transition

1. Obtain exact immutable approval for schedule hash `b33e6989...`.
2. Reactivate/update the paused automation only after that approval.
3. Collect one visible 20-minute segment per new calendar date and certify technical quality.
4. At 10 accepted dates, run `tools/run_pit_futility_visible.ps1`; no new approval is required for this local deterministic no-grid checkpoint.
5. Continue to 20-date train feasibility only if the futility verdict is `CONTINUE_TO_20_DATE_TRAIN_GATE`.
