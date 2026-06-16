# 2026-06-15 funding data-quality gate

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and prevent finalized datasets with weak coverage or excessive API errors from entering rank/backtest/OOS acceptance.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `31 / 288`
- Rows: `720`
- Manifest rows: `720`
- Line count matches manifest: `true`
- Errors: `182`
- Last write age during check: about `244s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added `FundingDataQualityConfig` and `evaluate_funding_data_quality`.

Quality metrics:

- `rows`;
- `markets`;
- `completed_cycles`;
- `errors`;
- `attempts = rows + errors`;
- `error_rate = errors / attempts`.

Quality gates:

- `min_rows`;
- `min_markets`;
- `min_completed_cycles`;
- `max_error_rate`.

`run_funding_postprocess_file` now runs this preflight after final/line-count checks and before creating rank/backtest/OOS artifacts. If rejected, it returns `status=data_quality_rejected` and writes no rank/backtest artifacts.

`run_funding_research_finalize_file` passes the same quality config into postprocess, so a low-quality completed collect cannot create a paper-forward plan.

The new parameters are exposed through:

- Python CLI: `funding-postprocess`, `funding-finalize`;
- PowerShell wrapper: `-FundingQualityMinRows`, `-FundingQualityMinMarkets`, `-FundingQualityMinCompletedCycles`, `-FundingQualityMaxErrorRate`.

Defaults preserve previous behavior.

## Verification

- Targeted tests:
  - `Ran 3 tests ... OK`
- Funding basis suite:
  - `Ran 47 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 119 tests ... OK`
- PowerShell parse/status smoke with quality params:
  - `funding-status` returned `status=running_or_waiting`, `line_count_matches_manifest=true`, `final=false`.

## Intended use after collector finalizes

For the 24h finalize step, use data-quality gates together with research gates. Starting candidates:

- `FundingQualityMinRows=1000`;
- `FundingQualityMinMarkets=5`;
- `FundingQualityMinCompletedCycles=250`;
- `FundingQualityMaxErrorRate=0.30`.

These should be combined with:

- market concentration gates;
- time-window robustness gates;
- OOS and stress gates;
- paper-forward plan validation.
