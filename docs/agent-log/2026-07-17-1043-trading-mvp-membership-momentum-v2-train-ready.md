# trading_mvp membership-momentum-v2 train adapter ready

Date: 2026-07-17 10:43 +03:00

## Status

- The user-approved membership-v2 public probe had already completed before this work unit: `1/1`, `1,387` rows, `0` errors.
- Membership-v2 is terminally closed as `INSUFFICIENT_SOURCE_QUALITY`: resolved delisted-end coverage is `0.3830`, below the frozen `0.90` gate. It was not relaunched.
- Active-run gate remains `READY_FOR_POSTPROCESS`; `replay_allowed=false`; no live writer exists.
- Frozen membership-v3 archive-source PlanOnly remains the only next network action:
  - path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_v3_20260717_0845.json`
  - plan hash: `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`
  - run id: `gate_membership_v3_archive_source_20260717_0845`
  - runtime cap: `600s`.
- The v3 network probe, archive payload history, real train, OOS, grid, paper and live actions were not run. No edge is proven.

## Implementation

- Added `trading_mvp/src/gate_membership_momentum_v2_train.py` as a separate hash-bound train-only adapter for the membership-v3 `20d warm-up / 100d train / 100d sealed OOS` contract.
- Preserved the existing strategy without retuning: `30d` lookback, `7d` holding period, `7d` rebalance, minimum `5` assets per side, conservative normal/stress cycle costs `46/72 bps`.
- The 120-day train view supports at most `12` independent weekly rebalance events. The frozen feasibility minimum is derived as `10` events (`80%` schedule coverage) and the artifact explicitly reports limited statistical power.
- The PlanOnly accepts only a final hash-valid membership-v3 quality ACCEPT, validates causal train lifecycle masking, hashes every train input and contains no OOS path.
- The evaluator reads only train artifacts, is deterministic and fail-closed. Negative economics closes the branch without retune; a feasible result can only request a separate hash-bound OOS PlanOnly.
- Added bounded offline CLI routes:
  - `fast-edge-membership-momentum-v2-train-plan`
  - `fast-edge-membership-momentum-v2-train`
- Module SHA-256: `1512998e7492e8229363b5afebd1bcf5214700fb982f0ed6909827b11e563d88`.
- Test SHA-256: `5b0cb82574fe1f9e7fc8df1c7c222cbbfcdfc4c6d9d55c0c8da14db12ac61f03`.

## Verification

- New TDD suite: `6 OK`.
- Related membership/momentum regressions: `33 OK`.
- Python compile: passed.
- PowerShell parser: passed.
- Full offline suite: `1017 OK`, `5 skipped`, `0 failed`, runtime `307.637s`.

## Next gate

The v2 probe approval cannot authorize a v3 run. The next network action requires the existing exact v3 approval and must run visibly. Source ACCEPT may unlock a separate history PlanOnly; it never auto-runs history, train or OOS.

Exact approval phrase:

`Подтверждаю visible Gate archive-membership v3 public probe plan_hash=e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3, run_id=gate_membership_v3_archive_source_20260717_0845, MaxRuntimeSec=600, public archive metadata only, без archive payload/returns/OOS/grid/live/private API keys.`