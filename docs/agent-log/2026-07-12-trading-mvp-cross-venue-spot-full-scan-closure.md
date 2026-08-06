# trading_mvp cross-venue spot full-scan closure

- Time: 2026-07-12 20:03 +03:00
- Agent: Codex, manual mode; swarm cancelled by user.
- Scope: existing-data verification only; no collect, grid, live orders, API keys, leverage, margin, replay, or paper-forward.

## Work

- Confirmed that the requested visible full scan had already completed on 2026-07-08 with a final manifest and exit code 0.
- Added `trading_mvp/src/cross_venue_full_scan_audit.py` and fail-closed unit tests.
- Bound the migrated report and manifest by full SHA-256.
- Compared the E: clean-slice source with the original C: source using size plus first/middle/last sampled fingerprints.
- Recomputed retained candidate gross edge, net edge, and capacity math.

## Decision

`CROSS_VENUE_SPOT_FULL_SCAN_VERIFIED_REJECTED_NO_NET_EDGE_AFTER_BASE_COSTS`

Audit:

`E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_venue_spot_full_scan_audit_20260712_200342.json`

SHA-256:

`51c2a3739340bda4a81362e6f44d50455dc944f69a0ef4d53937ae98130ccb68`

The strongest liquidity-qualified event had gross `46.7189 bps`, net `-22.2811 bps` at the fixed `69 bps` hurdle, and `-2.2811 bps` even after removing the `20 bps` inventory/rebalance buffer. Therefore OOS, walk-forward, and paper-forward are not valid next steps for this branch.

## Verification

- New targeted tests: `5/5` passed.
- Targeted gate/router regression: `21/21` passed.
- Fast project shard: `135/135` passed.
- Audit failures: none.
- Source copy sampled fingerprint match: true.
- Strategy accepted: false.

## Next

Close the spot branch and select a new structural hypothesis PlanOnly using existing data. Do not rerun or grid-tune this rejected branch without a material source/cost-model change.
