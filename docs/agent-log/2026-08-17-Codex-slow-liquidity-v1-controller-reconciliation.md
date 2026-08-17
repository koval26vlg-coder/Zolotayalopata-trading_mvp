# Slow Liquidity v1 Controller Reconciliation

Date: 2026-08-17
Scope: slow-liquidity proof pipeline only. The separate listing-momentum project is excluded.

## Decision

- fixed slow-liquidity v0 is `REJECTED_AS_DEGENERATE` because its 96h range was compared with unscaled one-bar ATR.
- scaled-compression v1 used the frozen formula `range_width_96h / (ATR_96h * sqrt(96)) <= 1.2`.
- v1 is now `REJECTED_INSUFFICIENT_EVENTS`; no replay, OOS, walk-forward, stress, grid, retune, collect, paper or live step is authorized from this checkpoint.
- a materially new structural hypothesis is an explicit user checkpoint, not an automatic controller action.

## Verified Artifacts

- v1 PlanOnly: `exports/trading-mvp/analysis/slow_liquidity_fixed_compression_v1_planonly_20260817_181803.json`
- v1 plan hash: `59655c350b0490edc9c8b2a11686affd835f16bdd7e0e017a43f9771ee1fae7f`
- parent plan hash: `38abed6a5d91c7633c149f4d1e391f64f27d85eda5edffc6cae56f1fa59f9654`
- parent plan file SHA256: `fe64440cf790bf99a5e55c23a256d711aeb10f5295905ce1dc43bd9d04bbca1f`
- input state hash: `75eb0e36df225d1afad5e61a7156681c71c877bf1b893b1caf7acb92bc894b15`
- feature normalizer: `exports/trading-mvp/analysis/slow_liquidity_feature_normalizer_planonly_20260817_181843.json`
- normalizer decision: `SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS`
- observed event counts: 20 raw candidates, 14 independent events, 6 bases, 3 exchanges

## Controller State

- active run gate: `READY_FOR_POSTPROCESS`
- run id: `slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6`
- replay allowed: `false`
- next decision: `SLOW_LIQUIDITY_FEATURE_NORMALIZER_V1_REJECTED_SELECT_NEXT_BRANCH`
- `requires_user_approval`: `true` for a new structural hypothesis
- actual collection approval: `false`

## Implementation

- added canonical state and input-file binding helpers;
- added stale-binding rejection to replay;
- added the immutable scaled-compression v1 PlanOnly;
- reconciled goal status, next-step and branch-selector controllers;
- updated branch disposition and current-state tests.

## Verification

- focused slow-liquidity tests: 13 passed;
- controller stateful tests: 3 passed;
- Python compilation: passed;
- PowerShell parsing: passed;
- core shard: 107 passed;
- full fast shard still has 6 pre-existing fast-edge/paper-forward wiring failures;
- integration shard still has 5 pre-existing historical-basis/PIT wrapper failures;
- no network request, collector, writer, listing-project action or live action was performed.
