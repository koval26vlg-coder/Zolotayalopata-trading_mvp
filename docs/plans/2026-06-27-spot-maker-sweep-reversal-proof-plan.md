# Spot Maker Liquidity Sweep/Reversal Proof Plan

Date: 2026-06-27

## Decision

Next research branch: `spot_maker_liquidity_sweep_reversal_event_quality`.

This is not an accepted strategy and not a paper-forward candidate. It is the least-refuted remaining branch after `funding/basis carry` was blocked by 7d evidence and `Рой` L1/L2 review.

## Why This Branch

Current scorecard state:

- `funding_basis_carry`: blocked for paper-forward. Primary blocker is economics; relaxed 7d diagnostics still have `rank_eligible=0`.
- `large_move_breakout`: rejected because in-sample edge did not survive holdout on thin data.
- `flow_continue` / `fade_exhaustion`: rejected on current samples.
- `liquidity_sweep_reversal_v2`: rejected on the old thin sample after execution replay.
- `spot_maker_liquidity_sweep/reversal`: inconclusive, not accepted; tiny positive slice had only 2 trades.
- `sweep/reclaim event-quality layer`: diagnostic only; enough events exist, but execution edge is not proven.

Therefore the next useful work is not to tune old samples. The branch can only move forward through a new proof pipeline with independent dense data, predefined gates and execution-aware maker simulation.

## Immediate Engineering Scope

Allowed now:

- Build a visible WS/perp collection plan, not the long collect itself.
- Define event-quality and OOS/walk-forward gates before new data is collected.
- Add branch selector/status tooling so future agents do not return to funding collection by default.
- Prepare a visible collector wrapper if the user later approves a dense multi-day run.

Blocked now:

- No live orders.
- No API keys.
- No leverage or margin.
- No paper-forward.
- No hidden/background long run.
- No tuning on the same thin 6h/1.35h samples.
- No new channel/video/P2P/off-ramp analysis.

## Required Data Before Replay

A future long run, only after explicit approval, must be visible and must produce:

- final manifest with `final=true`;
- dense Level 2 / trade-flow data;
- enough independent time coverage for train/OOS/walk-forward;
- per-market coverage metrics;
- collection error and stale-write diagnostics;
- market-quality metrics: spread, quote updates, trade count, notional, top-of-book depth;
- no active-run gate bypass.

## Acceptance Gates

Research acceptance requires all of:

- `tools/sweep_reversal_acceptance_gate.ps1` returns `accepted=true`;
- `min_trades >= 20` per accepted config;
- `win_rate >= 0.60`;
- `expectancy_quote > 0`;
- `net_pnl_after_costs > 0`;
- `profit_factor >= 1.20`;
- `max_drawdown_quote <= 5`;
- OOS accepted;
- walk-forward accepted;
- stress accepted;
- maker fill and adverse-selection metrics accepted;
- no paper-forward until research acceptance is proven.

## Validation Update 2026-06-27

Implemented local `event-validation-report` for the sweep/reclaim layer:

- train/OOS split;
- train-only slice selection;
- OOS validation;
- walk-forward windows;
- stress gate with favorable haircut and adverse widening;
- machine-readable rejection reasons.

Current old dataset verdict:

- event-quality sample: `1018` sweeps;
- selected train slice: `mexc:H_USDT SHORT`;
- OOS selected events: `7`;
- OOS target-before-stop rate: `0.50`;
- walk-forward accepted windows: `0/4`;
- stress target-before-stop rate: `0.0`;
- branch gate: `accepted=false`.

Conclusion: current sweep/reversal branch remains research-only and rejected on the current dataset. Do not tune the same sample to force acceptance. The branch can only continue on independent dense data collected visibly after explicit user approval.

## Next Implementation Steps

1. Keep `tools/trading_branch_selector.ps1` as the current branch controller.
2. Use `tools/start_ws_collect_visible.ps1 -PlanOnly` to preview a future visible WS collect; use `-ConfirmedLongRun` only after explicit user approval.
3. Keep `event-validation-report` and `tools/sweep_reversal_acceptance_gate.ps1` as mandatory gates before any paper-forward discussion.
4. Run `tools/sweep_reversal_acceptance_gate.ps1` after any replay/grid artifact update; current old-sample artifacts must remain `accepted=false`.
5. Characterize collector/data-quality errors through `funding-collect-diagnostics` and keep those diagnostics separate from strategy acceptance.
6. Use `Рой` again after the branch plan/tooling is ready or before any approved long visible run.

## Current Verdict

`spot_maker_liquidity_sweep_reversal_event_quality` is selected as the next research branch, not as a strategy. It remains blocked from paper-forward/live until the proof gates pass on independent data.
