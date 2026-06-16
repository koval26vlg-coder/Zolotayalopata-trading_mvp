# 2026-06-15 Funding Collect Resume Repair

## Context

The 24h funding collector for `funding_collect_24h_rolling_20260615_162045` stopped before completion:

- Original PID: `4356`
- Status after stop: not alive
- Manifest: `final=false`
- Completed cycles: `7 / 288`
- Rows: `144`
- Errors: `38`

No traceback was written to stdout/stderr. The partial dataset must not be postprocessed as final.

## Engineering Fix

Added resumable funding collection:

- `collect_funding_file(..., resume=True)` now loads existing manifest state.
- Resume continues from `completed_cycles + 1`.
- Existing `rows`, `errors`, and `cycle_summaries` are preserved.
- `funding-collect --resume` added to CLI.
- `-FundingResume` added to `trading_mvp/run_mvp.ps1`.

Regression coverage:

- `test_collect_funding_file_resumes_from_manifest`
- `test_cmd_funding_collect_passes_resume_to_collector`
- `test_main_dispatches_funding_collect_resume`

Verification:

- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`
  - Result: `Ran 22 tests ... OK`
- `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`
  - Result: `Ran 94 tests ... OK`

## Dataset Repair

A failed wrapper attempt started without `--resume` and appended one duplicate cycle. It was stopped and repaired:

- Wrong process stopped: PID `25968`
- Child Python stopped: PID `9880`
- Backup JSONL: `exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl.bak_before_resume_repair_20260615_173554`
- Backup manifest: `exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json.bak_before_resume_repair_20260615_173554`
- Last 24 appended rows retagged from duplicate `cycle=1` to `cycle=8`
- Repaired manifest:
  - `final=false`
  - `completed_cycles=8`
  - `rows=168`
  - `errors=44`

## Active Resume

Current resume process:

- Parent PID: `19088`
- Python child PID observed: `22644`
- Metadata: `docs\agent-log\2026-06-15-funding-collect-24h-resume-20260615_173652.json`
- Output: `exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports\trading-mvp\funding\funding_collect_24h_rolling_20260615_162045.manifest.json`
- Resume flag verified in child command line: `--resume`

After first successful resumed cycle:

- Process alive: `true`
- Manifest: `final=false`
- Completed cycles: `9 / 288`
- Rows: `192`
- Errors: `50`
- JSONL line count: `192`
- stderr bytes: `0`

## Next Gate

Do not run `funding-postprocess` until manifest has:

- `final=true`
- `completed_cycles=288`
- stable JSONL line count matching manifest `rows`

Then run guarded rank/backtest/stress/acceptance using the command recorded in `docs/agent-log/2026-06-15-funding-regime-gates.md`.
