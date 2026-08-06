# trading_mvp paper depth-boundary adapter checkpoint

Date: 2026-07-19 09:40 +03:00

## Result

- Paper evidence for `gate_membership_momentum_v2` no longer accepts a manually authored entry or exit execution source.
- A valid execution source must be derived from exactly three finalized, immutable Gate public-depth window manifests for the corresponding `entry` or `exit` boundary.
- The adapter derives the first causal executable price and timestamp from the first frozen window, then aggregates coverage, valid snapshots, impact, capacity, skew, and quote-age gates across all three windows.
- The transitive provenance chain is now `paper plan + approval + selection + 3 raw-depth manifests -> execution raw input -> immutable raw manifest -> source -> funding source -> evidence -> event -> ledger`.
- Added PlanOnly/CLI routes for the paper boundary window plan and execution raw-source builder. They do not collect data or submit orders.

## Verification

- Focused regression after fixture repair: `3/3` passed.
- Paper-state module: `13/13` passed in `600.429s`.
- Related execution runtime, probe and paper-plan modules: `21/21` passed in `21.474s`.
- Python compilation and PowerShell AST parsing: passed.
- Full project regression: `1071` passed, `5` skipped, `0` failures in `1175.824s`.
- Full log: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\paper_execution_adapter_20260719_0905.full-regression.visible.log`.

## Research boundary

- No network collector, OOS, grid, paper-forward, live order, private API key, leverage, or margin action ran.
- This checkpoint does not prove an edge and does not reopen membership-v2.
- Active gate remains `READY_FOR_POSTPROCESS`, with `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED` because delisted-end coverage is `0.3830 < 0.90`.
- The only authorized future network action remains the separately approved visible Gate membership-v3 archive-source probe.
