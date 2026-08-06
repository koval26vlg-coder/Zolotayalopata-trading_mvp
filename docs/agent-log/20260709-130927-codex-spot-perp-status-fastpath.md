# Codex checkpoint: trading_mvp spot/perp status fast-path

Date: 2026-07-09 13:09 +03:00
Agent: Codex
User request: continue current trading_mvp goal.

## Context
- Active gate is READY_FOR_POSTPROCESS, but replay/grid/live are blocked because replay_allowed=false.
- Current next_goal_decision is SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE.
- Public probe was not launched; it still requires explicit user confirmation.

## Changes
- Added a fast-path to tools/trading_next_goal_step.ps1 for spot/perp public-probe awaiting-confirmation state.
- Added the same fast-path to tools/trading_branch_selector.ps1.
- Updated targeted tests in trading_mvp/tests/test_visible_ws_collect_wrapper.py to accept the spot/perp awaiting-confirmation route.

## Verification
- PowerShell parser check: parser_ok.
- tools/trading_next_goal_step.ps1 -Json: 1394 ms, decision=SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION, fast_path=true.
- tools/trading_branch_selector.ps1 -Json: 1729 ms, decision=SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION, selected_branch=spot_perp_basis_mean_reversion_no_funding.
- Targeted unittest: python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper.VisibleWsCollectWrapperTests.test_next_goal_legacy_visible_collect_follows_active_branch trading_mvp.tests.test_visible_ws_collect_wrapper.VisibleWsCollectWrapperTests.test_branch_selector_blocks_stale_funding_next_action -> OK, 2 tests.
- check_active_run_gate.ps1 -Json: READY_FOR_POSTPROCESS, rows=2554, primary_output_complete=true, replay_allowed=false, requires_explicit_user_approval_for_public_probe=true.
- trading_goal_status.ps1 -Json: primary_edge_status=spot_perp_basis_availability_preflight_awaiting_public_probe_confirmation.

## Next Step
Wait for explicit user confirmation before running the short visible public REST spot/perp availability probe. Do not run collect/grid/replay/live/API/paper-forward before that confirmation.
