# Funding terminal watch

## Goal Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- Current 24h funding collector is still running; final-review/postprocess was not run.

## Change
- Added terminal watcher: `C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\watch_funding_collect.ps1`.
- The watcher displays:
  - state/readiness;
  - ASCII progress bar;
  - completed/remaining cycles;
  - ETA based on recent manifest cycle timestamps;
  - line count vs manifest rows;
  - errors/attempts/error rate;
  - last-write age/stale state;
  - configured/alive/missing PIDs;
  - input/manifest paths.
- The watcher writes a machine-readable snapshot JSON every refresh.
- Default mode is monitor-only. It does not stop or start collectors unless `-AutoResume` and `-ResumeCommand` are explicitly provided.
- Line counting uses `FileShare.ReadWrite`, so it works while the collector is actively appending to the JSONL.

## Current Smoke
- Command: `watch_funding_collect.ps1 -WatchOnce -NoClear` against the current 24h collector.
- Snapshot: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_watch_smoke_20260616.json`
- State: `running_or_waiting`
- Ready for postprocess: `false`
- Completed cycles: `131 / 288`
- Progress: `45.49%`
- ETA local: `2026-06-16 23:33:37 +03:00`
- Rows: `3144`, manifest rows: `3144`, match: `true`
- Processes alive: `4 / 4`

## Resume Helper
- Created resume script: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_collect_24h_spotliq_20260615_202709.resume.ps1`.
- It reuses the original launch parameters and adds `-FundingResume`.
- Use this only if the current collector is stale/dead; watcher can auto-start it when explicitly configured.

## Verification
- `watch_funding_collect.ps1` PowerShell parser: OK.
- `funding_collect_24h_spotliq_20260615_202709.resume.ps1` PowerShell parser: OK.
- Live watcher smoke: OK, including reading JSONL while collector holds the file open.

## Decision
- Do not run final rank/backtest/decision artifacts yet.
- Use watcher for terminal progress. Run strict final-review only after watcher/audit reports `ready_for_postprocess=true`.
