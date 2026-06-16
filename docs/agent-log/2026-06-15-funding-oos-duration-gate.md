# 2026-06-15 funding OOS duration gate

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and make out-of-sample validation harder to misuse. OOS should not be accepted only because it has enough rows if those rows cover too short a time interval.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `32 / 288`
- Rows: `744`
- Manifest rows: `744`
- Line count matches manifest: `true`
- Errors: `188`
- Last write age during check: about `143s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added OOS duration coverage gates:

- `FundingOosConfig.min_train_span_hours`, default `0.0`;
- `FundingOosConfig.min_oos_span_hours`, default `0.0`.

`run_funding_oos_backtest` now reports:

- `coverage.train_span_hours`;
- `coverage.oos_span_hours`;
- `coverage.train_span_accepted`;
- `coverage.oos_span_accepted`;
- `coverage_acceptance.accepted`;
- `coverage_acceptance.reasons`.

Overall OOS `accepted` now requires:

- in-sample acceptance;
- out-of-sample acceptance;
- coverage acceptance.

The postprocess OOS summary now includes the coverage block so the final artifact explains whether OOS failed because of metrics or because the sample was too short in time.

The new parameters are exposed through:

- Python CLI `funding-oos-backtest`: `--min-train-span-hours`, `--min-oos-span-hours`;
- Python CLI `funding-postprocess`/`funding-finalize`: `--oos-min-train-span-hours`, `--oos-min-span-hours`;
- PowerShell wrapper: `-FundingOosMinTrainSpanHours`, `-FundingOosMinSpanHours`.

Defaults preserve previous behavior.

## Verification

- Red check before implementation:
  - `FundingOosConfig.__init__()` rejected `min_train_span_hours`;
  - CLI rejected `--min-train-span-hours` and `--min-oos-span-hours`.
- Targeted tests after implementation:
  - `Ran 3 tests ... OK`
- Funding basis suite:
  - `Ran 48 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 120 tests ... OK`
- PowerShell parse/status smoke with OOS span params:
  - `funding-status` returned `status=running_or_waiting`, `line_count_matches_manifest=true`, `final=false`.

## Intended use after collector finalizes

For a 24h dataset, start with:

- `FundingOosMinTrainSpanHours=6`;
- `FundingOosMinSpanHours=6`.

This should be combined with:

- data-quality gates;
- market concentration gates;
- time-window PnL concentration gates;
- stress gates;
- paper-forward plan validation.
