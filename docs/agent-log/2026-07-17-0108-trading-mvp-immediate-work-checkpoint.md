# trading_mvp immediate-work checkpoint

Timestamp: `2026-07-17T01:08:01+03:00`

## Active state

- Active-run gate: `READY_FOR_POSTPROCESS`.
- Completed segment: `pit_universe_v2_forward_20260716_n01`.
- Collector result: `4/4` cycles, `6864` rows, `0` endpoint errors, `final=true`.
- Technical certification: `REJECTED`.
- Sole reason: `dual_venue_bbo_size_coverage_below_minimum`.
- Accepted PIT dates remain `2`: `2026-07-14`, `2026-07-15`.
- Returns and PnL were not read.

## Root cause and fix

- MEXC depth completion by cycle was `136/210`, `145/210`, `172/210`, `210/210`.
- The first three cycles exhausted the old sequential 120-second depth-enrichment budget.
- Current collector defaults use a global request-start interval of `0.25` seconds and at most `3` workers.
- The rate-fix public probe completed `210/210` depth requests with zero errors.
- The old approved schedule hash `14f687e...` is immutable but has a stale runtime-tool hash and must not be reused for future segments.

## Closed historical branches

- `cross_venue_perp_basis_convergence_1h_v2`: closed before OOS as `INSUFFICIENT_EXECUTABLE_UNIVERSE` (`5` liquidity survivors, frozen minimum `8`).
- `funding_regime_persistence_carry_v2`: closed after deterministic OOS as `INSUFFICIENT_DATA`; stress and concentration gates also failed.
- No grid, retune, threshold relaxation or additional OOS read was performed.

## Paper product readiness

Focused verification passed `23/23` tests:

- two-leg lifecycle and internally calculated PnL;
- fee/funding accounting without manual PnL injection;
- WAL recovery and reconciliation;
- ledger tamper detection;
- stale/thin depth execution guard;
- data-quality and daily-loss kill switches;
- hash-bound paper approval;
- 15-observation live-review gate.

Paper infrastructure is ready, but remains blocked until a research branch reaches the required historical and execution-probe acceptance gates.

## Next scheduled action

Rate-fix PlanOnly:

- path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_primary_immutable_sources_planonly_20260716_234212.json`
- plan hash: `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1`
- first visible segment: `2026-07-17T23:00:00+03:00..2026-07-17T23:20:00+03:00`
- run ID: `pit_universe_v2_forward_20260717_n01`

The schedule remains unapproved and hash-bound. No early or hidden collector was launched.
