# trading_mvp Fast-First Edge Lab completed

Date: 2026-07-13
Agent: Codex (manual; swarm disabled)

## Delivered

- Added `CostProfile` as the shared source of MEXC/Gate spot/perp fees, spread, impact, slippage, maker fallback, and rebalance costs.
- Removed the synthetic negative cross-exchange round-trip cost from `funding_pairs.py`.
- Added `fast-edge-plan`, `fast-edge-evaluate`, `fast-edge-execution-probe`, `fast-edge-report`, and `paper-forward-segment`.
- Added `resolve-active-run` with fail-closed archival of an explicitly rejected incomplete run.
- Added foreground execution, `MaxRuntimeSec` default 1200 and hard maximum 10800, cache hashes, resumable probe state, and timeout sealing as `STOPPED_INCOMPLETE`.
- Confirmed `exports\trading-mvp` is a junction to `E:\ZolotyayLopata-data\exports\trading-mvp`.

## Gate resolution

Run `spot_pit_event_forward_20260712_225519` was archived as `REJECTED_INCOMPLETE`. Its 719168 rows remain on disk, but resume and use as edge evidence are prohibited.

## Frozen evaluation

- Plan hash: `e7519aab2b6bf9581386eb2a8a52d5f7c55c7d694ea6e8703b8bcd6562a125e8`
- Evaluation result hash: `78a003bdc634f51b81aed2893bdf4ed884fb4415f878b08fe0492d48dbf04903`
- Report result hash: `81bc6254a5bf1828b11a981450fd15abbec0381a0b14b6420bf4cbb55cc0b477`
- Universe: 20 symbols, 40 route constructions.
- Funding: 0 historical candidates; 20 cross-venue routes rejected and 20 same-venue routes insufficient because matching spot history is absent.
- Frozen listing-event fallback: rejected, 21 trades, net `-76.8045`, PF `0.5933`, walk-forward `2/4`.
- Frozen slow-liquidity fallback: rejected, 144 trades, net `-420.9597`, PF `0.3110`, walk-forward `0/4`.
- Final decision: `NO_FAST_EDGE_FOUND`; report verdict `REJECT`.

The closest funding route, `EVAA_USDT`, was not accepted: only 55 aligned OOS days and 3/5 positive walk-forward folds. No execution probe or paper-forward run was started.

## Verification

- Deterministic evaluation repeat: identical hash and decision.
- Full regression: `522` tests passed, `5` skipped, `0` failed.
- `py_compile`: passed.
- PowerShell parser: passed for `run_mvp.ps1` and `resolve_active_run.ps1`.
- `git diff --check`: passed for changed tracked files.
- Synthetic negative fee search: no matches.

## Next allowed work

Do not retune funding, listing-event, or slow-liquidity on the same evidence. The next research step must be a new fixed Fast-First hypothesis in PlanOnly mode. No collect, execution probe, paper-forward, API keys, or live orders are authorized by this result.
