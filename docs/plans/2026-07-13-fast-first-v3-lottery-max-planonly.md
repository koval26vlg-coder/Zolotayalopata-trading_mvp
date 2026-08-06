# trading_mvp Fast-First v3 lottery-MAX PlanOnly

Date: 2026-07-13
Mode: PlanOnly, research-only, no OOS performance access

## Goal

Freeze one genuinely new non-Binance structural-edge hypothesis before any train/OOS performance calculation. Do not alter thresholds or reuse the alpha logic of funding/basis, listing-event, slow-liquidity, HFT/order-book, large-move breakout, daily momentum, capitulation, cross-venue dislocation/lead-lag or residual-dispersion branches.

## Frozen hypothesis

`venue_local_lottery_max_factor_v1`

Among liquid and seasoned non-Binance perpetuals on the same venue, contracts with the largest single-day upside return during the prior 20 closed days are temporarily overpriced by lottery demand and underperform low-MAX peers during the next five closed days after full base-tier execution costs.

This is distinct because:

- funding and basis cannot be alpha inputs;
- listing date, listing age and post-listing windows are absent;
- liquidity is used only for candidate quality and capacity, not as shock/compression/reclaim alpha;
- no order-book, trade-flow, HFT, breakout or latency feature is used;
- no cross-venue price comparison is used;
- cumulative-return momentum is not the main score;
- no one-day residual shock or residual-dispersion convergence is used;
- a frozen residualized robustness test controls for cumulative return and log liquidity.

## Frozen signal

- Venues: MEXC and Gate independently.
- Instrument: USDT linear perpetual, fully collateralized `1x` research assumption.
- Feature: `MAX20`, the maximum close-to-close log return over the 20 completed days ending at `t`.
- Candidate pool: top 12 markets by trailing 30-day median quote volume, minimum 8.
- History: minimum 60 prior closed days.
- Capacity: every selected leg must have trailing median quote volume at least `$5,000,000`, equivalent to a `$500` proxy.
- Portfolio: long two lowest `MAX20`, short two highest `MAX20`, equal `$500` notional per leg.
- Entry: next daily open after signal close.
- Exit: fifth daily close after entry.
- Rebalance: every five days from frozen anchor `2026-02-24`; no overlap.
- Grid, TP/SL and parameter selection on train or OOS are absent.

## Economics

One portfolio contains four perp legs and eight orders. It is conservatively charged as two complete two-leg cycles under the unified `base_api` CostProfile, including maker-fill probability, taker fallback, spread, impact, slippage and two rebalance buffers.

| Venue | Normal cost | Stress cost |
|---|---:|---:|
| MEXC | `$6.50` per `$2,000` gross portfolio | `$8.40` |
| Gate | `$7.50` per `$2,000` gross portfolio | `$9.20` |

Funding is only an unavoidable cash flow. Price-only OOS PnL after costs must be positive; favorable funding is halved in stress and funding cannot exceed 25% of positive OOS PnL.

## Frozen validation

- Train: `2025-12-26..2026-05-13`, 139 closed calendar days.
- OOS: `2026-05-14..2026-07-12`, 60 closed calendar days.
- Walk-forward: five consecutive 20-day folds after a 99-day initial train; no refit.
- Minimum OOS events: 20 total, 10 per venue and 10 unique rebalance dates.
- Both venues must have positive OOS net expectancy.
- OOS profit factor `>=1.2`; positive portfolio-event rate `>=60%`.
- At least 4/5 combined folds and 3/5 folds per venue must be positive.
- Normal, residualized-score robustness and stress PnL must all remain positive after costs.
- Maximum OOS drawdown: 10% of peak allocated collateral.
- Top event/base positive-PnL share: at most 25%; venue share: at most 75%.
- Break-even holding period: at most five days.
- Missing seal, coverage, events, candidate pool or capacity produces `INSUFFICIENT_DATA`, not acceptance.

## Evidence seal

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v3\plans\fast_first_lottery_max_planonly_20260713.json`.
- Plan hash: `3f086ac9c0f59c9690a63870f03ba44543559e08271333e73ae7957e86e240f7`.
- Plan file SHA-256: `619fc4be2cb69f8afb30b714cb065782e8dcfe94adc5b8ab969b6ecf300b0252`.
- Input Merkle SHA-256: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`.
- Inputs verified: 195/195 files; previous residual-dispersion plan remained unchanged.
- Experiment ledger: `exp_20260713_183747_991e58a62c2b`, verdict `untested`, OOS status `not_evaluated`, metrics `{}`.

## Boundary

Current-universe survivorship remains unresolved. Even a full historical pass can authorize only `ACCEPT_FOR_SHORT_EXECUTION_PROBE`, never paper or live. Evaluation, grid, execution probe, paper-forward, API keys, live orders, leverage and margin remain blocked.

## Next allowed step

Implement and unit-test a deterministic hash-bound no-grid evaluator. Tests must cover no look-ahead, exclusion of open daily bars, exact eight-order costs, five-day non-overlap, fixed split/folds and fail-closed verdict logic. OOS execution remains prohibited until those tests pass.

## Evaluator readiness

Status at 2026-07-13: implementation and tests complete; real OOS not run.

- Evaluator: `trading_mvp/src/lottery_max_evaluator.py`.
- Canonical plan and 195-file Merkle seal revalidated without calculating returns or signals.
- Exactly one frozen configuration is supported; both `main` and residualized `robustness` scores are evaluated with no grid/refit.
- Direct evaluation requires an owned visible gate with decision `FAST_FIRST_V3_EVALUATION_RUNNING`; the current PlanOnly gate rejects a direct call.
- Synthetic evaluator tests: 10 passed, including deterministic repeat, no-look-ahead, closed-bar exclusion, five-day non-overlap, four-leg funding/cost accounting and verdict ordering.
- Targeted regression: 55 passed. Full project regression: 549 passed, 5 skipped.
- Readiness artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v3\manifests\fast_first_v3_lottery_max_evaluator_readiness_20260713.json`.
- Gate: `FAST_FIRST_V3_EVALUATOR_READY_OOS_NOT_RUN`; `evaluation_allowed=false` until a new explicit user request.

The next action is not automatic OOS. A new explicit request is required to prepare an owned visible no-grid evaluation run.
