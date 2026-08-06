# 2026-07-17 04:22 +03 - Gate spot/perp v2 terminal closure

## State

- Active-run gate: `READY_FOR_POSTPROCESS`, terminal closure `1/1`, `final=true`, `errors=0`.
- Hypothesis: `gate_spot_perp_basis_convergence_history_v2`.
- Verdict: `INFEASIBLE_ON_CURRENT_DATA`.
- Reason: frozen economic entry threshold `132 bps` was absent in 100 train days; maximum basis `122.022080 bps`.
- OOS/grid/retune/probe/paper/live: not run and forbidden for this branch.

## Artifacts

- Closure: `E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2\reports\gate_spot_perp_train_closure_20260717_fast_faa446e2e44d.closure.json`.
- Closure artifact hash: `a3cd42541c8134bd70043c1056f5b230a7b930eaf71ae1ab2ea408270a9866bd`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2\reports\gate_spot_perp_train_closure_20260717_fast_faa446e2e44d.closure.manifest.json`.
- Manifest hash: `7cc52bc37f65023bf75408287ff34bff13ecc74bd0e410bcbcc403fa76cadc5a`.
- Analysis: `docs/analysis/2026-07-17-gate-spot-perp-v2-train-closure.md`.

## Code

- Added `trading_mvp/src/spot_perp_basis_history_v2_report.py`.
- Added `trading_mvp/tests/test_spot_perp_basis_history_v2_report.py`.
- Added `tools/run_gate_spot_perp_train_closure_visible.ps1`.
- Added a dedicated experiment-registry setup instead of misclassifying this branch as funding carry.
- Fixed terminal-manifest counter fallback in `tools/check_active_run_gate.ps1`.

## Verification

- Closure read-back: `valid=true` with all parent file hashes unchanged.
- Focused strategy tests: `11 OK`.
- Active gate and closure tests: `22 OK`.
- Experiment ledger: `exp_20260717_012350_7590ffaf6e03`, canonical ledger SHA-256 `4eee54cdfd2d15934127cce0d7c2ed74a02ec791004ae428b72f54abce9b769e`.
- Exact regression subset after Windows encoding/atomic-write fixes: `15 OK`, `1 skipped`.
- Full visible regression `trading_mvp_full_regression_20260717_045201`: `940 OK`, `5 skipped`, `0` failures/errors, `379.377s`, `exit_code=0`.
- Next: do not manufacture another factor on the same current-universe cache; continue PIT shadow evidence or source a materially new point-in-time/delisted-universe dataset under a new PlanOnly.
