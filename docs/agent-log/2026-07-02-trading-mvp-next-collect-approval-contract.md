# trading_mvp next collect approval contract

Date: 2026-07-02
Agent: Codex

## Context
- Previous visible WS collect/postprocess was rejected for replay/grid.
- Rejected artifact: `exports/trading-mvp/backtests/ws_postprocess_ws_collect_61h_sweep_20260701_211647.json`.
- Reasons: `min_duration_ratio`, `max_gap_sec`.

## Safe Planning Run
- Ran `start_ws_collect_visible.ps1 -Hours 72 -MaxPairsPerExchange 16 -UniversePath exports/trading-mvp/universe/no_binance_dense_ws_sweep_20260628.csv -PlanOnly`.
- Plan only; no new collect started.
- Plan output: `exports/trading-mvp/run/ws_collect_plan_preview_latest.json`.

## Readiness
- Ran `trading_ws_collect_readiness.ps1 -Json`.
- Result: `READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION`.
- Readiness artifact: `exports/trading-mvp/analysis/trading_ws_collect_readiness_current.json`.
- Research-only: true.
- Live orders/API keys/leverage/margin: false.
- Requires explicit user approval for actual collect: true.

## Approval Contract
- Initial contract failed because `active-run-gate.json` lacked the exact rejected-artifact approval fields.
- Updated gate with:
  - `replay_allowed=false`
  - `requires_explicit_user_approval_for_actual_collect=true`
  - `next_goal_decision=START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL`
  - guarded `command_after_explicit_approval`
  - readiness path and preview command
- Re-ran `trading_collect_approval_contract.ps1 -Json`.
- Result: `ok=true`, `status=APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT`, `fail_count=0`.

## Swarm
- Workflow remains pending L1: `2026-07-02-011649-606893-trading-mvp-ws-dataset-rejected-checkpoint`.
- `trading_swarm_status.ps1`: `SWARM_REVIEW_INCOMPLETE`, allowed next agent `Antigravity CLI`.

## Next Step
Do not start any long collect until explicit user approval. If user approves, use the guarded visible command from `active-run-gate.json` / readiness artifact. If user does not approve, wait for swarm or choose a different proof branch manually.
