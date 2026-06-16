# 2026-06-15 funding data-quality duplicates gate

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and avoid accepting inflated sample size from duplicate market rows within the same collection cycle.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `34 / 288`
- Rows: `792`
- Manifest rows: `792`
- Line count matches manifest: `true`
- Errors: `200`
- Last write age during check: about `35s`

No postprocess/finalize was started because the manifest is not final.

## Change

Extended `FundingDataQualityConfig` with:

- `min_unique_cycles`, default `0`;
- `max_cycle_market_duplicate_rate`, default `1.0`.

`evaluate_funding_data_quality` now reports:

- `unique_cycles`;
- `cycle_market_duplicates`;
- `cycle_market_duplicate_rate`.

Duplicate definition:

- duplicate key = `(cycle, exchange, spot_symbol, perp_symbol)`;
- each market should normally produce at most one row per cycle.

If configured strictly, postprocess rejects before rank/backtest/OOS when:

- unique row cycles are below `min_unique_cycles`;
- duplicate cycle-market rate exceeds `max_cycle_market_duplicate_rate`.

The new parameters are exposed through:

- Python CLI `funding-postprocess` and `funding-finalize`;
- PowerShell wrapper: `-FundingQualityMinUniqueCycles`, `-FundingQualityMaxCycleMarketDuplicateRate`.

Defaults preserve backward compatibility for old JSONL files without `cycle`.

## Verification

- Targeted tests:
  - `Ran 2 tests ... OK`
- Funding basis suite:
  - `Ran 51 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 123 tests ... OK`
- PowerShell parse/status smoke with duplicate-quality params:
  - `funding-status` returned `status=running_or_waiting`, `line_count_matches_manifest=true`, `final=false`.

## Intended use after collector finalizes

For the 24h finalized dataset, use:

- `FundingQualityMinUniqueCycles=250`;
- `FundingQualityMaxCycleMarketDuplicateRate=0.01`.

This should be combined with existing:

- data-quality rows/markets/errors gates;
- OOS duration gates;
- market/time-window concentration gates;
- stress gates;
- paper-forward temporal separation.
