# trading_mvp basis-v2 OOS postprocess checkpoint

- Timestamp: 2026-07-16T10:54:22+03:00
- Agent: Codex
- Scope: bounded offline implementation and verification
- Active-run gate after work: `READY_FOR_POSTPROCESS`
- Real public-history collector started: no
- Real OOS dataset opened: no
- Grid, retune, live orders, private API keys, leverage/margin: no

## Implemented

- Added `trading_mvp/src/historical_basis_v2_oos_postprocess.py`.
- Added `tools/start_historical_basis_v2_oos_postprocess_visible.ps1`.
- Added `fast-edge-basis-v2-oos-postprocess` to `trading_mvp/run_mvp.ps1`.
- OOS is accepted only from a final `READY_FOR_OOS_EVALUATION_NOT_RUN` train manifest with two matching hash-bound `FEASIBLE_FOR_OOS` artifacts.
- The orchestrator runs two full-evaluation repeats using one selected, already cross-checked feasibility artifact, requires identical deterministic hashes/verdicts, and then builds the terminal report.
- Any timeout, invalid provenance, or repeat mismatch writes `STOPPED_INCOMPLETE`; partial ACCEPT is forbidden.
- `PlanOnly` validates provenance without opening OOS files or creating output/launch artifacts.

## Verification

- TDD RED observed for missing module, missing action, and missing visible wrapper.
- Targeted OOS/run_mvp/visible tests: 11 passed.
- Related basis-v2/evaluator/report/gate regression: 61 passed.
- Full regression A: 706 passed.
- Full regression B: 137 passed, 5 skipped.
- Total fresh full regression: 843 passed, 5 skipped, 0 failed.
- PowerShell parser accepted `run_mvp.ps1` and all three basis-v2 visible wrappers.
- `git diff --check` reported no tracked whitespace errors.

## Key hashes

- OOS orchestrator SHA-256: `ae21902a57279197ec53d47c42df00e04196b9cac5551529f3415df4e11a7a7a`
- Visible OOS wrapper SHA-256: `3f227b275ceb271b04c8e39d96f15d84f9874fa8b7c0785f19aef113cb429238`
- `run_mvp.ps1` SHA-256: `0ef857844a1ee885f66cdfa311d3ce44d93cb5ef7682b668b3075cedd97c9563`

## Next critical gate

The frozen plan still needs one explicitly approved visible public-history collect (`MaxRuntimeSec=1200`). After its final manifest, run train postprocess. Only `FEASIBLE_FOR_OOS` permits the new visible OOS postprocess; all other train outcomes close the branch without OOS or retuning.
