# trading_mvp funding/basis PlanOnly after sweep rejection

- Time: 2026-07-08 16:27:37 +03:00
- Agent: Codex
- User request: continue after liquidity_sweep_reversal was rejected; select the next research branch through PlanOnly without grid/live/API keys.

## What changed
- Added 	ools/trading_funding_basis_planonly.ps1 to produce one research-only PlanOnly packet from existing funding/basis diagnostics.
- Updated 	ools/trading_branch_selector.ps1, 	ools/trading_next_goal_step.ps1, 	ools/trading_goal_status.ps1, and 	ools/trading_edge_preflight.ps1 so active gate FUNDING_BASIS_CARRY_PLANONLY_CURRENT_COST_NOT_ACCEPTED stays on PlanOnly and does not route back to rejected liquidity_sweep_reversal / dense WS collect.
- Updated 	rading_mvp/tests/test_visible_ws_collect_wrapper.py to assert PlanOnly behavior when liquidity_sweep_rejected_gate=true.
- Updated docs/agent-log/active-run-gate.json with the selected branch and next-step guard.

## PlanOnly result
- Artifact: $(C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_basis_planonly_20260708_162124.json.FullName)
- Decision: FUNDING_BASIS_PLANONLY_CURRENT_COST_NOT_ACCEPTED
- Branch: unding_basis_carry_structural_planonly
- Current-cost model: not accepted.
- Fee-tier evidence: missing.
- Rank eligible: 0.
- Total trades: 0.
- Watchlist: research focus only, not tradeable.

## Current allowed next step
- No collect/grid/live/API/paper-forward.
- If user can provide non-secret actual maker/taker fee tiers for MEXC/Gate spot+perp, store fee evidence and rerun 	ools/trading_funding_basis_planonly.ps1.
- Otherwise design a new non-HFT structural research branch.

## Verification
- PowerShell parser check: OK.
- 	rading_branch_selector.ps1 -Json: NEXT_BRANCH_FUNDING_BASIS_CARRY_PLANONLY, actual collect approval false.
- 	rading_next_goal_step.ps1 -Json: FUNDING_BASIS_CARRY_STRUCTURAL_PLANONLY, primary command is PlanOnly.
- 	rading_goal_status.ps1 -Json: PlanOnly resolution.
- 	rading_edge_preflight.ps1 -Json: OK, 0 failures, 1 warning (SWARM_REVIEW_INCOMPLETE).
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: OK, 20 tests, skipped=3.
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_cli_ws_input_guard: OK, 5 tests.

## Risks and constraints
- This is not a trading signal and not investment advice.
- No live orders, API keys, leverage, margin, paper-forward or grid are allowed from this branch.
- Funding/basis remains economically unaccepted under current cost assumptions.
