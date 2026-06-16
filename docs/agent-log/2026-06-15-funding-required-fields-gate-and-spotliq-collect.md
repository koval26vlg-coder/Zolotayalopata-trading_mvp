# 2026-06-15 funding required-fields gate and spotliq collect

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline toward a strategy accepted only after strict data quality, OOS, stress, execution-quality, and paper-forward gates.

## Problem Found

The original running 24h collector was started before the spot top-of-book liquidity fields were added.

Original dataset:

- Output: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Latest checked state: `final=false`, `completed_cycles=38 / 288`, `rows=888`, `errors=224`
- Strict required field presence:
  - `spot_bid_qty`: `0.0`
  - `spot_ask_qty`: `0.0`
  - `spot_top_min_notional_quote`: `0.0`

Conclusion: the original dataset is legacy-schema data and must not be accepted by strict research finalize after the spot-liquidity gate was introduced.

## Change

Extended `FundingDataQualityConfig` with required row-field checks:

- `required_row_fields`;
- `min_required_row_field_presence`.

`evaluate_funding_data_quality` now reports:

- `required_row_field_presence`;
- `required_row_field:<field>` rejection reasons.

Strict research preset now requires these fields with `1.0` presence:

- `spot_bid_qty`;
- `spot_ask_qty`;
- `spot_top_min_notional_quote`.

CLI/PowerShell exposure:

- Python: `--quality-required-row-fields`;
- Python: `--quality-min-required-row-field-presence`;
- PowerShell: `-FundingQualityRequiredRowFields`;
- PowerShell: `-FundingQualityMinRequiredRowFieldPresence`.

## Verification

- Targeted funding suite with explicit venv Python:
  - `Ran 55 tests ... OK`
- Full trading_mvp test suite with explicit venv Python:
  - `Ran 127 tests ... OK`

## Smoke Collect

Smoke output:

- `exports/trading-mvp/funding/funding_collect_spotliq_smoke_20260615_202617.jsonl`
- Rows: `2`
- Errors: `2`

The smoke rows included the new fields. Strict status on the smoke file showed required field presence:

- `spot_bid_qty`: `1.0`
- `spot_ask_qty`: `1.0`
- `spot_top_min_notional_quote`: `1.0`

## New 24h Spotliq Collector

Started a new 24h collector using the updated schema:

- Metadata: `docs/agent-log/2026-06-15-funding-collect-24h-spotliq-20260615_202709.json`
- Launcher PID: `14080`
- PowerShell child PID: `29320`
- Python PID: `25592`
- Python child PID: `8060`
- Output: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Stdout: `exports/trading-mvp/run/funding_collect_24h_spotliq_20260615_202709.out.log`
- Stderr: `exports/trading-mvp/run/funding_collect_24h_spotliq_20260615_202709.err.log`

First-cycle status:

- `final=false`
- `completed_cycles=1 / 288`
- `rows=24`
- `errors=6`
- `line_count_matches_manifest=true`
- strict readiness: `false`

Strict readiness failed only for expected early-data reasons:

- `status_not_final`;
- `data_quality:min_rows`;
- `data_quality:min_completed_cycles`;
- `data_quality:min_unique_cycles`.

Strict required field presence passed:

- `spot_bid_qty`: `1.0`
- `spot_ask_qty`: `1.0`
- `spot_top_min_notional_quote`: `1.0`

## Next Step

Use the new `funding_collect_24h_spotliq_20260615_202709` dataset as the strict research candidate. Do not run guarded finalize until its manifest has `final=true`, the line count matches manifest rows, and strict `funding-status` no longer reports early-data or schema rejection reasons.
