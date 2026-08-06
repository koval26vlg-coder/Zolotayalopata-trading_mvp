# trading_mvp membership v2 closure and v3 source PlanOnly

- Visible v2 public probe completed: `1,387` rows, `0` process errors, final source decision `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Unique diagnostic view: `1,353` symbols, `516` delisted, `315` missing end timestamps, delisted-end coverage `38.95%` versus frozen `90%` gate.
- Duplicate adapter defect isolated: `34` exact duplicate symbols, `0` conflicting duplicates. Fixing duplicates does not repair lifecycle coverage.
- Immutable closure created and independently validated: `INSUFFICIENT_SOURCE_QUALITY`, no history/OOS/retune/live.
- One bounded archive-source repair PlanOnly frozen: `plan_hash=e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- v3 scope: `364` candidates, `25` sampled symbols, `189` HEAD/Range-fallback tasks, `MaxRuntimeSec=600`, public archive metadata only.
- v3 probe not started; exact hash-bound approval is still required.
- Verification: focused `14 OK`; related Gate pipeline `62 OK`; Python compile and PowerShell parse passed.
- Analysis: `docs/analysis/2026-07-17-gate-membership-v2-source-closure-and-v3-planonly.md`.
