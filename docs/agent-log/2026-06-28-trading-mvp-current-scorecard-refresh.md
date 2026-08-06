# trading_mvp current scorecard refresh

- Date: 2026-06-28 15:26:58 +03:00
- Agent: Codex
- Request: continue active trading_mvp objective without starting unconfirmed long runs.
- Route: medium-risk control-plane/data-evidence fix via agent-workflow-router; no live orders, API keys, leverage, margin, or channel/P2P work.
- Gate before/after: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700; no new long run started.

## What changed
- Created current scorecard: exports/trading-mvp/analysis/anufriev_strategy_scorecard_current_20260628.csv.
- Created human summary: docs/analysis/2026-06-28-trading-mvp-strategy-scorecard-current.md.
- Updated default scorecard path in:
  - tools/trading_branch_selector.ps1
  - tools/trading_goal_status.ps1
  - tools/trading_strategy_acceptance_gate.ps1
- Fixed trading_goal_status.ps1 so funding summary uses scorecard funding evidence, not the current active WS gate rows.
- Updated regression tests in trading_mvp/tests/test_visible_ws_collect_wrapper.py.

## Evidence now reflected
- Spot maker liquidity sweep/reversal: rejected on fresh ws_confirmed_research_6h_20260628_103700 grid; 11 trades, win_rate=0.54545, net_pnl=0.029408, PF=1.565, failed min_trades and min_win_rate.
- Sweep/reclaim event quality: rejected; 43 sweeps, target_before_stop_rate=0.38235, false_sweep_rate=0.69767, validation accepted=false.
- Funding/basis carry: failed/blocked; 7d final review refused due data_quality:min_min_rows_per_cycle, 50583 rows, 2016/2016 cycles, relaxed rank_eligible=0.

## Verification
- Targeted tests: C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate -> 13 OK, 1 skipped.
- Full tests: C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp\tests -> 211 OK, 1 skipped.
- trading_edge_preflight.ps1 -Json -> ok=true, READY_FOR_EDGE_PROOF_STEP.
- trading_branch_selector.ps1 -Json -> scorecard path 20260628 and selected branch spot_maker_liquidity_sweep_reversal_event_quality.
- trading_goal_status.ps1 -Json -> funding_rows=50583, gate_rows=2745067, accepted_trading_strategies=0.
- trading_strategy_acceptance_gate.ps1 -Json -> accepted=false, stage=research_only_no_accepted_strategy.
- start_ws_collect_visible.ps1 -Hours 6 -PlanOnly -> would_start=false, selected_branch=spot_maker_liquidity_sweep_reversal_event_quality.

## Limits and next step
- git command is unavailable in this shell, so no git diff/status was produced.
- The objective is not complete: no accepted edge and no paper-forward.
- Next long step remains visible 6h WS collect only after explicit user approval with -ConfirmedLongRun.
