# Funding rank basis gate

Date: 2026-06-15

## Objective

Continue the research-only trading_mvp goal while the 24h funding/basis collector is still running. Since the dataset is not final, postprocess/finalize was not run. The pipeline was tightened so rank artifacts do not promote markets that violate strict basis gates used by backtest/finalize.

## Collector status

Checked strict status for:

- Output: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`

Latest status:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `4 / 288`
- `rows`: `96`
- `errors`: `24`
- `line_count_matches_manifest`: `true`
- `last_write_age_sec`: about `16`
- `required_row_field_presence`: `1.0` for `spot_bid_qty`, `spot_ask_qty`, `spot_top_min_notional_quote`
- Blocking reasons: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

## Changes

- Added rank-level basis gates to `FundingRankConfig`:
  - `max_abs_basis_bps`
  - `min_basis_bps`
- Added `rank_eligible` and `rank_reasons` to ranked rows.
- Rank sorting now prioritizes `rank_eligible` rows ahead of rows that only pass persistence scoring.
- Rank reasons include:
  - `source_not_eligible`
  - `source:<original_reason>`
  - `basis_too_wide`
  - `basis_below_min`
- Wired rank basis gates through:
  - `funding-rank`
  - `funding-postprocess`
  - `funding-finalize`
  - `run_mvp.ps1` funding-rank action
- Added `--strict-research` support to `funding-rank`; strict rank applies `min_basis_bps=0.0`.

## Verification

- `python -m unittest trading_mvp.tests.test_basis`
  - Result: 61 tests passed.
- `python -m unittest discover -s trading_mvp/tests`
  - Result: 133 tests passed.
- PowerShell smoke:
  - Command path: `run_mvp.ps1 -Action funding-rank -FundingStrictResearch`
  - Input: current partial 24h spot-liquidity JSONL
  - Output: `exports/trading-mvp/funding/funding_rank_smoke_minbasis_20260615.json`
  - Summary: `input_rows=96`, `markets_analyzed=24`, `ranked_rows=10`, `rank_eligible=4`, `persistence_eligible=10`
  - Confirmed: a negative-basis HYPE/MEXC row received `rank_reasons=["basis_below_min"]` and `rank_eligible=false`.

## Decision

Postprocess/finalize remains blocked by collector readiness, not by code. Continue waiting for `final=true`; then run strict postprocess/finalize with the same basis gates across rank, backtest, OOS, stress, and paper-forward plan creation.
