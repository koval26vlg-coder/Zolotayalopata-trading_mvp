# 2026-06-16 Funding Final Review Wait

## Goal
Allow `funding-final-review` to optionally wait for strict collector readiness before running final postprocess, while keeping the default behavior unchanged and research-only.

## Collector Status
- status: `running_or_waiting`
- `ready_for_postprocess=false`
- cycles: `82 / 288`
- rows: `1968`
- errors: `492`
- blockers: `status_not_final`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Final postprocess was not run.

## Code Changes
- Added optional wait flags to `funding-final-review`:
  - `--wait-timeout-sec`
  - `--wait-poll-interval-sec`
  - `--wait-stale-after-sec`
  - `--wait-output`
- `funding-final-review` now can call `wait_funding_ready` before final review when `--wait-timeout-sec > 0`.
- Default behavior remains unchanged: no wait when `--wait-timeout-sec=0`.
- PowerShell `funding-final-review` passes wait flags only when `-DurationSec > 0`.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted parser test: OK.
- Full suite: `python -m unittest discover -s trading_mvp/tests`
  - result: `162 tests OK`.
- PowerShell smoke:
  - action: `funding-final-review`
  - `-DurationSec 0`
  - output: `exports/trading-mvp/funding/funding_final_review_guard_wait_patch_20260616.json`
  - status: `not_ready_for_postprocess`
  - artifacts_created: `[]`
  - downstream reports for timestamp `20260616_011112`: absent.

## Next Gate
When a hands-off continuation is needed, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 `
  -Action funding-final-review `
  -FundingStrictResearch `
  -DurationSec <wait_timeout_sec> `
  -PollIntervalSec 300 `
  -InputPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl `
  -ManifestPath C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json
```

This will wait for strict readiness first, then run guarded final review. If readiness is still false, it writes a not-ready review and does not create downstream artifacts.
