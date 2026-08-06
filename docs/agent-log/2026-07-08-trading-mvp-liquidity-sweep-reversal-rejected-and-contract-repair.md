# trading_mvp: liquidity_sweep_reversal rejected + contract repair

- Date: 2026-07-08T15:09:07+03:00
- Agent: Codex
- User request: proceed with recommendation after confirmed replay-validation NoGrid inconsistency.

## Plan
- Repair wrapper/run_mvp artifact contract without launching replay/grid/live/API.
- Preserve research-only boundary.
- Mark liquidity_sweep_reversal rejected based on existing event-validation evidence.

## Done
- Updated 	ools/run_ws_replay_validation_visible.ps1: each executed stage now requires an expected non-empty fresh output file before it can be recorded as completed.
- Updated 	rading_mvp/run_mvp.ps1: Python CLI calls now go through Invoke-TradingMvpCli, and non-zero Python exit codes propagate to the PowerShell process.
- Updated 	rading_mvp/tests/test_visible_ws_collect_wrapper.py: added regression guards for stage output checks and Python exit propagation.
- Updated docs/agent-log/active-run-gate.json: status set to READY_FOR_POSTPROCESS, branch decision set to LIQUIDITY_SWEEP_REVERSAL_REJECTED_SELECT_NEXT_BRANCH.

## Evidence
- Event-validation artifact: xports/trading-mvp/backtests/event_validation_ws_durable_72h_2exchange_pregap_confirmed_replay_nogrid_20260708_133407.json.
- Decision: REJECTED_VALIDATION_GATE.
- Rejection reasons: 
o_train_eligible_slice, 	rain_selected_rejected, oos_rejected, walk_forward_rejected, stress_rejected.
- Data slice behind the validation: 2-exchange clean slice from ws_durable_72h_20260704_000015, normalized market-filter output with replay_allowed=true.

## Verification
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: OK, 20 tests, skipped=8.
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_cli_ws_input_guard: OK, 5 tests.
- PowerShell parser check for changed scripts: OK.

## Risks / Limits
- No new replay run was launched after the repair; this was intentional to avoid burning limits on a rejected branch.
- The missing ws_replay artifact from the prior run remains missing by design; future runs will fail closed instead of producing ok=true summaries without outputs.
- This is research-only decision support, not investment advice and not permission for live orders/API keys/leverage/margin.

## Next Agent Step
- Do not continue tuning liquidity_sweep_reversal on this dataset.
- Select the next research branch with PlanOnly first. Preferred direction: slower structural edge (unding/basis carry) or a new non-HFT signal family with OOS/walk-forward/stress/economics gates.
