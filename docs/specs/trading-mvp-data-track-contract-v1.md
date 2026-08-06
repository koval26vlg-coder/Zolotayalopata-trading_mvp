# trading_mvp Data-Track Contract v1

Status: `IMPLEMENTED_TARGETED_VERIFIED`
Scope: PlanOnly preparation for a future Fast-First data track after `NO_FAST_EDGE_ON_CURRENT_DAILY_DATA`.

## Contract Boundary

`fast-edge-data-track-plan` creates one immutable, hash-bound PlanOnly artifact. It does not start a collector, open a track, inspect market returns, compute performance or authorize OOS.

Required inputs:

- hypothesis id from `docs/research/trading_mvp_hypothesis_bank_v1.json`;
- exact required data type;
- dataset id and 64-hex input Merkle;
- train candidate/valid counts;
- OOS candidate and per-venue counts;
- unique OOS dates, dual-venue coverage and capacity proxy;
- output path and runtime cap no greater than 1,200 seconds.

## Fail-Closed Rules

- Hypothesis/data-type mismatch is rejected.
- Invalid Merkle, counts, coverage or runtime is rejected.
- Existing output is never overwritten.
- `oos_metrics` and `observed_performance` remain empty.
- `evaluation_allowed`, probe, paper, live, API keys, leverage, margin, grid and retune remain false.
- The sole next action is `fast-edge-feasibility`.

## Evidence Boundary

A successful PlanOnly build proves only that the contract is structurally valid. A fixture feasibility pass proves only the estimator wiring. Neither result is evidence of a trading edge or permission to run OOS on real data.
