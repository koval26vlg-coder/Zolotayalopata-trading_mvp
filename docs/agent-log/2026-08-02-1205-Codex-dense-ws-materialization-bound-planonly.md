# Dense WS materialization-bound PlanOnly boundary

- Status: `CONTRACT_FREEZE_ONLY_COMPLETE`
- User-approved proposal hash: `a9ec751329e436c1ea30b63433c57cf0e9ffd35370a097735c9ce91f71bb40d7`
- Campaign: `dense_ws_microstructure_regime_filter_v1_20260803_aef_24h`
- Campaign PlanOnly hash: `57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b`
- Frozen signal/evaluator PlanOnly hash: `620b1711a5436c722acea99d41c4b81ba57bd317069456282814939b3eefeea2`

## Implemented

- Added immutable hash-binding builder:
  `trading_mvp/src/dense_ws_materialization_bound_plan.py`
- Added visible bounded launcher with read-only `-PreflightOnly`:
  `tools/build_dense_ws_materialization_bound_planonly_visible.ps1`
- Bound both files by SHA-256 in the authoritative autopilot policy.
- Extended the guard progression:
  `MATERIALIZATION_ACCEPTED` -> visible PlanOnly hash binding ->
  `MATERIALIZATION_BOUND_PLANONLY_READY` -> exact user approval required.
- The builder revalidates campaign, phase, segment, raw BBO, quality,
  causal labels, execution snapshots, and materialization hashes before it
  creates one immutable non-executable PlanOnly.

## Safety boundary

- Evaluator execution: `false`
- Returns/PnL/OOS access: `false`
- Network collector: `false`
- Grid/retune: `false`
- Paper/live/private API/real capital/leverage/margin: `false`
- Output overwrite: forbidden
- Maximum future binding runtime: `1800` seconds
- Next action after successful binding:
  `REQUEST_EXACT_HASH_BOUND_EVALUATOR_APPROVAL`

## Verification

- Targeted unit tests: `52/52 PASS`
- Fast regression: `260/260 PASS`
- Fast regression deterministic result hash:
  `36640d8b8d8ee3740a30a6957ccd4f40f09865f7dad35a4c312ca1e1d5411f69`
- Builder SHA-256:
  `0f4adf30b531090c65d54a910ecfd4cb6ef14a1ff417e54258ae26f730f180a8`
- Visible wrapper SHA-256:
  `4c25abdb9c741a80c541da357f403f850326eeea6bacb036e8d645d4207c9c7a`
- Guard SHA-256:
  `4cb2424b01617e1f32aaf1fa020f8e87f8d9102844bdafdeab3a298a93db4aa6`
- Policy SHA-256:
  `f79f0e029fc4861249a11929545186127223a743411cc9fc8c229511d60da3cc`

No collector, evaluator, returns/PnL/OOS read, grid, retune, paper-forward,
live action, private API access, real capital, leverage, or margin was started.
