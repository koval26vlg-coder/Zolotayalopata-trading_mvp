# trading_mvp preflight WS path alignment

- Time: 2026-06-27 13:38:15 +03:00
- Agent: Codex
- Goal: continue trading_mvp edge proof without starting long runs.
- Gate status before work: READY_FOR_POSTPROCESS, but funding postprocess blocked by guard review (min_rows_per_cycle=9); no funding rank/backtest/paper-forward.

Problem:
- 	ools/trading_edge_preflight.ps1 was clean, but its output still pointed operators toward 7d funding collect hints while the current next proof branch is guarded visible 6h WS collect planning.

What changed:
- Updated 	ools/trading_edge_preflight.ps1 so 
ext_allowed_action now names the guarded visible 6h WS collect planning branch.
- Added explicit output fields:
  - isible_ws_collect_preview_command
  - isible_ws_collect_command
  - ws_postprocess_command
  - ws_replay_validation_plan_command
  - unding_visible_collect_command
- Kept legacy isible_collect_command, but when funding is blocked by swarm it now resolves to the WS confirmed command rather than funding collect.
- Updated 	rading_mvp/tests/test_visible_ws_collect_wrapper.py to lock the WS-path preflight wording and fields.

Verification:
- 	ools/trading_edge_preflight.ps1 -Json: READY_FOR_EDGE_PROOF_STEP, failures=0, warnings=0, next_allowed_action references guarded visible 6h WS collect planning.
- 	ools/trading_next_goal_step.ps1 -Json: decision remains SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT.
- 	ools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly: would_start=false, ConfirmedLongRun required, zero-line/early-density/schema guards present, postprocess/replay-validation commands present.
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: 2 OK via C:\Program Files\Python313\python.exe.
- python -m unittest discover -s trading_mvp/tests: 202 OK via C:\Program Files\Python313\python.exe.

Next:
- Actual 6h WS collect remains blocked until explicit user confirmation and visible terminal/monitor run with -ConfirmedLongRun.
- After collect: guarded WS postprocess, then replay validation PlanOnly with the same ExpectedManifestPath, then separate decision on ConfirmedResearchRun.
