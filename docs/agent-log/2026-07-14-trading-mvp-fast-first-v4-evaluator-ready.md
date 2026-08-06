# trading_mvp Fast-First v4 evaluator ready

Date: 2026-07-14 13:12 +03:00  
Agent: Codex, manual mode; swarm disabled

## User request

Continue the frozen Fast-First v4 goal without running OOS before a separate explicit approval.

## Plan

1. Verify the active-run gate and canonical PlanOnly seal.
2. Finish the visible owned no-grid evaluation wrapper through TDD.
3. Verify fail-closed behavior and project regressions.
4. Register evaluator readiness without reading OOS metrics.

## Completed

- Added `tools/run_fast_first_v4_evaluation_visible.ps1`.
- Bound the wrapper to plan hash `5396885aa9abf77a461f20aa190c843b86be098b76abd6f3a5655a8f725eee60` and the canonical v4 PlanOnly artifact.
- Required `ConfirmedResearchRun`, `MaxRuntimeSec<=1800` and a fresh `ApprovedNotLaterThan` for an actual run.
- Added a visible `Start-Process -WindowStyle Normal` worker, one-time worker-token ownership, hard deadline, process-tree termination, two deterministic evaluations and atomic manifests/gates.
- Added fail-closed `STOPPED_INCOMPLETE` handling for timeout, evaluator failure, deterministic mismatch and manual/nonzero worker termination.
- Added v4 wrapper regression assertions to `trading_mvp/tests/test_powershell_tooling.py`.
- Updated the current goal so its next step is the separately approved visible OOS run, not implementation or collection.
- Archived the preceding gate state before readiness registration.

## Verification

- TDD RED: v4 wrapper test failed because the file was absent.
- TDD RED: ownership test failed before worker-token enforcement.
- TDD RED: nonzero-worker test failed before gate closure was implemented.
- Targeted tests: 34 passed, 0 failed.
- Fast shard: 177 passed, 0 failed in 32.882 seconds.
- PowerShell parser: PASS.
- PlanOnly wrapper smoke: PASS; no evaluator started.
- Missing `ConfirmedResearchRun`: FAIL_CLOSED.
- Direct worker without a valid ownership record/token: FAIL_CLOSED.
- Final gate check: `READY_FOR_POSTPROCESS`, decision `FAST_FIRST_V4_EVALUATOR_READY_OOS_NOT_RUN`.

## Evidence

- Evaluator readiness source: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\manifests\fast_first_v4_funding_pressure_evaluator_readiness_20260714_1258.json`.
- Owned-run readiness: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\manifests\fast_first_v4_owned_evaluation_readiness_20260714_131215.json`.
- Wrapper SHA-256: `ceed92667f506a447f05d09404b449f7eceb97c41c5d499fff325c3b284c05fe`.
- Input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`.

## Constraints and risks

- OOS evaluation was not started and OOS metrics were not read.
- Grid search, execution probe, paper-forward, live orders, API keys, leverage and margin remain disabled.
- `command_after_explicit_approval` currently points to a safe PlanOnly preview. An actual command must be generated only after the user explicitly approves the duration and hard deadline.
- The dirty worktree predates this step; unrelated changes were not reverted.

## Next agent action

Wait for a separate explicit OOS approval containing the requested duration (maximum 1800 seconds) and deadline. Then run exactly one visible owned no-grid evaluation. Do not retune, collect new data or auto-chain a probe.
