# trading_mvp basis-v2 train postprocess checkpoint

- Timestamp: 2026-07-16T10:36:13+03:00
- Scope: offline deterministic infrastructure only
- Active-run gate after verification: `READY_FOR_POSTPROCESS`
- Market-data collector started: no
- OOS read/evaluation started: no
- Grid, retune, live orders, private API keys, leverage/margin: no

## Implemented

- Added `historical_basis_v2_postprocess.py` to validate a final collector manifest, run quality, and execute exactly two deterministic train-feasibility repeats.
- Added the visible bounded wrapper `start_historical_basis_v2_train_postprocess_visible.ps1` with a 1,800-second hard limit and a read-only `PlanOnly` mode.
- Added `fast-edge-basis-v2-train-postprocess` to `run_mvp.ps1`.
- Fixed the terminal report contract so canonical evaluator `metrics` and `four_hour_robustness` are preserved.
- Kept OOS sealed: a feasible train result stops at `READY_FOR_OOS_EVALUATION_NOT_RUN`.

## Verification

- PowerShell parser: `run_mvp.ps1` and both visible basis-v2 wrappers parsed without errors.
- Targeted tests: 23 passed.
- Related regression: 48 passed.
- Full regression A: 698 passed.
- Full regression B: 137 passed, 5 skipped.
- Total fresh full regression: 835 passed, 5 skipped, 0 failed.
- `git diff --check`: no whitespace errors in tracked changes.

## Frozen input

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_094355.json`
- Plan hash: `710307b8dbb49f05089e1f3bccbb597c7107bfc505d2cf3e9488d7fa738c7faa`
- Plan file SHA-256: `c864ceebb531f7614cb9c97fce34e25140f98dbe9edaba7dbaf22aab18bb25e9`

## Next gate

The only critical-path action is one explicitly approved, visible, public-history collect with `MaxRuntimeSec=1200`. After a final manifest exists, run the new train-only postprocess. Do not run OOS until train feasibility passes.
