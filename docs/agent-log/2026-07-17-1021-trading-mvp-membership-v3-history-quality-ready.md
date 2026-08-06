# trading_mvp membership-v3 history quality ready

Date: 2026-07-17 10:21 +03:00

## Status

- Active-run gate is `READY_FOR_POSTPROCESS`; no live collector or monitor process exists.
- Membership-v2 remains closed as `INSUFFICIENT_SOURCE_QUALITY` because delisted-end coverage was `0.3830 < 0.90`.
- Frozen membership-v3 source PlanOnly remains hash-valid and re-authorizes offline:
  - plan path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_v3_20260717_0845.json`
  - plan file SHA-256: `d31ea79c8757387e6f1b89562b0fcb4e53d09b127dacfc6990bcdeb9ee01793e`
  - plan hash: `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`
  - run id: `gate_membership_v3_archive_source_20260717_0845`
  - candidates: `364`; metadata probe tasks: `189`; runtime cap: `600s`.
- The v3 source probe was not launched. No network access, archive payload read, returns, PnL, OOS, grid, paper or live action occurred in this work unit.

## Implementation

- Added a separate hash-bound membership-v3 archive-history quality PlanOnly/evaluator in `trading_mvp/src/gate_historical_membership_v3_history_quality.py`.
- Added `20d warm-up / 100d train / 100d sealed OOS` with five fixed 20-day OOS folds to the v3 history contract.
- Quality PlanOnly validates final collector provenance without reading archive payload.
- Quality evaluation normalizes Gate candle/funding archives, infers funding cadence only from the frozen allowed intervals, applies coverage gates and never computes returns, signals or PnL.
- Missing delisted lifecycle end can be resolved only from the last valid closed archive hour; no synthetic tail or interpolation is allowed.
- Train manifest masks lifecycle events first observed after the train boundary. The sealed OOS manifest retains the full lifecycle commitment, preventing future delisting leakage into train.
- Global quality rejects when resolved delisted-end coverage is below `0.90`, even if at least 20 assets otherwise pass.
- Added `fast-edge-membership-v3-history-quality-plan` and `fast-edge-membership-v3-history-quality` routes to `trading_mvp/run_mvp.ps1`, both capped at `1800s`.

## Verification

- Targeted membership-v3 history suite: `14 OK`.
- Related v1/v2/v3 source, closure, legacy history, momentum train/OOS and survivorship regression: all passed.
- Python compile: passed.
- PowerShell parser for `trading_mvp/run_mvp.ps1` and visible v3 source launcher: passed.
- Full suite: `1011 tests OK`, `5 skipped`, `0 failed`, runtime `302.530s`.
- Full-suite log: `C:\Users\koval\AppData\Local\Temp\trading_mvp_full_tests_20260717.log`.

## Next gate

The only next network action remains the exact-approved visible 600-second v3 public archive-metadata probe. A history PlanOnly can be created only after a final source `ACCEPT`; history collection then requires its own visible hash-bound approval. Quality does not auto-run train or OOS. No trading edge is proven at this stage.

Exact approval phrase:

`Подтверждаю visible Gate archive-membership v3 public probe plan_hash=e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3, run_id=gate_membership_v3_archive_source_20260717_0845, MaxRuntimeSec=600, public archive metadata only, без archive payload/returns/OOS/grid/live/private API keys.`
