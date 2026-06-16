# 2026-06-15 funding paper-forward plan validation

Goal context: continue the research-only `trading_mvp` objective without live orders, API keys, leverage, or margin execution.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `23 / 288`
- Rows: `528`
- Manifest rows: `528`
- Line count matches manifest: `true`
- Errors: `134`
- Last write age: about `101s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added validation inside `run_funding_paper_forward_file` so a manually forged plan cannot pass only by setting `ready_for_paper_forward=true`.

The runner now rejects ready plans when:

- `research_only` is not exactly `true`;
- `live_orders` is not exactly `false`;
- `api_keys_required` is not exactly `false`;
- `leverage_enabled` is not exactly `false`;
- `margin_execution` is not exactly `false`;
- strict research evidence is missing from `research_acceptance`;
- `research_gate_reasons` is not empty.

Rejected plans write both JSONL and summary artifacts with `plan_gate_reasons`, without trade events.

## Verification

- Red check before implementation:
  - `test_paper_forward_rejects_forged_live_orders_plan`: failed because current code returned `ok=true`.
  - `test_paper_forward_rejects_forged_plan_without_research_evidence`: failed because current code returned `ok=true`.
- Targeted tests after implementation:
  - `Ran 4 tests ... OK`
- Funding basis suite:
  - `Ran 42 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 114 tests ... OK`

## Next gate

Continue monitoring the 24h collector. Only run guarded `funding-finalize` after:

- `final=true`;
- `completed_cycles=288`;
- `line_count_matches_manifest=true`.
