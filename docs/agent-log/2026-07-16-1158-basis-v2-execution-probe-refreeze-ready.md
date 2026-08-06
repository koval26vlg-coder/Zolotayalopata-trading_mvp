# trading_mvp basis-v2 execution-probe refreeze ready

Date: 2026-07-16 11:58 +03:00

## State

- Goal remains active: One-Week Historical Edge Sprint.
- Active-run gate: `READY_FOR_POSTPROCESS`; no live market-data writer.
- No history collector, OOS evaluation, execution probe, grid, paper-forward, live order, private API key, leverage, or margin action was started.
- Approved PIT shadow schedule is independent and unchanged.

## Implemented proof path

- Added immutable/hash-bound execution-probe PlanOnly, public MEXC/Gate BBO/depth collector, raw-sample recomputation, and three-window terminal evaluation.
- Probe gates require exactly three final windows, at least 180 valid snapshots per base/window, at least 80% coverage, p95 timestamp skew at most 2000 ms, at least USD 500 capacity per leg, and p95 impact at most 10 bps.
- Probe authority is capped at `PAPER_FORWARD_PLANONLY`; it cannot authorize live trading.
- Historical report now emits the exact next action `fast-edge-basis-v2-execution-probe-plan` only after full historical acceptance.
- Existing paper OMS remains v1-specific. A separate v2 paper snapshot is intentionally deferred until `PAPER_FORWARD_READY`; it is not represented as ready now.

## Verification

- TDD RED was observed for the missing probe module/actions, provenance binding, owned run id, and tamper handling.
- Targeted suite: 18/18 passed.
- Full regression: 857 passed, 5 skipped, 0 failed in 317.009 seconds.
- Full log: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\full_tests_basis_v2_execution_probe_20260716.log`.
- Python compilation, PowerShell parsing, and diff whitespace checks passed.

## New frozen artifact

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_115419.json`
- Plan hash: `3ce7e5a5f4e6bbcc2646cecc0a677342c17fa5c98eb1a5821c0d568a87cb1667`
- Plan file SHA-256: `b8f4a1b08307a57f4909ac66517ad88797ec2bd7d9546e724316af70540bd74b`
- Code snapshot hash: `a96f6b96546eff10f8cb44922f5a28759dfb74953aaeb92a794dd78fe3d152e8`
- Snapshot manifest SHA-256: `6f45561767db97e68d0f8d0ace7485b8a91d1852281a8d54805621ed8ff9a72e`
- Preflight hash: `83b87e3ffe327787e807007eaa2399714964ceeadb93e0a73b6e11a90d5bae77`
- Candidate count: 20.
- Previous plan hash `aaedb59d88c5194528b35687a9dd02dbd902185d60e7a1193d24c7a2bcc6e5bb` is archival and must not be collected or evaluated.

## Next gated action

Visible public history collect only after the exact approval phrase:

`Подтверждаю visible basis-v2 history collect plan_hash=3ce7e5a5f4e6bbcc2646cecc0a677342c17fa5c98eb1a5821c0d568a87cb1667, run_id=basis_v2_history_20260716_115900, MaxRuntimeSec=1200, hard deadline=2026-07-16T22:00:00.0000000+03:00, public API only, без grid/OOS/live/private API keys.`

PlanOnly estimate: 360 public requests, 750 seconds, hard runtime cap 1200 seconds, 20 candidates, 780.528 GiB free on output volume.
