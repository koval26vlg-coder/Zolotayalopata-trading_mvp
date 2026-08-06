# basis-v2 safe visible chain ready

- Goal remains active: One-Week Historical Edge Sprint.
- Active-run gate verified open as `READY_FOR_POSTPROCESS`; no writer is alive.
- Frozen plan: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_124214.json`.
- Plan hash: `1a5cc89ff97fbe9e97a7ba282a675df5dfda6b89592e2e9b4a2a0e91cf9e24dc`.
- Frozen source snapshot hash: `7b53fcda0e73fb28c592a7a7db0e3d86905684969cdfcc733b4fb828f6b3ef34`.
- Implemented an opt-in visible continuation in `tools\start_historical_basis_v2_collect_visible.ps1`:
  - successful public history collect;
  - separate visible data-quality plus two deterministic train-feasibility repeats;
  - no OOS, grid, retune, live orders, private keys, leverage, or margin;
  - any postprocess failure preserves the completed collector and records `COLLECT_COMPLETED_TRAIN_POSTPROCESS_STOPPED_INCOMPLETE`;
  - protected PIT overlap check covers the whole collector plus train-only pipeline.
- Verification:
  - PowerShell AST: OK;
  - collect and postprocess visible-wrapper tests: 7 OK;
  - all historical-basis-v2 tests: 94 OK;
  - full suite before the wrapper-only change: 861 OK, 5 skipped.
- Sealed read-only preview: `docs\agent-log\run-gates\basis_v2_history_20260716_125552.planonly-preview.json`.
- Preview proves no collector was started: no launch record, run directory, or log exists.
- Planned run: 360 public requests, estimated collect runtime 750 seconds, total hard pipeline cap 3075 seconds, 780.522 GiB free on E:.

## Next action

Await the exact approval phrase from the preview. Then run only its exact `approval_command`. The chain may produce a train-feasibility verdict, but automatic OOS remains blocked.

Exact phrase:

`Подтверждаю visible basis-v2 history collect plan_hash=1a5cc89ff97fbe9e97a7ba282a675df5dfda6b89592e2e9b4a2a0e91cf9e24dc, run_id=basis_v2_history_20260716_125552, MaxRuntimeSec=1200, collect hard deadline=2026-07-16T22:00:00.0000000+03:00, затем visible train-only postprocess MaxRuntimeSec=1800 без automatic OOS, end-to-end runtime cap=3075 sec, public API only, без grid/OOS/live/private API keys.`
