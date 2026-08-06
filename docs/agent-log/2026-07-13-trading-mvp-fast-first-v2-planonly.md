# trading_mvp Fast-First v2 PlanOnly

Date: 2026-07-13
Agent: Codex, manual mode; swarm disabled

## Gate

- Active gate verified as `READY_FOR_POSTPROCESS`.
- Previous decision remains `FAST_FIRST_NO_EDGE_FOUND`.
- Replay, grid, execution probe, paper-forward, API keys and live orders remain blocked.

## New fixed hypothesis

Selected `venue_local_perp_residual_dispersion_reversion_v1`, a same-venue market-neutral perpetual relative-value branch.

The branch is not a retune of funding/basis, listing-event, slow-liquidity, HFT/order-book, daily momentum, capitulation or MEXC/Gate spot-dislocation evidence. Funding cannot be the alpha source because price-only net after costs is an acceptance gate.

## Sealed evidence

- Dataset: `E:\ZolotyayLopata-data\exports\trading-mvp\daily\daily_forward_20260713`
- Dataset manifest SHA-256: `3c7794dcf11dd2b456614c614d263fe1498292d7b364e281371ead79e6c23466`
- Input Merkle SHA-256: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`
- Frozen universe: 97 non-Binance perpetual contracts after excluding `CRCLX`, `NVDAX`, `QQQX` synthetic proxies.
- MEXC coverage: 43 contracts, 200 calendar days.
- Gate coverage: 54 contracts, 201 calendar days.
- Plan path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v2\plans\fast_first_residual_dispersion_planonly_20260713.json`
- Plan hash: `a73a54627477030bea0d4c57395c717cf74b1a243862ef9f8726356780e50566`
- Plan file SHA-256: `3abde96e8b6aa279c74268edcb558d6a5012bb09251d7a1a695ba66f373a4115`

## Economics and boundary

- MEXC normal/stress cycle: `65/84 bps`.
- Gate normal/stress cycle: `75/92 bps`.
- No OOS returns or candidate performance were calculated in this step.
- Current-universe survivorship limits a future passing verdict to `ACCEPT_FOR_SHORT_EXECUTION_PROBE` only.
- Next allowed work: implement and unit-test the hash-bound no-grid evaluator; do not execute it yet.

## Evaluation completion

- Evaluator implementation passed leakage, seal, cost-profile, split, verdict and visible-run tests before OOS execution.
- Visible run `fast_first_v2_residual_dispersion_20260713_1845` completed two deterministic evaluations.
- Verdict: `INSUFFICIENT_DATA`.
- Closed OOS coverage: 59/60 days after excluding the still-open 2026-07-13 candle.
- Frozen liquidity threshold produced no eligible cross-section: Gate 200/200 and MEXC 199/199 days skipped for `insufficient_eligible_markets`.
- Signals/events: 0/0. No performance claim is possible.
- Full regression: 538 passed, 5 skipped; Python compile, PowerShell parsers and `git diff --check` passed.
- Next allowed command family: `new-fast-first-hypothesis-planonly`; no retuning of this branch on the same evidence.
