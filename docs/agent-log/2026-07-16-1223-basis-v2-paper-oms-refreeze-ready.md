# trading_mvp basis-v2 paper OMS and final refreeze ready

Date: 2026-07-16 12:23 +03:00

## State

- Goal remains active: One-Week Historical Edge Sprint.
- Active-run gate is `READY_FOR_POSTPROCESS`; no market-data writer is running.
- No history collect, OOS, execution probe, paper-forward market process, grid, live order, private API key, leverage, or margin action was started.
- PIT shadow schedule remains independent and unchanged.

## Implemented

- Added `historical_basis_v2_paper_oms.py` with immutable paper PlanOnly creation, v2 state/ledger schemas, two-leg position lifecycle, funding and fee accounting, WAL recovery, reconciliation, data-quality and daily-loss kill switches.
- Added a 15-independent-event gate. The maximum result is `LIVE_REVIEW_ELIGIBLE`; it never authorizes live execution.
- Preserved the existing v1 paper OMS API by parameterizing its internal contract while keeping v1 schemas and validators as defaults.
- Added exact `run_mvp.ps1` actions: `fast-edge-basis-v2-paper-plan`, `fast-edge-basis-v2-paper-init`, `fast-edge-basis-v2-paper-observe`, and `fast-edge-basis-v2-paper-status`.
- Strengthened execution-probe provenance: terminal reports now bind each window manifest by path, file SHA-256, result hash, and recomputed raw-sample metrics before paper PlanOnly can be created.
- Probe `PAPER_FORWARD_READY` now emits the exact next action `fast-edge-basis-v2-paper-plan`.

## Verification

- TDD RED observed for the missing module and CLI actions.
- Targeted final suite: 22 passed, 0 failed.
- Full regression before the final next-command string assertion: 861 passed, 5 skipped, 0 failed in 326.786 seconds.
- Python compilation and PowerShell parsing passed.
- `git diff --check` passed; only the existing LF/CRLF warning for `run_mvp.ps1` remains.
- Full log: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\full_tests_basis_v2_paper_oms_20260716.log`.

## New frozen artifact

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_122129.json`
- Plan hash: `ae2ff278e5efe5c4885b9917fa60ea23d1c09db2012fd7f439790eb2751d04d1`
- Plan file SHA-256: `63b4c3ae1d04a0c517fcc751d250525a2de4d1e5f23cf01c710a009bfd44fcf2`
- Code snapshot hash: `8376a0bf19ecce9a1fa9e0950e4a0c812a656b667b044d41760f5c10bf47ade1`
- Snapshot manifest SHA-256: `8939bd0d797806a6a3a99b12d46f58ebb31ca7a4d5659103514e57bd45aa2c9c`
- Snapshot contains the v1 OMS core, v2 execution probe, and v2 paper OMS.
- Previous plan hashes `3ce7e5a5f4e6bbcc2646cecc0a677342c17fa5c98eb1a5821c0d568a87cb1667` and `aaedb59d88c5194528b35687a9dd02dbd902185d60e7a1193d24c7a2bcc6e5bb` are archival and must not be collected or evaluated.

## Next gated action

Visible public history collect only after this exact approval phrase:

`Подтверждаю visible basis-v2 history collect plan_hash=ae2ff278e5efe5c4885b9917fa60ea23d1c09db2012fd7f439790eb2751d04d1, run_id=basis_v2_history_20260716_122300, MaxRuntimeSec=1200, hard deadline=2026-07-16T22:00:00.0000000+03:00, public API only, без grid/OOS/live/private API keys.`

PlanOnly estimate: 360 public requests, 750 seconds, hard runtime cap 1200 seconds, 20 candidates, 780.525 GiB free on output volume.
