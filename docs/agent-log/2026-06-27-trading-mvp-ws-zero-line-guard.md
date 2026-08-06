# trading_mvp WS zero-line guard

- Time: 2026-06-27 13:33:40 +03:00
- Agent: Codex
- Goal: continue trading_mvp edge proof without starting long runs.
- Gate status before work: READY_FOR_POSTPROCESS, but funding postprocess blocked by guard review (min_rows_per_cycle=9); no funding rank/backtest/paper-forward.

What changed:
- Added ZeroLineAbortAfterMinutes and DisableZeroLineAbort to 	ools/start_ws_collect_visible.ps1.
- PlanOnly and active-run gate metadata now expose zero_line_guard.
- Visible monitor stops child collector and marks STOPPED_INCOMPLETE with stop_reason=zero_line_guard_failed if no raw lines are written by the threshold.
- Updated 	ools/trading_edge_preflight.ps1 to require zero-line, early-density and schema guards.
- Updated 	rading_mvp/tests/test_visible_ws_collect_wrapper.py to cover the zero-line guard markers.

Verification:
- 	ools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly: would_start=false, zero_line_guard.enabled=true, bort_after_minutes=10.
- 	ools/trading_edge_preflight.ps1 -Json: READY_FOR_EDGE_PROOF_STEP, ail_count=0, warn_count=0.
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: 2 OK via C:\Program Files\Python313\python.exe.
- python -m unittest discover -s trading_mvp/tests: 202 OK via C:\Program Files\Python313\python.exe.
- 	ools/trading_next_goal_step.ps1 -Json: still SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT, with gate_postprocess_block preserved.

Next:
- Actual 6h WS collect remains blocked until explicit user confirmation and visible terminal/monitor run with -ConfirmedLongRun.
- After collect: guarded WS postprocess, then replay validation PlanOnly with the same ExpectedManifestPath, then separate decision on ConfirmedResearchRun.
