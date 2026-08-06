# Fast-First v2 residual-dispersion verdict

Date: 2026-07-13

## Decision

`INSUFFICIENT_DATA`

The fixed hypothesis `venue_local_perp_residual_dispersion_reversion_v1` was evaluated exactly once, with one deterministic repeat, without grid search or OOS tuning. It is neither accepted nor rejected on profitability because the frozen pre-signal gates produced no executable events.

## Evidence

- Plan hash: `a73a54627477030bea0d4c57395c717cf74b1a243862ef9f8726356780e50566`.
- Input files: 195 expected, 195 observed; Merkle hash matched.
- Frozen universe: 97 non-Binance contracts, 43 MEXC and 54 Gate.
- Closed OOS coverage: 59 days versus the required 60; the open 2026-07-13 daily candle was correctly excluded.
- Gate eligible-market requirement: at least 12 instruments per venue after trailing 30-day median quote volume of at least $5,000,000.
- Gate result: Gate skipped 200/200 days and MEXC skipped 199/199 days for `insufficient_eligible_markets`.
- Signals: 0. Pair events: 0. Capacity proxy: unavailable.
- Deterministic result hash: `f2edd8391b088fcec12214601ac8364adcea1fd651d8b9f0a9a135efc13f6e75` in both runs.

## Interpretation

This is a universe/data compatibility failure before alpha evaluation. Zero PnL, zero expectancy, zero profit factor and zero win rate are placeholders caused by zero events, not measured strategy performance. Lowering liquidity, minimum-market or event thresholds after seeing this output would be retrospective tuning and is prohibited on this dataset.

## Boundaries

- No execution probe, grid search, paper-forward, API keys, live orders, leverage or margin.
- Funding, listing-event and slow-liquidity branches remain closed for retuning on their prior evidence.
- The residual-dispersion branch is also closed for retuning on this evidence.

## Next permitted step

Freeze a genuinely new Fast-First structural-edge hypothesis in PlanOnly before inspecting its OOS. It must use existing data or a separately approved collection of no more than three hours, retain conservative base fees, and define cost/OOS/walk-forward/stress/capacity gates before evaluation.
