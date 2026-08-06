# Codex Agent Log: trading_mvp listing-event replay PlanOnly

Date: 2026-07-09
Agent: Codex
User request: Confirmed visible listing-event OHLCV history collect and continued guarded research pipeline.

## Plan
- Respect active-run gate and visible-run rules.
- Use completed listing-event OHLCV history artifact only.
- Implement read-only listing_event_drift_reversal replay PlanOnly.
- Keep grid, live orders, API keys, leverage/margin and paper-forward blocked.
- Update gate-aware next-step scripts so a rejected replay does not route back to old scaffolding.

## Completed
- Verified active-run gate was READY_FOR_POSTPROCESS.
- Added listing-event history normalizer path support before this replay step.
- Added `trading_mvp/src/listing_event_replay.py`.
- Added `tools/trading_listing_event_replay_planonly.ps1`.
- Added unit tests in `trading_mvp/tests/test_listing_event_replay.py`.
- Ran read-only replay PlanOnly and updated active-run gate.
- Updated `tools/trading_next_goal_step.ps1`, `tools/trading_goal_status.ps1`, and `tools/trading_branch_selector.ps1` to recognize replay rejected/candidate states.

## Replay Result
Artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\listing_event_replay_planonly_20260709_095909.json`
Decision: `LISTING_EVENT_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE`
Events: 36
Rows: 2554
Executed trades: 21
Win rate: 42.86%
Net PnL quote, notional 100 per trade: -76.80453409356448
Expectancy quote: -3.6573587663602134
Profit factor: 0.5933393975323866
OOS trades: 7
OOS expectancy quote: 3.0680758575314386
Stress expectancy quote: -4.357358766360213
Walk-forward accepted ratio: 0.5, threshold 0.6
Rejection reasons: net_expectancy_not_positive, profit_factor_below_threshold, walk_forward_rejected, stress_net_expectancy_not_positive

## Checks
- `python -m unittest trading_mvp.tests.test_listing_event_replay trading_mvp.tests.test_listing_event_normalizer trading_mvp.tests.test_listing_event_history_quality`: 12 OK.
- `trading_next_goal_step.ps1 -Json`: decision now `LISTING_EVENT_REPLAY_PLANONLY_REJECTED_SELECT_NEXT_BRANCH`.
- `trading_goal_status.ps1 -Json`: primary_edge_status now `listing_event_replay_rejected_select_next_branch`.
- `trading_branch_selector.ps1 -Json`: selected_branch now `next_non_hft_structural_branch`.
- Full `unittest discover` was attempted but timed out at ~180s; no stuck unittest python remained. Existing Python processes were Aion/SML adapters.
- `git diff --stat` could not run because `git` was not in PATH in this shell.

## Risk/Limitations
- This was a fixed-config PlanOnly replay, not optimization/grid.
- Current evidence rejects this setup; do not retune on the same sample to manufacture win rate.
- OOS slice alone was positive, but train/full/stress/walk-forward fail; no strategy accepted.
- Visible history collect window PID 29668 may still be open waiting for Enter, but child collector is finished.

## Next Valid Step
Run new non-HFT structural branch PlanOnly or design a larger independent listing-event sample. Do not start collect/grid/replay/live/API/paper-forward until a gate explicitly allows it.

Command for next controller:
`pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1 -Json`
