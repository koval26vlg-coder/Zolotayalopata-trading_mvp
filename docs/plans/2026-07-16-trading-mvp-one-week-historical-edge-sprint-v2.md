# Trading MVP One-Week Historical Edge Sprint v2

Date: 2026-07-16

Status: `TERMINAL_PRE_OOS_QUALITY_VERDICT`

Mode: PlanOnly, research-only, MEXC/Gate, non-Binance, public data only.

## Objective

Within seven calendar days produce one reproducible terminal verdict for a single new hypothesis:

`cross_venue_perp_basis_convergence_1h_v2`

Allowed historical verdicts:

- `ACCEPT_FOR_EXECUTION_PROBE`
- `REJECT`
- `INSUFFICIENT_DATA`

Historical acceptance never authorizes paper or live trading. `PAPER_FORWARD_READY` requires the separate execution-probe contract.

## Frozen Data Contract

- Venues: MEXC and Gate only.
- Instruments: matching USDT linear perpetuals.
- Binance: identity/exclusion reference only.
- Primary interval: one hour.
- Window: exactly 179 fully closed UTC days in a half-open interval `[window_start_ts, window_end_ts)`.
- Anchor: latest common immutable funding-cache cutoff rounded down to a closed UTC hour.
- Split: 14 warm-up days, 85 train days and 80 sealed OOS days.
- OOS diagnostics: five fixed, non-overlapping 16-day subperiods. They are not rolling walk-forward folds.
- Series per venue: trade, mark and index one-hour candles.
- Funding: separate lossless event ledger using actual settlement timestamps.
- Daily/funding data: reuse the immutable cache; do not repeat a full backfill.
- New candle acquisition: only missing one-hour series, one visible owned writer, maximum 90 minutes.
- Output: new immutable `historical-basis-1h-v2` namespace. Frozen v1 files and artifacts remain unchanged.

## A0 Offline Preflight

A0 must not read returns, PnL, signals or OOS metrics. It produces a hash-bound availability report.

Requirements:

1. Build the dual-venue universe from canonical identity, venue-native symbols and PIT lifecycle records.
2. Exclude Binance Spot assets and stable, wrapped, staked, leveraged, LP, synthetic, pre-market, index and tokenized assets.
3. Reject ticker collisions and ambiguous identity mappings.
4. Verify a common 179-day funding window for both venues with exact timestamps, signs, cadence changes, duplicates, gaps and pagination provenance.
5. Probe the oldest and newest boundary of one-hour trade/mark/index series for every candidate.
6. Verify timestamp convention: candle timestamps represent bar opens and a signal is available only after bar close.
7. Estimate request count and worst-case runtime; require completion within 90 minutes.
8. Require at least eight eligible assets before train-only liquidity filtering.
9. Freeze all input hashes, the half-open time window and the candidate set before any return is read.

A0 verdicts:

- `PREFLIGHT_ACCEPTED_NOT_COLLECTED`
- `INSUFFICIENT_EXECUTABLE_UNIVERSE`
- `INSUFFICIENT_FUNDING_HISTORY`
- `UNRESOLVED_DATA_CONTRACT`

Only `PREFLIGHT_ACCEPTED_NOT_COLLECTED` permits the collector.

## Frozen Strategy

- `venue_basis_bps = (mark_close - index_close) / index_close * 10000`.
- `basis_spread_bps = abs(mexc_basis_bps - gate_basis_bps)`.
- Long the lower-basis venue and short the higher-basis venue.
- A signal is evaluated after a one-hour bar closes.
- Entry executes at the next contiguous one-hour trade-bar open.
- Entry requires a fresh threshold crossing from below.
- `exit_threshold_bps = 20`.
- `maximum_holding_hours = 72`.
- A convergence exit is observed on a closed bar and executes at the next contiguous trade-bar open.
- A max-hold exit executes at the first causally available trade-bar open at or after 72 hours.
- No OHLC touch, intrabar ordering, TP, SL, trailing, maker fill, grid or retune assumption.
- One position per canonical asset.
- A new episode is allowed only after the previous position has closed, spread has reset to `<=20 bps`, and a later fresh crossing above the entry threshold occurs.
- A data gap larger than three hours terminates the segment and forbids cross-gap PnL.

## Economics

- Notional: `$500` per leg.
- Fully collateralized `1x`.
- Historical execution: taker-only.
- Cost profile is loaded from `CostProfile`, never a promotional/VIP/rebate assumption.
- Current frozen normal cycle cost: `78 bps`.
- Current frozen stress cycle cost: `88 bps`.
- Entry threshold: `stress_cycle_cost_bps + 20 bps exit + 20 bps safety`, currently `128 bps`.
- Four trading operations, spread, impact, slippage and rebalance buffer are included.
- Funding event attribution uses `entry_ts <= settlement_ts < exit_ts`.
- Positive funding cash flow receives a 50% stress haircut; adverse funding is preserved in full.
- Price-only and total PnL are reported separately; funding cannot rescue negative price-only expectancy.

## Universe Selection

- A0 may retain at most 20 canonical candidates using only identity, lifecycle and data availability.
- Current or full-window volume cannot determine the historical shortlist.
- Train-only seven-day median quote volume on the worse leg must be at least `$1,000,000`.
- After quality and train-only liquidity, select 12 primary plus up to 8 reserve deterministically.
- Reserve substitution is allowed only for pre-OOS data-quality or lifecycle failure.
- Fewer than eight surviving assets yields `INSUFFICIENT_EXECUTABLE_UNIVERSE`; thresholds are not relaxed.

## Quality Gates

- Each trade/mark/index series coverage `>=98%`.
- Dual-venue aligned coverage `>=95%`.
- Funding settlement coverage `>=98%` against the venue's observed cadence schedule.
- No open bars, duplicate timestamps or merged funding events.
- Timestamp and price values must be finite and positive where required.
- All lifecycle masks are applied before signal generation.
- Funding remains a separate immutable JSONL ledger and is never exact-joined into candle rows.

## Train Feasibility

- At least 20 independent episodes.
- At least 10 distinct UTC dates.
- Both MEXC-cheap and Gate-cheap directions.
- At least eight quality-surviving canonical assets in the frozen universe.
- Train is used only for feasibility and train-only liquidity; it cannot alter threshold, exit, hold, costs or OOS boundaries.
- On failure OOS remains unread and verdict is `INSUFFICIENT_DATA` or `REJECT` as specified by the failed gate.

## Historical OOS Gates

- At least 40 independent episodes on at least 20 dates and eight assets.
- Any OOS sample below 40 independent episodes yields `INSUFFICIENT_DATA`; sample scarcity is never converted into `REJECT`.
- Price-only net expectancy after costs `>0`.
- Total net expectancy after costs and funding `>0`.
- Profit factor `>=1.2`.
- At least four of five fixed OOS subperiods positive.
- Normal and stress net PnL non-negative; stress expectancy `>0`.
- One-sided 95% day-and-asset cluster-bootstrap lower bound of expectancy `>0`.
- MEXC-cheap and Gate-cheap directions separately non-negative.
- No base, date or episode contributes more than 25% of positive PnL.
- Maximum drawdown `<=10%` of peak concurrently collateralized capital.
- Deterministic repeat on identical hashes produces the same result hash.

If the one-hour primary passes, aggregate the same immutable one-hour data into four-hour bars and rerun the unchanged strategy as a robustness check. No new data, threshold or parameter is allowed. Negative four-hour normal or stress evidence blocks historical acceptance.

## Implementation Actions

The v2 interface is versioned and must not redirect existing v1 actions:

- `fast-edge-basis-v2-preflight`
- `fast-edge-basis-v2-plan`
- `fast-edge-basis-v2-history-collect`
- `fast-edge-basis-v2-history-quality`
- `fast-edge-basis-v2-evaluate`
- `fast-edge-basis-v2-report`

Required artifacts include plan/code/universe/input hashes, source and fee provenance, candle manifest, separate funding-event Merkle, quality report, train feasibility, sealed OOS result, fixed-subperiod metrics, 4h robustness, rejection reasons and exactly one `next_allowed_command`.

## Runtime And Visibility

- A0 preflight: maximum 30 minutes, normally offline plus bounded public boundary probes.
- Plan freeze: maximum 10 minutes.
- Candle collector: maximum 90 minutes, visible terminal, one writer.
- Quality: maximum 30 minutes.
- Train or OOS evaluator: maximum 30 minutes each.
- Report: maximum 30 minutes.
- Timeout or network interruption produces `STOPPED_INCOMPLETE`, never partial acceptance.
- Existing matching cache hashes are reused.

## Terminal Rules

- Any negative OOS, fixed-subperiod, stress or bootstrap gate closes the branch without retuning.
- A data-contract failure closes the run as insufficient or incomplete; it does not silently shorten the window.
- External 5m data requires a new PlanOnly only after a documented native-data path ambiguity.
- Rejection does not activate another hypothesis in this sprint.
- Historical acceptance permits only a short visible execution-probe PlanOnly.
- Private API keys, live orders, leverage and margin remain prohibited.

## Current State

- Council decision: complete.
- v2 implementation: complete.
- Frozen plan hash: `354422b317d3112b3da73ff3f8126e2bf09948795f2781e64acb47f611060665`.
- Visible public collector `basis_v2_history_20260716_132600_runtime_guard`: `120/120` series, `0` errors, `112.665s`.
- Candle/alignment/funding quality: `20/20` assets passed.
- Frozen train-liquidity gate: `5/8` assets passed (`PIPPIN`, `HYPE`, `PI`, `MYX`, `H`).
- Terminal verdict: `INSUFFICIENT_EXECUTABLE_UNIVERSE` with reason `TRAIN_LIQUIDITY_SURVIVORS_BELOW_FROZEN_MINIMUM`.
- Hash-bound terminal result: `b6ddafe2b980e7fae55c6985fb46b725200beeb57aa47ae78d0639e2545309a6`; deterministic repeat matched.
- Canonical experiment-ledger record: `exp_20260716_162742_3fe2bb00a84f`, verdict `inconclusive`, OOS status `not_run_quality_gate_failed`, provenance complete.
- Current basis-v2 regression: `108/108` passed; PowerShell parse passed.
- Paper-only execution safety is implemented for future accepted plans: every position transition now requires synchronized MEXC/Gate depth, bounded quote age/skew, `$500` capacity per leg and impact within the frozen probe limit. Depth VWAP replaces unexecutable trade-price assumptions; missing, stale or thin books append `EXECUTION_BLOCKED` and cannot create paper PnL.
- OOS: not read.
- Returns/PnL: not read.
- Grid, retune, execution probe, paper-forward and live: blocked for this frozen branch.
- Next allowed command: `open-materially-new-planonly-hypothesis-or-continue-pit-shadow`.
