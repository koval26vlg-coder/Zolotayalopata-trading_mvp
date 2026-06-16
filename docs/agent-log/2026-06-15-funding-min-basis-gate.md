# Funding min basis gate

Date: 2026-06-15

## Objective

Continue the research-only trading_mvp goal by tightening the funding/basis carry pipeline before any 24h postprocess. The strict research path must not accept long spot + short perp carry when perp basis is below the configured minimum.

## Changes

- Added `min_basis_bps` to `BasisScanConfig` and `FundingBacktestConfig`.
- Added `basis_below_min` eligibility/exit reason.
- Wired `--min-basis-bps` through:
  - `funding-scan`
  - `funding-collect`
  - `funding-backtest`
  - `funding-oos-backtest`
  - `funding-postprocess`
  - `funding-finalize`
- Wired `FundingMinBasisBps` through `run_mvp.ps1` for all relevant funding actions.
- Set strict research preset `min_basis_bps=0.0`.
- Fixed the backtest row check so `basis_bps=0.0` is treated as a valid value, not as missing.

## Verification

- `python -m unittest trading_mvp.tests.test_basis`
  - Result: 60 tests passed.
- `python -m unittest discover -s trading_mvp/tests`
  - Result: 132 tests passed.

## Collector status

Checked strict status for:

- Output: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`

Latest status:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `3 / 288`
- `rows`: `72`
- `errors`: `18`
- `line_count_matches_manifest`: `true`
- `required_row_field_presence`: `1.0` for `spot_bid_qty`, `spot_ask_qty`, `spot_top_min_notional_quote`
- `data_quality.accepted`: `false`
- Blocking reasons: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Postprocess/finalize was not run because the collector is not final.
