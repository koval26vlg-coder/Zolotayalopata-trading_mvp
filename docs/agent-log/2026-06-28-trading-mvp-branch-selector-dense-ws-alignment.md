# trading_mvp branch selector dense WS command alignment

- time: 2026-06-28 17:31:10 +03:00
- agent: Codex
- request: continue active trading_mvp edge-proof goal without starting a long run
- gate before work: READY_FOR_POSTPROCESS; no active long run
- issue found: tools/trading_branch_selector.ps1 still exposed stale visible_ws_collect_plan / visible_ws_collect_after_approval commands with -Hours 6 while next-goal/preflight/shortcuts use 72h dense WS collect
- changes:
  - tools/trading_branch_selector.ps1 now resolves WS collect commands from the latest PlanOnly preview artifact and exposes command_resolution, shortcuts, and plan preview path
  - tools/trading_edge_preflight.ps1 wording no longer says confirmed 6h collect; it says long WS collect / PlanOnly command from next-goal
  - trading_mvp/tests/test_visible_ws_collect_wrapper.py asserts branch selector emits source=latest_plan_preview, Hours=72, dense universe, and no stale -Hours 6 -ConfirmedLongRun
- verification:
  - trading_branch_selector.ps1 -Json: visible_ws_collect_command_resolution.source=latest_plan_preview; effective_hours=72
  - targeted tests: 17 OK, 1 skipped
  - full tests: 215 OK, 1 skipped
  - trading_edge_preflight.ps1 -Json: READY_FOR_EDGE_PROOF_STEP, fail=0, warn=0
  - check_active_run_gate.ps1 -Json: READY_FOR_POSTPROCESS
- no long collector/backtest/replay/grid started; actual 72h collect still requires explicit user approval and visible terminal/monitor
