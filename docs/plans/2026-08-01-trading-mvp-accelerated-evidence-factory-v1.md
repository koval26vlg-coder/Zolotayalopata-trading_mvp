# trading_mvp Accelerated Evidence Factory v1

## Objective

Find, prove, or reject one executable research strategy as quickly as evidence integrity permits. The pipeline advances continuously: market-data windows are used for pre-registered collection, and every gap is used for bounded code, validation, provenance, or post-processing work.

Readiness is not edge proof. A strategy is not accepted until the frozen train, chronological OOS, five-fold walk-forward, stress, economics, execution-capacity, and public paper-forward gates all pass.

The first dense evidence dataset must cover one uninterrupted 24-hour market
cycle. This is preferred over combining repeated night-time slices because it
preserves regime transitions, time-of-day effects, and every event between
them. Hourly durable files are checkpoints inside one continuous run, not
separate collection windows.

## Active Evidence Sequence

1. Preserve the completed PIT n05 evidence and run the already preapproved
   `pit_universe_v2_forward_20260803_n06` segment from 01:00 to 01:20 local
   time.
2. Reserve 01:20 through 01:30 for PIT finalization and the global writer-lock
   handoff. Never overlap the PIT writer and the dense writer.
3. Start one continuous MEXC/Gate public WS collection at 01:30 on 2026-08-03.
4. Keep the same writer running through the daytime and stop at 01:30 on
   2026-08-04 after exactly 86,400 writer seconds.
5. Reserve a final shutdown deadline of 02:00 on 2026-08-04. Keep the existing
   25,000,000,000-byte hard campaign-output cap and stop early on an integrity,
   disk, quota, or single-writer failure.
6. Do not launch `pit_universe_v2_forward_20260804_n07` while the continuous
   writer owns the global writer lock. That PIT segment expires unaccepted;
   later PIT dates continue normally. This is an explicit priority decision,
   not a hidden overlap or a failed PIT run.

This continuous campaign is a specific evidence-value exception to the general
19:00-08:00 convenience windows. It is intentionally allowed to continue
during the day so the dataset contains a complete daily market cycle. The
writer still publishes hourly append-safe durable segments, but it does not
intentionally stop between them.

The previous split-phase schedule is superseded and must not be launched. A
fresh immutable Contract/PlanOnly must bind this exact 24-hour window before
collection starts. A failed or interrupted campaign cannot be silently joined
to a later run; partial data remains diagnostic, and a new run needs a new
immutable plan.

## Frozen Scope

- Hypothesis: `dense_ws_microstructure_regime_filter_v1`.
- Venues: MEXC and Gate public spot market data only.
- Data type: `DENSE_WS_SEGMENTED`.
- Universe: 1,388 rows, SHA-256 `ce3d78cac3aa084a23376ee26a39c8fc98655a262a701c0d4d5f00469f2bafe3`.
- Existing raw schema, segment-validity, causal regime timestamp, stale-quote, cost, risk, and no-grid contracts remain frozen.
- One global visible market-data writer claim is mandatory across PIT and dense launchers.
- The stale `no_binance_dense_ws_sweep_20260628.csv` 72-hour route is terminally disabled. Its partial outputs are diagnostic-only and cannot be used for replay, OOS, returns, PnL, or acceptance evidence.

## Automatic Evidence Pipeline

After the continuous 24-hour run finalizes and passes raw integrity, the same immutable evidence chain may run these deterministic stages without idle gaps:

1. Campaign data quality, gap accounting, schema and venue coverage.
2. Frozen train evaluation.
3. Chronological OOS evaluation.
4. Five-fold walk-forward evaluation.
5. Normal and stress cost economics.
6. Drawdown, sample-size, liquidity, fill-risk, and execution-capacity gates.
7. Seven-day public-read-only paper-forward only when every prior gate is `PASS`.

Any failed gate stops downstream promotion. No grid, retune, new hypothesis, universe drift, or silent acceptance is allowed. Historical or paper terminal `ACCEPT`/`REJECT` is reported to the user.

## Safety Boundary

Research and public paper observation only. No private API keys, order submission, real capital, leverage, margin, withdrawals, or live trading. These remain separate critical decisions.
