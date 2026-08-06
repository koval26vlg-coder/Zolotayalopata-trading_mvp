# Gate historical membership momentum: embargo-safe proof pipeline

> Superseded status note (2026-07-17 11:23 +03:00): membership-v2 source was rejected at `0.3830 < 0.90` delisted-end coverage. The v3 `20d/100d/100d` adapters use one globally anchored seven-day rebalance calendar; folds do not reset signal dates. See `docs/agent-log/2026-07-17-1123-trading-mvp-membership-momentum-v2-global-cadence-fix.md`. The older `30d/140d/210d` figures below are retained as historical v1 design context, not as the active contract.

## Status

- Engineering status: ready for the separately approved public metadata probe.
- Market-data status: no new network probe or historical collect has run.
- Strategy evidence: no train, OOS, execution-probe or paper result exists yet.
- Active-run gate: open (`READY_FOR_POSTPROCESS`); the previous Gate spot/perp branch is closed as train-infeasible and remains blocked from replay/grid.
- Research boundary: public data only, no private API keys, live orders, leverage or margin.

## Materially new hypothesis

`cross_sectional_momentum_daily_survivorship_repair_v1` is a Gate-only, weaker-evidence branch designed to test whether a point-in-time non-Binance perpetual universe contains a slower cross-sectional momentum effect after conservative base costs.

Frozen strategy contract:

- 30 closed daily bars for the signal.
- Enter at the next closed daily open; exit at the daily open after seven holding days.
- Rebalance every seven days, so modeled positions do not overlap.
- Require at least 20 scored markets and at least five markets per side.
- Use `max(5, floor(scored_markets / 10))` long and short buckets.
- Require seven-day median quote volume of at least USD 1,000,000.
- No grid search, retune, TP, SL or OOS parameter selection.

Frozen cost contract:

- Normal: 20 bps fees + 10 bps spread + 4 bps impact + 2 bps slippage + 10 bps rebalance buffer = 46 bps per portfolio rebalance.
- Stress: 20 + 20 + 8 + 4 + 20 = 72 bps.
- Maker fill probability is zero because daily OHLCV cannot prove maker fills.
- Favorable funding is removed in stress; adverse funding is preserved.
- Stress funding is adjusted per asset before aggregation, so favorable funding on one leg cannot mask adverse funding on another.
- Price-only and funding results remain separate.

## Embargo design

The historical contract is physically split before any return calculation:

- 30 calendar days warm-up.
- 140 calendar days train.
- 210 calendar days sealed OOS, committed as five 42-day folds.

Quality writes two independent roots:

- `train/manifest.json`, containing only warm-up/train files.
- `oos-sealed/manifest.json`, containing only sealed OOS files.

The train PlanOnly contains the train manifest path, hashes of accepted quality inputs and only the OOS commitment hash. It does not contain an OOS path, the quality-report path or the raw collector-manifest path. The evaluator rejects any train file outside the train root and validates every referenced SHA-256 before reading rows.

Cached quality is reused only when the root manifest, both split manifests and every referenced normalized file remain hash-valid. A changed normalized file forces reconstruction from immutable raw archives.

## Train gate

The deterministic no-grid train evaluator produces one of:

- `GATE_MEMBERSHIP_MOMENTUM_FEASIBLE_FOR_OOS_PLANONLY`.
- `GATE_MEMBERSHIP_MOMENTUM_INFEASIBLE_ON_CURRENT_DATA`.
- `GATE_MEMBERSHIP_MOMENTUM_INSUFFICIENT_TRAIN_DATA`.

Frozen feasibility requirements:

- At least 18 independent non-overlapping rebalances.
- At least 10 unique traded assets.
- Positive price-only and total net expectancy after normal costs.
- Profit factor at least 1.1.
- Non-negative stress expectancy.
- Maximum drawdown no more than 15%.
- No single base contributes more than 35% of positive PnL.

Failure closes the branch without retuning. Success permits creation of a separate hash-bound OOS PlanOnly but does not launch OOS automatically.

## OOS gate

The separate OOS PlanOnly is created only from a hash-valid feasible train result and the sealed OOS commitment. It revalidates the quality artifact, train plan, deterministic train result, OOS manifest and every normalized input SHA-256 before opening OOS files.

Frozen OOS requirements:

- Exactly five non-overlapping 42-day chronological folds over 210 sealed days.
- At least 20 independent rebalances and 10 unique traded assets.
- Positive price-only and total net expectancy after 46 bps normal costs.
- Profit factor at least 1.2 and at least four positive folds.
- Non-negative 72 bps stress expectancy.
- Positive deterministic cluster-bootstrap 95% lower expectancy bound.
- Maximum drawdown no more than 10%.
- No single base or rebalance contributes more than 25% of positive PnL.
- Historical OHLCV cannot prove fill or capacity; the maximum positive verdict is `GATE_MEMBERSHIP_MOMENTUM_HISTORICAL_ACCEPT_FOR_EXECUTION_PROBE`.

Failure produces a terminal no-retune decision. An accepted historical result only permits an execution-probe plan; it cannot directly authorize paper-forward or live trading.

## Verification

- Targeted membership/history/momentum train/OOS suite: 31 tests passed.
- Full project regression: 988 tests passed, 5 skipped.
- Python modules compile successfully.
- `run_mvp.ps1` parses successfully.
- Frozen v2 probe plan file SHA-256 remains `b0bc4da3811acdeb67578fab5963ce7c54a0233867c9a6238700952dcedf0b69`.
- Frozen v2 probe module SHA-256 remains `e1aa13cae17d45c7b15a1d246a1d1508b7b18a2070b01a013aa7b79ca22b4bae`.

## Next permitted external step

Run the existing visible, ten-minute Gate historical-membership v2 public probe only after the exact hash-bound approval. Do not run history collect, train evaluation, OOS, grid, probe, paper-forward or live before its output passes the frozen source-quality contract.
