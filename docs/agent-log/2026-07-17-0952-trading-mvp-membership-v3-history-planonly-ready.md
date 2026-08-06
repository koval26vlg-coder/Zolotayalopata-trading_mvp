# trading_mvp membership-v3 history PlanOnly ready

Date: 2026-07-17 09:52 +03:00

## State

- Active-run gate: `READY_FOR_POSTPROCESS`; no live worker exists.
- Membership-v2 is closed as `INSUFFICIENT_SOURCE_QUALITY`: delisted-end coverage `0.3830` is below the frozen `0.90` gate.
- Frozen membership-v3 archive-source PlanOnly remains unchanged:
  - plan hash: `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`
  - run id: `gate_membership_v3_archive_source_20260717_0845`
  - plan path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_v3_20260717_0845.json`
- The v3 public archive-metadata probe has not been launched. Exact hash-bound approval is still required.

## Implemented offline

- Added `trading_mvp/src/gate_historical_membership_v3_history_plan.py` (`908f6eb2f2e7aa612d401ce58ecdfca15c53fa2e0939fae399cb2cc424ef5628`).
- Added `trading_mvp/src/gate_historical_membership_v3_history_collector.py` (`bf84fe15b1a8581b90cc701b9d2f1cb643c06625ec0e5a0d0fbf6a33fd7e4abb`).
- Added visible launcher `tools/start_gate_historical_membership_v3_history_collect_visible.ps1` (`f53db34b4041374cc17e5c55b9f19166ffe3a4215f699b64a31733ce49dd82bd`).
- Extended `trading_mvp/run_mvp.ps1` with offline history-plan routing and a fail-closed direct history-collect route.
- Added `trading_mvp/tests/test_gate_historical_membership_v3_history_plan.py`.

The history planner accepts only a final, source-quality-accepted v3 report whose plan, module, artifact and task hashes match. It never reads prices, returns, signals, PnL or OOS. Missing delisted lifecycle ends remain `archive_observed_pending`; no date is invented. The collector is public-archive-only, bounded, resumable and cache/hash-bound.

## Verification

- Existing frozen v3 source plan re-authorized with its original plan and module hashes.
- Visible launcher PlanOnly smoke: `network_access=false`, `collect_started=false`; no manifest or process was created.
- Targeted v3 and legacy history regression: `30 OK`.
- Full suite: `1006 OK`, `5 skipped`, `0 failed`, runtime `298.170s`.
- Full-suite log: `C:\Users\koval\AppData\Local\Temp\trading_mvp_full_tests_20260717_094544.log`.
- PowerShell parsing and Python compilation passed.

## Next allowed network action

Only the exact-approved visible 600-second v3 public archive-metadata probe may run. It must not download archive payloads or read returns/OOS/PnL. If source quality rejects, close the branch. If it accepts, generate the separate hash-bound full-history PlanOnly; do not auto-start history collection or evaluation.

