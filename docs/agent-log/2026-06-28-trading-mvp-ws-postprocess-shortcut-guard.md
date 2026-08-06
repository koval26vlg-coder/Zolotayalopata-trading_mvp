# Trading MVP visible WS postprocess shortcut guard

- time: 2026-06-28 16:05:35 +03:00
- agent: Codex
- user_request: продолжи цель
- goal: prove or reject a high-winrate trading edge with data gates; no live orders/API keys/leverage/margin.

## Context
- Active run gate was checked before work: READY_FOR_POSTPROCESS for ws_confirmed_research_6h_20260628_103700.
- Current 6h WS dataset is complete and postprocessed; strategy acceptance remains false.
- Long-run collection was not started.

## Changes
- Added preflight check visible_ws_postprocess_shortcut_alignment in tools/trading_edge_preflight.ps1.
- The check verifies TRADING_WS_POSTPROCESS_FROM_GATE.cmd routes through tools/run_ws_postprocess_visible.ps1 and does not bypass with direct run_mvp.ps1/ws-postprocess.
- Exposed ws_postprocess_shortcut_command in preflight JSON.
- Updated trading_mvp/tests/test_visible_ws_collect_wrapper.py to require the new check and shortcut command.

## Evidence Reviewed
- ws_collect_20260628_000346.json: total_events=2745067, MEXC/Gate, errors=0.
- ws_data_quality_ws_collect_20260628_000346_postprocess_20260628_100805.json: accepted=true, rows=2744439, span_hours=5.99997, parse_error_rate=0.
- sweep_reversal_acceptance_ws_confirmed_research_6h_20260628_103700_gatefixed.json: accepted=false, fail_count=15.
- ws_grid_search_ws_confirmed_research_6h_20260628_103700.json: eligible_combinations=0; best LSR had 11 trades, win_rate=0.54545, net_pnl_quote=0.0294, PF=1.565 but failed min_trades/min_win_rate.

## Verification
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper trading_mvp.tests.test_active_run_gate: 13 OK, 1 skipped.
- pwsh tools/trading_edge_preflight.ps1 -Json: ok=true, READY_FOR_EDGE_PROOF_STEP, visible_ws_postprocess_shortcut_alignment=pass.
- python -m unittest discover -s trading_mvp\\tests: 211 OK, 1 skipped.
- check_active_run_gate.ps1 -Json: READY_FOR_POSTPROCESS, expected_outputs_complete=true.
- trading_strategy_acceptance_gate.ps1 -Json: accepted=false, live_orders=false.

## Next
- Do not paper/live.
- Next allowed step is only a visible dense WS collect plan or another short proof-quality engineering step.
- Any actual 6h collect still requires explicit user confirmation and visible terminal/monitor.
