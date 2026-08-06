# trading_mvp WS collect ready for postprocess

Date: 2026-06-28
Agent: Codex
Request: пользователь спросил "что с прогоном" после видимого 6h WS collect.

## Findings
- Run id: `ws_collect_6h_sweep_visible_20260627_210337`.
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\raw\ws_collect_20260628_000346.json`.
- Result: `ok=true`, `total_events=2745067`, `errors={}`.
- MEXC: 8 symbols, 2083425 events, duration 21602.1148 sec, no errors.
- Gate.io: 8 symbols, 661642 events, duration 21601.8631 sec, no errors.
- Stale monitor PID `23612` remained alive after collector completion and made `check_active_run_gate.ps1` report `RUNNING` incorrectly.

## Changes
- Closed stale monitor PID `23612`.
- Updated `docs/agent-log/active-run-gate.json` to `READY_FOR_POSTPROCESS` with manifest path and duration metrics.
- Patched `tools/check_active_run_gate.ps1` to respect explicit `READY_FOR_POSTPROCESS` for WS manifests that do not include funding-style `final=true`.
- Added regression coverage in `trading_mvp/tests/test_active_run_gate.py`.

## Verification
- `check_active_run_gate.ps1 -Json` returns `status=READY_FOR_POSTPROCESS`.
- Targeted tests: `python -m unittest trading_mvp.tests.test_active_run_gate` via bundled Python, 4 tests OK.

## Next Step
Run guarded ws-postprocess on the manifest, then replay-validation PlanOnly with the same manifest. Do not run live orders, API keys, leverage/margin, or investment-advice workflows.
