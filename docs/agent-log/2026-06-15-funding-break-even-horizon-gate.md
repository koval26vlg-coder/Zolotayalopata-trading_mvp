# Funding break-even horizon gate

Date: 2026-06-15

## Objective

Continue the research-only trading_mvp goal while the 24h funding/basis collector is still running. The pipeline now checks whether modeled funding carry can recover round-trip cost within an explicit break-even horizon.

## Collector status

Strict status was checked for:

- Output: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`

Latest status:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `5 / 288`
- `rows`: `120`
- `errors`: `30`
- `line_count_matches_manifest`: `true`
- `error_rate`: `0.2`
- Required spot-liquidity fields present at `1.0` for `spot_bid_qty`, `spot_ask_qty`, `spot_top_min_notional_quote`
- Blocking reasons: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Postprocess/finalize was not run because the collector is not final and strict data-quality gates are not satisfied.

## Changes

- Added `max_break_even_hours` to:
  - `BasisScanConfig`
  - `FundingRankConfig`
  - `FundingBacktestConfig`
- Added `break_even_horizon_too_long` rejection reason in:
  - scan eligibility
  - rank eligibility
  - backtest entry/exit
- Added strict research preset:
  - `max_break_even_hours=24.0`
- Wired `--max-break-even-hours` through:
  - `funding-scan`
  - `funding-collect`
  - `funding-rank`
  - `funding-backtest`
  - `funding-oos-backtest`
  - `funding-postprocess`
  - `funding-finalize`
  - `run_mvp.ps1` funding actions

## Verification

- `python -m unittest trading_mvp.tests.test_basis`
  - Result: 65 tests passed.
- `python -m unittest discover -s trading_mvp/tests`
  - Result: 137 tests passed.
- PowerShell smoke:
  - Command path: `run_mvp.ps1 -Action funding-rank -FundingStrictResearch`
  - Input: current partial 24h spot-liquidity JSONL
  - Output: `exports/trading-mvp/funding/funding_rank_smoke_strict_breakeven_20260615.json`
  - Summary: `input_rows=120`, `markets_analyzed=24`, `ranked_rows=10`, `rank_eligible=0`, `persistence_eligible=10`
  - Top diagnostics:
    - Gate HYPE: `break_even_hours` about `917.6`, reasons include `basis_below_min`, `expected_edge_below_min`, `break_even_horizon_too_long`
    - MEXC XMR: `break_even_hours` about `73.4`, reasons include `expected_edge_below_min`, `break_even_horizon_too_long`

## Interpretation

This does not prove the strategy is unviable because the dataset is still partial. It does prove that, under the current taker-like fee/slippage model and 24h strict horizon, the currently observed top funding candidates do not recover round-trip cost fast enough. Final decision remains gated on completed 24h collect, strict postprocess, OOS, stress, and paper-forward validation.
