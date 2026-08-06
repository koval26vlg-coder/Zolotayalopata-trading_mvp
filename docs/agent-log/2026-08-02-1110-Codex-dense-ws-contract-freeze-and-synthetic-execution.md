# Dense WS contract freeze and synthetic execution preparation

- Recorded the user's exact contract-freeze-only approval for proposal
  `a9ec751329e436c1ea30b63433c57cf0e9ffd35370a097735c9ce91f71bb40d7`.
- Frozen signal/evaluator contract:
  - contract hash: `b70975468fbd67acf550dea39aac21c116fb3a86a57ed56d400f40f0fa287954`
  - file SHA-256: `a9ef768d6f61297d01d8fe37a9d4e00b27cf5b2d52f122ab8ca9a0c3fae5a81d`
- Frozen non-executable PlanOnly:
  - plan hash: `620b1711a5436c722acea99d41c4b81ba57bd317069456282814939b3eefeea2`
  - file SHA-256: `2ae9f20892eeb65772aa40c8bee0c905935dd50af2c57e29232ecc9418168fdb`
- Bound both artifacts into the authoritative autopilot policy. Policy SHA-256 is
  `4f565a42f7b4fa651fb862c3abe2755ea7e21b2f4f33a6605e7836eee6c9ffc7`.
- Updated heartbeat automation so the contract freeze is not requested again.
- Added a synthetic-fixture-only execution realization implementation. It rejects
  every snapshot or BBO row without `fixture_only=true`, has no CLI or file reader,
  and cannot run the actual evaluator.
- Added the contract-freeze and synthetic execution tests to the bounded fast
  regression lane.

## Verification

- Frozen-file validator: `VALID_FROZEN_CONTRACT_AND_NON_EXECUTABLE_PLANONLY`.
- Linked unit tests: 31 passed.
- Fast regression: 245 passed, 0 failures, 0 errors, 0 skipped.
- Fast regression deterministic result hash:
  `85da86bbd2edadd70a499aaea844e47c6fd1686d710faeb483fd943bff50d561`.
- Final guard: `ACTIVE`, `WAIT_APPROVED_LONG_CAMPAIGN_WINDOW`, weekly remaining
  77%, no writer active, no action due.

## Safety boundary

- `evaluation_authorized=false` and `executable=false` remain frozen.
- No actual market data, returns, PnL, or OOS was read.
- No network collector, grid, retune, paper-forward, live orders, private API,
  real capital, leverage, or margin was used.
- After campaign quality and causal materialization, build one new run plan bound
  to exact output hashes and request only the exact evaluator approval.
