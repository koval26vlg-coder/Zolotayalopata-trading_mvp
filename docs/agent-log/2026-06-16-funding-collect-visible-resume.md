# Funding collect visible resume

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- Original 24h collector stopped before final manifest.

## Original Collector Diagnosis
- Original metadata: `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-06-15-funding-collect-24h-spotliq-20260615_202709.json`
- Original PIDs checked: `14080`, `29320`, `25592`, `8060`.
- All original PIDs were absent.
- Original stdout/stderr logs were empty:
  - `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_collect_24h_spotliq_20260615_202709.out.log`
  - `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_collect_24h_spotliq_20260615_202709.err.log`
- Manifest before resume diagnosis had stopped at `completed_cycles=137`, `rows=3264`, `errors=816`, `final=false`.

## Hidden Resume Handling
- A hidden resume was briefly launched, then stopped because the user explicitly requested a visible terminal.
- Hidden resume process chain stopped: `35268`, `33716`, `27952`, `28496`.
- Before visible relaunch, hidden resume had completed cycle `138`, bringing manifest to `rows=3294`, `errors=816`.

## Visible Resume Launch
- Visible monitor metadata: `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-06-16-funding-collect-24h-spotliq-resume-20260616_1130_visible.json`
- Visible monitor script: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_collect_24h_spotliq_resume_20260616_1130_visible.monitor.ps1`
- Visible monitor PID: `36620`.
- Collector chain observed after launch: `36620 -> 18700 -> 21380 -> 32680`.
- The monitor window prints progress every 60 seconds: cycles, rows, line count, errors, and last write age.
- Output remains the original JSONL:
  - `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest remains the original manifest:
  - `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json`

## Verification
- Condition-based verification waited for a real manifest increment.
- Initial cycle at visible monitor verification: `138`.
- Verified current cycle: `139`.
- Rows: `3324`.
- JSONL line count: `3324`.
- Errors: `816`.
- Last write: `2026-06-16T11:27:58.6743966+03:00`.
- Waited: `10.2` seconds.

## Decision
- Continue the visible-monitored resume.
- Do not run final-review/postprocess until strict `ready_for_postprocess=true`.
