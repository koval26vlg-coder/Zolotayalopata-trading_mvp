# funding_regime_persistence_carry_v2: terminal OOS

## Decision

- Status: `BRANCH_CLOSED_INSUFFICIENT_DATA`.
- Historical verdict: `INSUFFICIENT_DATA`.
- Execution probe, paper-forward and live are not authorized.
- Retuning this branch on the same train/OOS cache is prohibited.

## Frozen Provenance

- Plan hash: `c51562b959001970f3c689f7e277e8d3131d17c7f5b0e4e206f29750b1b60465`.
- Train feasibility hash: `bec9f9b368d3961d451c28ce730d86385af18b27cae5256566031e8875c113c0`.
- OOS deterministic result hash: `cca69e970e3bd0499926e5cb88e9236f638515f262eba91d3eaaf65680cffbf5`.
- OOS repeats have identical file SHA-256 values.
- Terminal closure SHA-256: `a821a012c83f9d5b38a76680187f4b38e50f6bf8a6a4b08e5bbd4673b55203cc`.

## Train Gate

- Candidate assets: `5`.
- Independent train episodes: `16`.
- Unique train signal dates: `16`.
- Minimum dual-leg coverage: `100%`.
- Both route directions were present.
- Verdict: `FEASIBLE_FOR_OOS`; no OOS values or PnL were read at this stage.

## OOS Result

- Independent episodes: `11`, required `20`.
- Unique signal dates: `10`.
- Unique traded assets: `3`.
- Normal net PnL: `+95.190938156149` quote on fixed `$500` per leg.
- Normal expectancy: `+8.653721650559` quote per event.
- Price-only net PnL: `-35.290061843851` quote.
- Funding PnL: `+130.481` quote.
- Positive-event rate: `45.45%`.
- Positive walk-forward folds: `4/5`.
- Stress net PnL: `-130.790311843851` quote.
- Cluster-bootstrap lower 95% expectancy: `-1.764720085609` quote.
- Maximum single-base positive-PnL share: `98.71%`.
- Maximum single-date and single-event positive-PnL share: `82.36%`.

The positive normal PnL is not accepted evidence. The sample-size gate failed, and the diagnostics show negative stress performance, a negative bootstrap lower bound and extreme concentration.

## Runtime Incident

The first visible OOS wrapper run `funding_regime_persistence_v2_oos_20260717_003832` stopped fail-closed because the two repeats received different remaining runtime metadata. Their market metrics matched, but they were not accepted. The wrapper was corrected to use the same fixed `870s` budget for each repeat. The successful replacement run was `funding_regime_persistence_v2_oos_20260717_004220_runtimefix`.

## Verification

- Funding-regime tests: `19/19` passed before OOS.
- CostProfile and PowerShell regression: `31/31` passed.
- Full project regression: `897` tests passed, `5` skipped.
- OOS artifact passed `validate_oos_result` after the successful deterministic repeat.

## Next Allowed Step

Create a materially new `PlanOnly` hypothesis or close the current weekly sprint as `NO_WEEKLY_EDGE_FOUND_MEXC_GATE`. Do not retune funding persistence, basis convergence, same-venue carry, HFT, listing-event or slow-liquidity on their existing data.

## Independent Checkpoint

`swarm_limited`: the external agent workflow was not started because the local safety policy rejected sending private trading artifacts to an unverified third-party workflow. No workaround was attempted. Codex completed the checkpoint from local hashes, deterministic repeats, frozen gates and the full regression suite.
