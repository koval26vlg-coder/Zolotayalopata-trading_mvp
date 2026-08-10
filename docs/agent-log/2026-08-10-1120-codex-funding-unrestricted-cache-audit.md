# Funding unrestricted cache audit

- Funding asset policy remains unrestricted: every coin and category is eligible; Binance listing status is not an exclusion rule.
- MEXC/Gate venue scope and official same-underlying identity, data quality, liquidity, capacity and cost gates remain unchanged.
- `funding_pairs.py` now pins an omitted analysis timestamp to immutable `manifest.params.end_sec` instead of the workstation clock.
- The pre-OOS all-cached-assets summary contains 110 shared symbols and 108 analyzed pairs at `2026-07-20T06:05:04+00:00`.
- Pair summary SHA-256: `ae268021c11a40a0b7a3ddb6b82a547af45fe12cda2561633084f8f1972d96ae`.
- Feasibility audit decision: `CURRENT_CACHE_FIXED_HOLD_STRESS_INSUFFICIENT`.
- At the frozen 20-day horizon, 11 pairs cover normal costs and 2 cover stress costs; the gate requires 4.
- The fourth-best cached stress break-even is 29 days. This is an upper-bound screen, not returns/PnL or OOS evaluation.
- Audit SHA-256: `2cbf49cacda2effffd50849efbd33efb9fa0074dc6287ed547deb05a0aa0c749`.
- The current cache is not proven to contain every MEXC/Gate funding asset, so this result does not reject the unrestricted funding strategy.
- No collector, network market data, OOS value read, evaluator, returns/PnL, grid/retune, execution probe, paper/live, private API, capital, leverage or margin action occurred.
- Funding regressions: 78/78 passed; Python compile and `git diff --check` passed.
