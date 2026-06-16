# Funding strict expected-carry gate

Date: 2026-06-15

## Objective

Continue the research-only trading_mvp goal while the 24h funding/basis collector is still running. The pipeline now rejects strict rank candidates whose expected carry is negative after modeled fees/slippage.

## Collector status

Strict status was checked for:

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
- `last_write_age_sec`: about `203`
- `error_rate`: `0.2`
- Required spot-liquidity fields present at `1.0` for `spot_bid_qty`, `spot_ask_qty`, `spot_top_min_notional_quote`
- Blocking reasons: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Postprocess/finalize was not run because the collector is not final and strict data-quality gates are not satisfied.

## Changes

- Added `min_expected_net_carry_bps` to `FundingRankConfig`.
- Added rank-level `expected_edge_below_min` reason when `expected_net_carry_bps` is below threshold.
- Updated strict research preset to force `min_expected_net_carry_bps=0.0`.
- Wired `--min-expected-net-carry-bps` through:
  - `funding-rank`
  - strict `funding-rank`
  - `funding-postprocess` rank config
  - `funding-finalize` rank config
  - `run_mvp.ps1` funding-rank action

## Verification

- `python -m unittest trading_mvp.tests.test_basis`
  - Result: 62 tests passed.
- `python -m unittest discover -s trading_mvp/tests`
  - Result: 134 tests passed.
- PowerShell smoke:
  - Command path: `run_mvp.ps1 -Action funding-rank -FundingStrictResearch`
  - Input: current partial 24h spot-liquidity JSONL
  - Output: `exports/trading-mvp/funding/funding_rank_smoke_strict_expected_20260615.json`
  - Summary: `input_rows=96`, `markets_analyzed=24`, `ranked_rows=10`, `rank_eligible=0`, `persistence_eligible=10`
  - Observed top rows all had negative `expected_net_carry_bps` and were marked with `expected_edge_below_min`.

## Interpretation

This is not a final strategy result because the source dataset is partial. It is a useful early diagnostic: with the current fee/slippage model and one funding interval target, the top partial candidates do not cover round-trip costs. Final acceptance still depends on completed 24h collect, strict postprocess, OOS, stress, and paper-forward gates.
