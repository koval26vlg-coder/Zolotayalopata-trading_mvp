# 2026-06-27 - Codex - trading_mvp next edge branch selector

## User Request

Continue the active `trading_mvp` goal after `Рой` L1/L2 blocked funding carry.

## Route

Engineering + agent-coordination route. Followed:

- Active Run Gate Rule;
- Visible Run Rule;
- Trading Edge Scope Rule;
- Trading Swarm Rule;
- research-only/no-live/no-API-keys/no-leverage constraints.

## State Checked

Active run gate:

- status: `READY_FOR_POSTPROCESS`
- run id: `funding_collect_7d_spotliq_visible_20260617_185732`
- cycles: `2016/2016`
- rows: `50583`
- errors: `657`
- final: `true`

Swarm workflow:

- workflow id: `2026-06-27-095557-165108-trading-mvp-7d-funding-checkpoint-review`
- L1 decision: `block`
- L2 decision: `block`
- current level after approval: `L3`
- current agent: `Codex`

## Decision

Funding carry remains blocked for paper-forward/live.

Because no `funding_account_fee_tiers_current.json` exists, there is no verified non-secret fee-tier evidence that could reopen funding economics.

Selected next research branch:

`spot_maker_liquidity_sweep_reversal_event_quality`

This is not an accepted strategy. It is selected only as the next proof branch because scorecard evidence marks it inconclusive rather than fully disproven, and it must be tested only on independent dense data with strict OOS/walk-forward/stress gates.

## Changes

Added:

- `tools/trading_branch_selector.ps1`
- `tools/start_ws_collect_visible.ps1`
- `docs/plans/2026-06-27-spot-maker-sweep-reversal-proof-plan.md`
- `exports/trading-mvp/analysis/spot_maker_sweep_reversal_next_branch_20260627.json`

Updated:

- `tools/trading_next_goal_step.ps1`
- `tools/trading_goal_status.ps1`

## Verification

Commands run, without starting any long collector/grid/backtest:

- `tools/check_active_run_gate.ps1 -Json`: `READY_FOR_POSTPROCESS`
- `tools/trading_edge_preflight.ps1 -Json`: `ok=true`, `fail_count=0`, `warn_count=0`
- `tools/trading_branch_selector.ps1 -Json`: `NEXT_BRANCH_SPOT_MAKER_LIQUIDITY_SWEEP_REVERSAL`
- `tools/trading_next_goal_step.ps1 -Json`: primary command is branch selector
- `tools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly`: `would_start=false`, requires `-ConfirmedLongRun`
- `spot_maker_sweep_reversal_next_branch_20260627.json`: valid JSON, accepted strategy remains `false`

## Current Next Step

Do not start a long run automatically.

Allowed short work:

- define event-quality/OOS gates for the selected branch;
- use `tools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly` to preview a future visible run;
- if the user explicitly approves, run `tools/start_ws_collect_visible.ps1 -Hours 6 -ConfirmedLongRun` in a visible terminal.

Blocked:

- live orders;
- API keys;
- leverage/margin;
- paper-forward;
- hidden/background collectors;
- tuning old thin samples;
- new channel/P2P/off-ramp content analysis.

