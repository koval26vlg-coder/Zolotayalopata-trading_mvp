# Evaluator input hash binding

Date: 2026-08-17

Scope: slow liquidity listing momentum forward evaluator.

Changes:

- Bind evaluation output to the validated forward state SHA-256.
- Bind evaluation output to the frozen evaluator plan hash and file SHA-256.
- Build an input manifest hash from the state, monitor plan, baseline binding, and tick manifest file hashes.
- Reject stale or tampered evaluation cache entries instead of reusing them by window count.
- Add regression coverage for changed state content with the same complete-window count and for tampered cache content.

Verification:

- `python -m unittest trading_mvp.tests.test_slow_liquidity_listing_momentum_forward_evaluator` -> 8 tests passed.
- `python -m unittest trading_mvp.tests.test_slow_liquidity_listing_momentum_forward_monitor` -> 10 tests passed.
- No network or long-running collector was started.
