# AEF exact contract-freeze blocked checkpoint

- Recorded local: `2026-08-02T01:32:00+03:00`
- Goal state: `blocked` after the third consecutive identical checkpoint.
- Blocker: exact hash-bound contract-freeze decision for
  `dense_ws_microstructure_regime_filter_v1_20260802_aef`.
- Candidate contract hash:
  `905f5f18a2028733894aef112ac857d7c1cecc005fc39ed8c55ac418beafcf5e`.

## Evidence

- Authoritative guard remains `ACTIVE` with decision
  `USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT`.
- Contract and immutable PlanOnly are absent; `actual_collection_allowed=false`.
- The bounded research backlog is exhausted: `50/50` tasks completed and no
  READY or CLAIMED task remains.
- PIT n06 is not due. It remains an independent preapproved segment scheduled
  for `2026-08-03T01:00:00+03:00` through `01:20:00+03:00`.
- Heartbeat automation `trading-continuous-production` is `ACTIVE`, targets the
  current thread, and wakes daily at `00:55` local to service the PIT window.

## Unblock condition

- Resume only after an exact decision for the current candidate hash. Generic
  continuation does not freeze the contract or authorize collection.
- After exact freeze approval, build and validate immutable Contract/PlanOnly
  without starting the campaign. Long-campaign launch remains a separate exact
  approval checkpoint.

## Safety

- This checkpoint did not create Contract/PlanOnly, start a collector, read
  returns/PnL/OOS, run grid/retune, or enable paper/live/private API/leverage/
  margin actions.
