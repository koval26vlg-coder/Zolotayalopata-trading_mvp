# trading_mvp basis-v2 refreeze ready

Date: 2026-07-16 11:22 +03:00

## State

- Goal remains active: One-Week Historical Edge Sprint.
- Active-run gate: `READY_FOR_POSTPROCESS`; no live market-data writer.
- No collector, OOS evaluation, grid, probe, paper-forward, live order, private API key, leverage, or margin action was started.

## Audit findings fixed

1. Downstream quality/evaluator/postprocess code could run from a newer snapshot while reporting the frozen plan snapshot hash. Runtime snapshot binding is now fail-closed.
2. The 4h robustness check previously passed with zero episodes.
3. The 4h robustness check previously allowed favorable funding to hide negative price-only PnL.
4. The 4h checks were implicit evaluator behavior. They are now explicit, hash-bound acceptance gates.

## Verification

- TDD RED observed for missing runtime binding and both 4h false-accept paths.
- Related regression: 78/78 passed.
- Full regression: 848 passed, 5 skipped, 0 failed.
- Full log: `exports/trading-mvp/run/full_tests_basis_v2_refreeze_20260716.log`.
- `git diff --check`: no whitespace errors; only existing LF/CRLF warnings.

## New frozen artifact

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_111804.json`
- Plan hash: `aaedb59d88c5194528b35687a9dd02dbd902185d60e7a1193d24c7a2bcc6e5bb`
- Plan file SHA-256: `58eb7514e1061b96fceddcdc1cb11161677f2a588b45a4c70efc5070ca6046cf`
- Code snapshot hash: `aa8a0dbebd13a8f06eb0501fdcfc746d677e0faf74c731e10ae53a41139fa48a`
- Core module SHA-256: `909693eedf8cb1fc60fa92240ced00c5554079f10190f2a90d6b84cd81751609`
- Previous plan hash `710307b8dbb49f05089e1f3bccbb597c7107bfc505d2cf3e9488d7fa738c7faa` is archival and must not be collected/evaluated.

## Next gated action

Visible public history collect only after the exact approval phrase:

`Подтверждаю visible basis-v2 history collect plan_hash=aaedb59d88c5194528b35687a9dd02dbd902185d60e7a1193d24c7a2bcc6e5bb, run_id=basis_v2_history_20260716_1120, MaxRuntimeSec=1200, hard deadline=2026-07-16T13:00:00.0000000+03:00, public API only, без grid/OOS/live/private API keys.`

PlanOnly estimate: 360 public requests, 750 seconds, maximum 1200 seconds, 20 candidates, 780.5 GiB free on output volume.
