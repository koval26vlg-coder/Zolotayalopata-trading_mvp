# trading_mvp spot/perp basis mean-reversion PlanOnly

Date: 2026-07-09 11:06:51 +03:00
Agent: Codex
User request: Continue active trading_mvp goal after listing-event collect/replay branch.

## Plan
- Respect active-run gate and do not start collect/grid/replay/live/API/paper-forward.
- Build the selected spot_perp_basis_mean_reversion_no_funding PlanOnly scaffold.
- Keep funding payout out of PnL; funding may be used only as adverse-regime filter.
- Align controllers so stale listing_event_replay_rejected evidence does not override the current selected branch.

## Completed
- Added 	rading_mvp/src/spot_perp_basis_mean_reversion.py.
- Added 	rading_mvp/tests/test_spot_perp_basis_mean_reversion.py.
- Added 	ools/trading_spot_perp_basis_mean_reversion_planonly.ps1.
- Updated routing in:
  - 	ools/trading_next_goal_step.ps1
  - 	ools/trading_goal_status.ps1
  - 	ools/trading_branch_selector.ps1
  - 	ools/trading_structural_branch_planonly.ps1
- Ran PlanOnly scaffold and updated docs/agent-log/active-run-gate.json.

## Current Artifact
- Output: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\spot_perp_basis_mean_reversion_planonly_20260709_110427.json
- Decision: SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT
- Selected branch: spot_perp_basis_mean_reversion_no_funding
- Strategy accepted: alse
- collect/replay/grid/live/API/leverage/paper-forward: blocked.

## Current Gate
- status: READY_FOR_POSTPROCESS
- next_goal_decision: SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT
- replay_allowed: alse
- next step: build public-data availability preflight PlanOnly for paired spot mid, perp mark/mid, spread/depth and funding-regime fields. Do not start collect/grid/live/API/paper-forward.

## Checks
- PowerShell parser smoke for next-goal, goal-status, branch-selector, structural selector and spot/perp wrapper: OK.
- python -m unittest trading_mvp.tests.test_spot_perp_basis_mean_reversion: 6 OK.
- Regression targeted: python -m unittest trading_mvp.tests.test_spot_perp_basis_mean_reversion trading_mvp.tests.test_listing_event_replay trading_mvp.tests.test_cross_venue_dislocation: 15 OK.
- 	rading_next_goal_step.ps1 -Json: decision SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_RESEARCH.
- 	rading_goal_status.ps1 -Json: primary_edge_status spot_perp_basis_mean_reversion_planonly_research.
- 	rading_branch_selector.ps1 -Json: selected_branch spot_perp_basis_mean_reversion_no_funding.

## Risks / Limits
- This is not a backtest and not an accepted edge.
- Existing daily history has perp/funding hints but no verified paired spot/perp mid/spread/depth history; availability preflight is required before any detector/backtester.
- Do not reopen funding-carry by hiding funding payout inside PnL.

## Next Valid Step
Build spot_perp_basis_availability_preflight PlanOnly: verify, without collecting yet, which public endpoints/files can provide paired non-Binance spot mid, perp mark/mid, spot/perp spread/depth and funding-regime fields for enough bases. Actual collect remains blocked until a new explicit user confirmation.
