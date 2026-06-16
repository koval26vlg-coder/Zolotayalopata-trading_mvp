# 2026-06-16 Funding Final Review Gate

## Goal
Keep the funding/basis carry research pipeline research-only and prevent final postprocess artifacts from being created before the 24h collector is final and passes strict data-quality readiness.

## Code Changes
- Added `default_funding_final_review_path` and `run_funding_final_review_file` in `trading_mvp/src/basis.py`.
- Added CLI command `funding-final-review` in `trading_mvp/src/cli.py`.
- Added PowerShell action `funding-final-review` in `trading_mvp/run_mvp.ps1`.
- Added tests for not-ready guard behavior and CLI parser/strict preset coverage.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- `python -m unittest trading_mvp.tests.test_basis.BasisTests.test_funding_final_review_blocks_not_final_collect_before_downstream_artifacts trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands`: OK.
- `python -m unittest discover -s trading_mvp/tests`: 156 tests OK.

## Live Guard Check
Command:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 `
  -Action funding-final-review `
  -FundingStrictResearch `
  -InputPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl `
  -ManifestPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json `
  -OutputPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_final_review_guard_20260616.json
```

Result:
- status: `not_ready_for_postprocess`
- ready_for_postprocess: `false`
- cycles: `78 / 288`
- line_count: `1872`
- artifacts_created: `[]`
- readiness reasons: `status_not_final`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Downstream artifacts for the guard timestamp were not created:
- `funding_gate_report_20260616_005334.json`: absent
- `funding_frontier_report_20260616_005334.json`: absent
- `funding_sensitivity_20260616_005334.json`: absent
- `funding_decision_report_20260616_005334.json`: absent

## Next Gate
When `funding-status --strict-research` reports `ready_for_postprocess=true`, run `funding-final-review` again. Only then should final `postprocess`, `rank`, `backtest`, `OOS`, `walk-forward`, `frontier`, `sensitivity`, `decision`, and optional `paper-plan` artifacts be created.
