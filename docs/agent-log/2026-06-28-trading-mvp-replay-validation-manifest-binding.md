# Trading MVP replay validation manifest binding hardening

- time: 2026-06-28 16:24:51 +03:00
- agent: Codex
- user_request: continue active trading_mvp goal
- goal: prove or reject a high-winrate trading edge for non-Binance markets through data/backtest/OOS/walk-forward/stress/economics/paper-forward gates.

## Context
- Active run gate checked first: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700.
- No long collect, replay, grid, paper-forward, live order, API-key, leverage or margin action was started.
- Current strategy acceptance remains false.

## Change
- Hardened tools/run_ws_replay_validation_visible.ps1:
  - If -ConfirmedResearchRun is used without -ExpectedManifestPath, wrapper now returns a blocked JSON result with reason=expected_manifest_required_for_confirmed_research_run.
  - This prevents stale ws_postprocess_*.json artifacts from being replayed/gridded without explicit binding to the completed ws_collect_*.json manifest.
- Updated tools/trading_edge_preflight.ps1:
  - ws_replay_validation_quality_gate now requires the new manifest-required guard.
- Updated trading_mvp/tests/test_visible_ws_collect_wrapper.py:
  - Added regression test for ConfirmedResearchRun without ExpectedManifestPath.

## Verification
- Negative smoke:
  - run_ws_replay_validation_visible.ps1 -PostprocessPath current artifact -ConfirmedResearchRun -NoPause returned ok=false, would_run=false, reason=expected_manifest_required_for_confirmed_research_run.
- Positive PlanOnly smoke:
  - Same artifact with matching -ExpectedManifestPath and -PlanOnly returned ok=true, would_run=false.
- Targeted tests: python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate -> 14 OK, 1 skipped.
- Full tests: python -m unittest discover -s trading_mvp\\tests -> 212 OK, 1 skipped.
- trading_edge_preflight.ps1 -Json -> READY_FOR_EDGE_PROOF_STEP, fail_count=0, warn_count=0.
- check_active_run_gate.ps1 -Json -> READY_FOR_POSTPROCESS, expected_outputs_complete=true.
- trading_strategy_acceptance_gate.ps1 -Json -> accepted=false, live_orders=false.

## Next
- Do not paper/live.
- Actual next research step remains explicit user-approved visible 6h WS collect, then guarded postprocess, then replay-validation PlanOnly with the same ExpectedManifestPath, then separate review before ConfirmedResearchRun.
