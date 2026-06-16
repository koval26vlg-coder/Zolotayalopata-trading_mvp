# Funding collect diagnostics CLI

## Goal Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- Current 24h funding collector is still running; final-review/postprocess was not run.

## Change
- Added reproducible `funding-collect-diagnostics` artifact generation.
- Added Python CLI command and PowerShell `run_mvp.ps1` action.
- Diagnostics report partial/final collect quality, economics, missing fields, error breakdown, per-exchange rows, score distributions, and top rows by score/expected carry.
- Notes explicitly mark partial diagnostics as non-acceptance evidence.

## Verification
- `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: exit 0.
- Targeted unittest: `test_funding_collect_diagnostics_reports_partial_quality_and_economics` and `test_cli_parser_accepts_funding_commands`: `2 tests OK`.
- Full unittest discover: `187 tests OK`.
- `trading_mvp/run_mvp.ps1` PowerShell parser: `PowerShell syntax OK`.

## CLI Smoke
- Input: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Output: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_diagnostics_cli_smoke_20260616_0555.json`
- Completed cycles: `101 / 288`
- Progress: `35.07%`
- Rows: `2424`
- Rows match manifest: `true`
- Errors: `606`
- Eligible rows: `1592`
- Positive funding rows: `1726`
- Positive expected net carry rows: `0`
- Manifest error breakdown: `mexc:match_contract:no_perp_contract=404`, `gateio:match_contract:no_perp_contract=202`

## Strict Audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_0600.json`
- Stage: `collecting_funding`
- Accepted: `false`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `101 / 288`
- Remaining cycles: `187`
- Progress: `35.07%`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`
- Next action: `wait_and_recheck`

## Process Status
- PIDs still present during check: launcher `14080`, child `29320`, python `25592`, python child `8060`.

## Decision
- Do not run `funding-final-review`, `funding-rank`, or `funding-backtest` on this 24h dataset yet.
- Continue condition-based readiness checks and run strict final-review only after `ready_for_postprocess=true`.
