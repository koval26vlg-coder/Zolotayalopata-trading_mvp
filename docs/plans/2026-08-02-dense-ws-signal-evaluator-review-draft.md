# Dense WS signal/evaluator review draft

Status: `DRAFT_NOT_FROZEN_NOT_AUTHORIZED`

This document prepares the next critical review without reading campaign data,
returns, PnL, or OOS. It is not an evaluator contract and cannot authorize an
evaluation run.

## Plain-language idea

The campaign first finds moments when MEXC and Gate both have fresh, tight, and
active order books. During only those moments, the candidate signal checks
whether one venue can be bought at its current ask while the other can be sold
at its current bid for the same asset. The observed difference must then cover
the already frozen fees, slippage, and inventory-rebalancing allowance.

This reuses the existing `cross_venue_dislocation` research formula under the
new causal `DENSE_BOTH` filter. It does not introduce a new venue, universe,
market type, data source, cost model, or risk model.

## Candidate signal, one combination only

For every immutable execution snapshot with `regime_label=DENSE_BOTH`, evaluate
both directions:

1. Buy MEXC ask and sell Gate bid.
2. Buy Gate ask and sell MEXC bid.

For each direction:

```text
gross_edge_bps = (sell_bid / buy_ask - 1) * 10000
capacity_quote = min(buy_ask * buy_ask_qty, sell_bid * sell_bid_qty)
normal_net_edge_bps = gross_edge_bps - 69
stress_net_edge_bps = gross_edge_bps - 89
```

Candidate-event rules:

- causal snapshot only; no future quote may be used;
- both venues already passed the frozen age, skew, spread, and top-notional
  filters;
- `capacity_quote >= 50`, matching the frozen synthetic trade notional;
- one event per base and direction per 60 seconds;
- no threshold learned from returns, PnL, or OOS;
- no grid, retune, maker-fill assumption, leverage, margin, or short sale.

The sell leg is research-simulated only with pre-positioned inventory. The
frozen 20/30 bps inventory-rebalancing allowance remains charged; no transfer
speed or fee-tier advantage is credited.

## Candidate evidence sequence

1. Accepted hash-bound causal materialization.
2. Exact immutable evaluator contract review.
3. One contiguous 70% train / 30% OOS split with a 300-second embargo.
4. Five chronological walk-forward folds using the same untouched formula.
5. Normal and stress cost economics.
6. Sample-size, drawdown, capacity, stale-quote, and fill-risk checks.
7. Public read-only paper-forward only if every historical gate passes.

Any failed gate stops the downstream sequence. A result cannot silently change
the formula, costs, risk limits, split, universe, or venues.

## Required review before freeze

The user must confirm that the intended executable candidate is the existing
cross-venue dislocation formula restricted to causal `DENSE_BOTH` snapshots.
Only after that review may an immutable evaluator contract and a hash-bound
evaluation PlanOnly be created. Returns, PnL, and OOS remain closed until that
separate gate is explicitly authorized.
