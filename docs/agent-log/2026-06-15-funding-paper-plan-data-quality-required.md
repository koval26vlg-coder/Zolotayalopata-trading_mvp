# 2026-06-15 funding paper-plan data-quality required

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and ensure paper-forward plans are created only from research artifacts that passed data-quality and include a source time range.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `33 / 288`
- Rows: `768`
- Manifest rows: `768`
- Line count matches manifest: `true`
- Errors: `194`
- Last write age during check: about `195s`

No postprocess/finalize was started because the manifest is not final.

## Change

`create_funding_paper_forward_plan_file` now requires:

- accepted `research_acceptance`;
- explicit successful full backtest, OOS, and stress evidence;
- `data_quality.accepted == true`;
- `source_time_range` derived from `data_quality.metrics.first_ts/last_ts`.

If data-quality evidence is missing or rejected, the plan returns:

- `status=research_gate_evidence_missing`;
- `ready_for_paper_forward=false`;
- reasons such as `data_quality_missing`, `data_quality_not_accepted`, or `source_time_range_missing`.

`run_funding_paper_forward_file` also validates ready plans directly, so a forged `ready_for_paper_forward=true` plan cannot bypass the data-quality/source-time evidence checks.

## Verification

- Targeted tests:
  - `Ran 5 tests ... OK`
- Funding basis suite:
  - `Ran 50 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 122 tests ... OK`

## Intended use after collector finalizes

The final `funding-finalize` run must create a postprocess summary with accepted `data_quality`. Only then can `funding-paper-plan` create a ready paper-forward plan. This keeps the transition to paper-forward tied to verified data coverage and prevents manually forged or incomplete research summaries from advancing.
