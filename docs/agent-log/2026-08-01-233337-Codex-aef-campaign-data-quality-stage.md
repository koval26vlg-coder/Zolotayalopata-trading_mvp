# Accelerated Evidence Factory v1: campaign data-quality stage

- Observed at: `2026-08-01T23:33:37+03:00`
- Actor: `Codex`
- Scope: bounded offline implementation and verification only

## Reconciled state

- User-authorized shutdown of `Antigravity.exe` and `language_server.exe` was completed before this checkpoint.
- Stale WS writers were not left alive; their partial datasets remain `diagnostic-only`.
- Reconciliation evidence:
  `docs/agent-log/visible-runs/stale-ws-sweep-reconciliation-20260801_220151206/reconciliation-evidence.json`
- Reconciliation evidence SHA-256:
  `6d9c6eb46fe3ff89b375be118201a55bf4ff6fcf7bc775bbfb6ecfaef100478`
- Active gate is neutral `READY_FOR_POSTPROCESS` for
  `resolved_incomplete_20260801_220204534`; no market-data writer is active.

## Implemented

- Added `trading_mvp/src/dense_ws_campaign_quality.py`.
- Bound the exact campaign-quality executor into AEF contract/PlanOnly tool
  provenance in `dense_ws_campaign_contract.py`.
- Added completed-campaign dispatch
  `RUN_DENSE_WS_CAMPAIGN_DATA_QUALITY` to `autopilot_guard.py`.
- Added the AEF contract, campaign-quality, global writer claim and guard tests
  to the fast regression lane.
- The evaluator is streaming and hash-bound. It validates the exact campaign,
  phases, segment manifests, raw envelope schema, payload encoding, timestamps,
  ordering/gaps, venue/base coverage and declared-versus-observed counts.
- It never reads returns, PnL or OOS artifacts and cannot promote an incomplete
  campaign. Invalid finalized segments are excluded; promotion is possible only
  when all frozen minimums still pass.
- Terminal outcomes are `DATA_READY_FOR_TRAIN_ONLY_REVIEW`,
  `REJECT_DATA_QUALITY`, or `STOPPED_INCOMPLETE`; hash/integrity conflicts fail
  closed.

## Verification

- Exact AEF suite: `69` tests, `OK`.
- Full fast regression lane: `207` tests, `206` passed and `1` unrelated
  existing failure.
- Residual failure: `test_run_mvp_exposes_fixture_only_routes` expects three
  fixture-only paper-observer routes in `trading_mvp/run_mvp.ps1`. This route
  gap is outside the AEF evidence contract and was not hidden or patched as part
  of this change.
- Python compilation: passed for the modified AEF/guard modules.
- Ruff: passed for the modified AEF source and directly related tests.

## Current guard and next action

- Weekly remaining: `91%`, telemetry fresh.
- PIT `pit_universe_v2_forward_20260802_n05` remains preapproved for
  `2026-08-02 01:00-01:20 +03:00`; it must not start early.
- No dense collector, network writer, replay, returns/PnL/OOS evaluation, grid,
  retune, paper-forward, live/private API, leverage or margin action was run.
- AEF production contract/PlanOnly is intentionally not frozen because the new
  hash-bound candidate has not received its exact contract-freeze approval.
- Pending candidate:
  `905f5f18a2028733894aef112ac857d7c1cecc005fc39ed8c55ac418beafcf5e`.
- Feasibility SHA-256:
  `3b2a4421c5548730b7974972395d80e0a543b36d95c04f2a045113bbb146d8ee`.
- Universe SHA-256:
  `ce3d78cac3aa084a23376ee26a39c8fc98655a262a701c0d4d5f00469f2bafe3`
  (`1388` rows).

