# 2026-06-27 - Codex - trading_mvp goal resumed with swarm checkpoint

## User Request
Возобновить цель после 7d funding collect и добавить инструмент `Рой` в цель: использовать swarm для помощи, при лимитах агентов возвращаться к ручному управлению Codex, после восстановления лимитов снова подключать swarm.

## Goal State
Codex goal recreated as active:
`trading_mvp: найти, доказать или честно отбросить рабочую высоко-винрейтную trading strategy/edge для non-Binance markets через данные, backtest, OOS, walk-forward, stress, economics и paper-forward gates; использовать Рой для независимых проверок и handoff, а при лимитах агентов возвращаться к ручному управлению Codex до восстановления лимитов.`

## Active Run Gate
Checked `tools/check_active_run_gate.ps1`.

Status: `READY_FOR_POSTPROCESS`
Run id: `funding_collect_7d_spotliq_visible_20260617_185732`
Cycles: `2016/2016`
Rows: `50583`
Errors: `657`
Final: `true`

## Artifacts Checked
Strict final-review:
`exports/trading-mvp/funding/funding_final_review_funding_collect_7d_spotliq_visible_20260617_185732_final_review_20260627_094801.json`

Strict result: `not_ready_for_postprocess` because data quality failed on `min_min_rows_per_cycle`.
Actual `min_rows_per_cycle=9`; strict threshold is `20`.

Diagnostic relaxed rank:
`exports/trading-mvp/funding/funding_rank_funding_collect_7d_spotliq_visible_20260617_185732_relaxed_quality_diag_20260627_095113.json`

Diagnostic result: `rank_eligible=0`; top markets fail expected edge, risk-adjusted edge, break-even horizon and/or spot-top liquidity.

## Project Rule Updates
Updated `AGENTS.md` with Trading Swarm Rule.
Updated `docs/plans/2026-06-15-trading-mvp-research-goal.md` with 2026-06-27 checkpoint and Swarm usage rule.

## Swarm Workflow
Created Aion swarm workflow:
`2026-06-27-095557-165108-trading-mvp-7d-funding-checkpoint-review`

Purpose: independent checkpoint review of 7d funding result, strict quality blocker vs economic rejection, and next branch recommendation.

If swarm agents are limited/unavailable, mark `swarm_limited` and continue under Codex control. Reconnect swarm at the next meaningful checkpoint.

## Swarm L1 Result
Retried `Рой` through the correct isolated Antigravity workflow path:

`D:\AionUi-Paperclip\.venv-sml\Scripts\python.exe D:\AionUi-Paperclip\tools\antigravity_workflow_review.py --root D:\AionUi-Paperclip\docs\agent-workflows 2026-06-27-095557-165108-trading-mvp-7d-funding-checkpoint-review ...`

Antigravity response was recovered from local conversation DB and submitted through:

`D:\AionUi-Paperclip\.venv-sml\Scripts\python.exe D:\AionUi-Paperclip\tools\agent_workflow.py --root D:\AionUi-Paperclip\docs\agent-workflows submit-work ...`

Workflow state: `waiting_for_approval`; `last_handoff=levels/L1/handoff.md`.

L1 decision: `block`.

L1 conclusion:
- funding carry is not suitable for paper-forward now;
- strict `min_rows_per_cycle=9` vs threshold `20` is secondary;
- primary blocker is economics: relaxed diagnostics still have `rank_eligible=0`;
- fixing collector coverage alone risks wasting time unless real maker/fee-tier economics changes the cost model.

## Swarm L2 Result
Continued the same workflow to L2 after accepting the L1 handoff as a checkpoint result.

L2 handoff:
`D:\AionUi-Paperclip\docs\agent-workflows\2026-06-27-095557-165108-trading-mvp-7d-funding-checkpoint-review\levels\L2\handoff.md`

Workflow state after submit: `waiting_for_approval`; `last_handoff=levels/L2/handoff.md`; `allowed_next_agents=["Codex"]`.

L2 decision: `block`.

L2 conclusion:
- L1 block is confirmed;
- funding carry is not ready for paper-forward;
- collector coverage is still secondary to economics;
- do not run another funding collect first;
- next valid path is verified non-secret fee-tier evidence or selecting a different edge family.

## Failed Diagnostic Attempt
A direct `funding-sensitivity` command was attempted on the 7d dataset and ran for about 4.5 minutes, then exited with code `1073807364` without stdout and without creating `exports/trading-mvp/backtests/funding_sensitivity_7d_spotliq_diag_20260627.json`.

Do not repeat long or potentially long diagnostics as blind shell runs. Use a visible/progress wrapper or a bounded deterministic artifact-only script.

## Fee/Economics Gate Follow-up
Ran `tools/funding_cost_assumption_gate.ps1 -Json` and saved:

`exports/trading-mvp/analysis/funding_cost_assumption_gate_20260627.json`

Decision remains `USE_CURRENT_COST_ONLY_FOR_ACCEPTANCE` because `exports/trading-mvp/analysis/funding_account_fee_tiers_current.json` is absent.

Saved diagnostic public fee notes:

`exports/trading-mvp/analysis/funding_public_fee_observations_20260627.json`

Public MEXC pages suggest lower fees than the conservative current model, but this is not accepted strategy evidence. Gate public rates are account/VIP-dependent. Lower-cost maker/VIP scenarios remain `hypothesis_only` until non-secret account/trading-page or trade-history fee evidence is provided.

Created non-secret fee evidence template:

`exports/trading-mvp/analysis/funding_account_fee_tiers_template.json`

This is intentionally not named `funding_account_fee_tiers_current.json`, so the cost gate still treats fee-tier evidence as missing until verified values are explicitly provided.

## Current Verdict
No accepted strategy. Funding carry is blocked for paper-forward by both Codex evidence and `Рой` L1 review. Live orders, API keys, leverage and margin remain blocked.

## Next Step
Do not continue funding carry by collecting more data first. Next valid step is one of:

1. Validate actual non-secret maker/taker fee-tier assumptions for MEXC/Gate and map them to the model.
2. If fee evidence cannot materially change expected edge, deprioritize funding carry.
3. Move to another edge family with the same proof pipeline: data, replay/backtest, OOS/walk-forward, stress, economics, paper-forward gate.
