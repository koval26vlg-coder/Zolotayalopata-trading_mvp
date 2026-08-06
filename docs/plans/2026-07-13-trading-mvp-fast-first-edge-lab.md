# trading_mvp Fast-First Edge Lab

## Objective

Find, prove, or reject a non-Binance edge with positive net expectancy after base API costs without putting long data collection on the critical path. Default runtime is 20 minutes per step; every collector/backtest/replay is capped at 10,800 seconds.

The proof target is net expectancy, not nominal win rate. A candidate must pass chronological OOS, five-fold walk-forward, stress, concentration, break-even, execution capacity, and paper-forward gates before any live review.

## Operating Contract

- Binance is reference-only.
- Research-only: no API keys, live orders, leverage, or margin.
- Any process writing time-series artifacts runs in a visible terminal with progress, ETA, row count, last write, and errors.
- Cached inputs are reused only when the universe/config hash matches.
- A failed or timed-out run becomes `STOPPED_INCOMPLETE`; partial output cannot be accepted.
- The data/export root is `E:\ZolotyayLopata-data\exports\trading-mvp`. The workspace export path is a junction to that root.
- A run longer than three hours is outside Fast-First and requires a separate request.

## Implementation

### Run management

- `resolve-active-run -RejectIncomplete -RunId ...` archives an incomplete gate as `REJECTED_INCOMPLETE` after checking that no recorded process is alive.
- `MaxRuntimeSec` defaults to `1200` and rejects values above `10800`.
- `run_mvp.ps1` invokes Fast-First commands in the foreground and terminates timed-out process trees while sealing the gate as incomplete.

### Unified economics

`CostProfile` is the single source of costs for funding ranking, evaluation, and execution gating. It models four orders for a two-leg round trip, spread, impact, slippage, maker fill probability, taker fallback, and a rebalance/operational buffer.

Base defaults:

| Venue | Market | Maker | Taker | Provenance |
| --- | --- | ---: | ---: | --- |
| MEXC | spot | 10 bps | 10 bps | conservative unverified spot default |
| MEXC | perp | 6 bps | 8 bps | official API futures schedule |
| Gate | spot/perp | 10 bps | 10 bps | conservative floor without account-specific proof |

Negative rebates and unverified VIP discounts are ignored. Stress uses taker exits, p95 execution assumptions, a 50% funding haircut, and a doubled rebalance buffer.

### Fast-First commands

1. `fast-edge-plan`: freezes hypothesis, universe, costs, split, gates, hashes, and cache key.
2. `fast-edge-evaluate`: tests same-venue spot/perp and cross-venue perp/perp carry with chronological 70/30 OOS and five walk-forward folds, without OOS retuning.
3. `fast-edge-execution-probe`: records visible 5-second BBO/depth snapshots only for a historical candidate.
4. `fast-edge-report`: emits `ACCEPT_FOR_PAPER`, `REJECT`, or `INSUFFICIENT_DATA` and the only allowed next command.
5. `paper-forward-segment`: carries paper state across short windows; three qualified settlement windows produce `PAPER_READY`, and at least 15 observations are required for `LIVE_REVIEW_ELIGIBLE`.

## Acceptance Gates

- OOS: at least 60 aligned days and 60 settlements.
- Dual-leg coverage: at least 80%.
- OOS expectancy: positive after all costs.
- OOS profit factor: at least 1.2.
- Positive-settlement rate: at least 60%.
- Walk-forward: at least four of five positive folds.
- Stress net PnL: nonnegative.
- Break-even holding period: at most 14 days.
- Single funding event: at most 25% of OOS PnL.
- Execution: at least 180 valid snapshots, USD 500 per leg, p95 impact at most 10 bps.

## Frozen Result, 2026-07-13

Artifacts:

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge\plans\fast_edge_plan_full_20260713.json`
- Evaluation: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge\evaluations\fast_edge_evaluation_full_20260713.json`
- Report: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge\reports\fast_edge_report_full_20260713.json`

Evaluation covered 20 symbols and 40 route constructions. It produced zero historical candidates:

- Cross-venue funding: 20 rejected.
- Same-venue spot/perp: 20 insufficient because the frozen dataset has no matching spot history.
- Listing-event fallback: rejected, 21 trades, net PnL `-76.8045`, PF `0.5933`, walk-forward `2/4`.
- Slow-liquidity fallback: rejected, 144 trades, net PnL `-420.9597`, PF `0.3110`, walk-forward `0/4`.

The closest funding route still failed proof gates. `EVAA_USDT` had positive OOS net PnL and PF above 1.2, but only 55 aligned OOS days and three positive walk-forward folds out of five. It is not an accepted candidate.

Final decision: `NO_FAST_EDGE_FOUND` / report verdict `REJECT`. The execution probe was intentionally not run because historical acceptance produced no candidate. Retuning these three branches on the same data is prohibited; the next research action must start from a new frozen hypothesis.
