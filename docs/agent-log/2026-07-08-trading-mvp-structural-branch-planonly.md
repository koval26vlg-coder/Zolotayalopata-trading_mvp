# trading_mvp structural branch PlanOnly

- Date: 2026-07-08 17:28:26 +03:00
- Agent: Codex
- User request: continue the trading_mvp goal after base-fee funding/basis rejection.

## Plan
- Obey active-run gate and do not start long runs.
- Convert the next step from a manual text instruction into an executable no-start PlanOnly branch selector.
- Update next-goal/status/preflight/branch-selector routing so the project does not fall back to rejected funding or sweep/reversal paths.

## Done
- Added 	ools/trading_structural_branch_planonly.ps1.
- Selected next branch: cross_venue_spot_dislocation_inventory_rebalance.
- Created PlanOnly artifact: $artifact.
- Updated docs/agent-log/active-run-gate.json to 
ext_goal_decision=IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH.
- Updated 	ools/trading_next_goal_step.ps1, 	ools/trading_branch_selector.ps1, 	ools/trading_goal_status.ps1, 	ools/trading_edge_preflight.ps1.
- Updated 	rading_mvp/tests/test_visible_ws_collect_wrapper.py.

## Current Decision
- Funding/basis carry remains rejected under base/VIP0/no-volume fees.
- Next branch is cross-venue MEXC/Gate spot dislocation / inventory-rebalance research.
- Next engineering step: implement a read-only PlanOnly detector/backtester on existing clean 72h MEXC/Gate data.

## Guardrails
- No live orders.
- No API keys.
- No leverage/margin.
- No grid-search or new collector yet.
- No paper-forward until OOS/walk-forward/stress/economics gates pass.
- Win rate is secondary; optimize net expectancy after costs.

## Verification
- PowerShell parser check: OK for structural branch script, next-goal, branch-selector, goal-status and preflight.
- Structural branch PlanOnly smoke: OK, would_start=false, selected cross-venue branch.
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: OK, 21 tests, skipped=3.
- python -m unittest trading_mvp.tests.test_cli_ws_input_guard: OK, 5 tests.
- 	ools/trading_edge_preflight.ps1 -Json: OK, fail_count=0, warn_count=1 (SWARM_REVIEW_INCOMPLETE).

## Next Agent Step
Implement cross_venue_spot_dislocation read-only PlanOnly detector/backtester using existing market-filtered 72h MEXC/Gate data. First output should be a no-start plan/artifact and candidate event extraction, not live execution or a long collector.
