# 2026-06-15 funding paper-forward temporal gate

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and prevent paper-forward validation from reusing the same time period as research, even when the input path differs.

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
- Last write age during check: about `325s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added source time-range propagation:

- `evaluate_funding_data_quality` now records `first_ts`, `last_ts`, `span_sec`, `span_hours`;
- `create_funding_paper_forward_plan_file` copies this into `source_data_quality` and `source_time_range`.

Added paper-forward temporal separation:

- `run_funding_paper_forward_file` loads forward rows and checks `forward_first_ts > source_last_ts` when the plan contains `source_time_range`;
- if forward data overlaps the research period, it returns `status=source_time_overlap_blocked`;
- rejected runs write JSONL and summary artifacts with `temporal_gate` and no trade events.

Plans without `source_time_range` remain backward-compatible, but new finalized research plans include the range automatically.

## Verification

- Targeted tests:
  - `Ran 3 tests ... OK`
- Funding basis suite:
  - `Ran 49 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 121 tests ... OK`

## Intended use after collector finalizes

After an accepted 24h research phase creates a paper-forward plan, the next paper-forward input must begin strictly after the research dataset's `last_ts`. This avoids false confidence from validating on the same market period.
