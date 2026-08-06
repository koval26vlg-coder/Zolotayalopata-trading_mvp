# trading_mvp base-fee funding rejection

- Time: 2026-07-08 16:45:55 +03:00
- Agent: Codex
- User input: all target exchange accounts are at base/no-volume tier, so fees should be treated as the highest ordinary tier; no fee discounts/VIP assumptions.

## What changed
- Created non-secret operational constraint: $constraintPath.
- Updated 	ools/trading_funding_basis_planonly.ps1 to read the base-fee constraint.
- Updated branch/status/preflight controllers so funding/basis rejected under base fees routes to DESIGN_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY, not funding fee rescue or WS collect.
- Updated tests for unding_rejected_base_fees_gate.
- Updated active gate next step to select a new non-HFT structural research branch.

## Current decision
- Latest PlanOnly artifact: $(C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_basis_planonly_20260708_163823.json.FullName)
- Decision: FUNDING_BASIS_PLANONLY_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH
- Funding/basis carry is rejected for the current project state under base/VIP0/no-volume fees.
- No collect/grid/live/API/paper-forward is allowed.

## Verification
- PowerShell parser check: OK.
- 	rading_next_goal_step.ps1 -Json: DESIGN_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY, actual collect approval false.
- 	rading_goal_status.ps1 -Json: legacy visible collect resolves to manual PlanOnly design, not WS/funding collect.
- 	rading_edge_preflight.ps1 -Json: OK, 0 failures, 1 warning (SWARM_REVIEW_INCOMPLETE).
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: OK, 20 tests, skipped=3.
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_cli_ws_input_guard: OK, 5 tests.

## Next step
Design the next non-HFT structural research branch through PlanOnly with explicit data requirements, OOS/walk-forward/stress/economics gates. Do not reopen funding/basis via maker/VIP/reduced-fee sensitivity rows unless the project objective changes.
