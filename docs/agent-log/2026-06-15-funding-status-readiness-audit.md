# 2026-06-15 funding status readiness audit

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and prevent premature postprocess/finalize while the 24h collect is still running.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Final: `false`
- Completed cycles: `35 / 288`
- Rows: `816`
- Errors: `206`
- Line count matches manifest: `true`
- Last write age during latest check: about `278s`
- Strict status readiness: `false`

No postprocess/finalize was started because the manifest is not final.

## Change

Extended `funding_collect_status` with optional data-quality readiness:

- `data_quality_cfg` can be passed without running rank/backtest/OOS;
- status output now includes `readiness`;
- `ready_for_postprocess` is true only when final, line count matches manifest, and optional data-quality gates pass;
- readiness reasons include `status_not_final`, `line_count_mismatch`, `data_quality_error`, and `data_quality:<reason>`.

Extended CLI:

- `funding-status --strict-research`;
- `funding-status --quality-min-rows`;
- `funding-status --quality-min-markets`;
- `funding-status --quality-min-completed-cycles`;
- `funding-status --quality-min-unique-cycles`;
- `funding-status --quality-max-error-rate`;
- `funding-status --quality-max-cycle-market-duplicate-rate`.

Extended PowerShell wrapper:

- `-FundingStrictResearch` now applies to `-Action funding-status`;
- existing funding quality params are passed through for status audits.

## Real strict status output summary

Strict readiness failed for the current running collector with:

- `status_not_final`;
- `data_quality:min_rows`;
- `data_quality:min_completed_cycles`;
- `data_quality:min_unique_cycles`.

Strict quality metrics from the status check:

- rows: `816 / 1000`;
- markets: `24 / 5`;
- completed cycles: `35 / 250`;
- unique cycles: `34 / 250`;
- error rate: about `0.2016 / 0.30`;
- duplicate cycle-market rate: `0.0 / 0.01`.

This means the collector is still too early for finalize, but current error rate and duplicate-row quality are acceptable under the strict preset.

## Verification

- Targeted funding suite with explicit venv Python:
  - `Ran 52 tests ... OK`
- Full trading_mvp test suite with explicit venv Python:
  - `Ran 124 tests ... OK`
- PowerShell wrapper strict status smoke returned readiness/data-quality fields on the live dataset.
