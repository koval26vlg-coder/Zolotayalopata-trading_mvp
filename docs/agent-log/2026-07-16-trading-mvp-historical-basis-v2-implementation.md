# trading_mvp historical basis v2 implementation

Date: 2026-07-16

Status: `IMPLEMENTED_AWAITING_A0_PREFLIGHT`

## Decision

The literal 300-day/4h contract was not implemented because Gate public funding history is bounded to roughly 180 days. The implemented primary contract is `cross_venue_perp_basis_convergence_1h_v2`:

- 179 fully closed UTC days;
- 14-day warm-up, 85-day train and 80-day sealed OOS;
- one-hour trade, mark and index candles;
- a separate lossless funding-settlement ledger;
- five fixed 16-day OOS diagnostics, explicitly not walk-forward folds;
- causal next-open entry and exit, no intrabar touch assumptions;
- 4h aggregation only as a robustness check over the same immutable 1h input;
- no grid, retune, private API keys, live orders, leverage or margin.

## Implemented interface

- `fast-edge-basis-v2-preflight`
- `fast-edge-basis-v2-plan`
- `fast-edge-basis-v2-history-collect`
- `fast-edge-basis-v2-history-quality`
- `fast-edge-basis-v2-evaluate`
- `fast-edge-basis-v2-report`

The actions are versioned and do not redirect or mutate v1 artifacts. Every action has an explicit runtime ceiling. The collector uses one owned writer, a visible-run-compatible manifest/gate contract, separate MEXC/Gate token buckets and immutable cache reuse.

## Verification

- Python compilation: passed.
- PowerShell parser check for `run_mvp.ps1`: passed.
- v2 core/evaluator tests: `28/28` passed.
- v2 acquisition/quality tests: `23/23` passed.
- v2 report/wrapper tests: `7/7` passed.
- Historical-basis v1/v2 regression: `101/101` passed.
- Full repository suite: `822` total, `814` passed, `5` skipped, `3` failed.

The three full-suite failures are pre-existing Windows encoding/mojibake expectations in PIT and visible-wrapper tests. They do not import or exercise the historical-basis v2 implementation:

1. `test_pit_membership_drift_execution_probe_visible.PitMembershipDriftExecutionProbeVisibleTests.test_planonly_is_read_only_and_exposes_exact_confirmation`
2. `test_visible_ws_collect_wrapper.VisibleWsCollectWrapperTests.test_goal_status_uses_current_scorecard_not_active_gate_for_funding_summary`
3. `test_visible_ws_collect_wrapper.VisibleWsCollectWrapperTests.test_slow_liquidity_history_visible_collect_wrapper_is_guarded_planonly`

## Runtime state

- Active-run gate was `READY_FOR_POSTPROCESS` before implementation work.
- A0 preflight was not run.
- Historical collector was not started.
- OOS data and performance metrics were not read.
- No background or hidden process was created.

## Next allowed step

Run a visible, bounded A0 availability preflight. It may inspect identity, lifecycle, cache coverage and public boundary availability, but must not read returns, signals, PnL or OOS metrics.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1 `
  -Action fast-edge-basis-v2-preflight `
  -InputPath E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\pit_universe_v2_forward_20260715_n01\universe_state.json `
  -CoinRegistryPath C:\Users\koval\Documents\ZolotyayLopata\coins_not_on_binance_full_2026-05-29.csv `
  -ManifestPath E:\ZolotyayLopata-data\exports\trading-mvp\daily\daily_collect_20260702_top200\manifest.json `
  -OutputPath E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\preflight\preflight_20260716.json `
  -MaxRuntimeSec 1800
```
