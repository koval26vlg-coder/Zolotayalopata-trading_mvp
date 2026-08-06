# trading_mvp WS 61h postprocess rejected

Date: 2026-07-02
Agent: Codex

## Run
- Run id: `ws_collect_61.27h_sweep_visible_20260701_080528`
- Manifest: `exports/trading-mvp/raw/ws_collect_20260701_211647.json`
- Stale visible `pwsh -NoExit` was left open after collector completed; gate was repaired to `READY_FOR_POSTPROCESS` with stop reason `collector_completed_noexit_terminal_left_open`.

## Postprocess
- Postprocess artifact: `exports/trading-mvp/backtests/ws_postprocess_ws_collect_61h_sweep_20260701_211647.json`
- Data-quality artifact: `exports/trading-mvp/backtests/ws_data_quality_ws_collect_61h_sweep_20260701_211647.json`
- Normalized artifact: `exports/trading-mvp/normalized/ws_normalized_ws_collect_61h_sweep_20260701_211647.jsonl`
- Normalized rows: `11,493,374`
- Decode/parse errors: `0`
- Event kinds: `bbo=9,402,100`, `depth=1,971,341`, `trade=119,933`
- Exchanges: `mexc=11,263,147`, `gateio=230,227`

## Decision
- `replay_allowed=false`
- `data_quality.accepted=false`
- Reasons: `min_duration_ratio`, `max_gap_sec`
- Duration ratio: `0.2638` vs required `0.8`
- Span: `16.1608h` vs requested manifest duration `61.27h`
- Max gap: `523.34s` vs allowed `300s`
- Markets with gap over limit: `16`
- Manifest error count: `9`

## Rules
- Do not run ws-replay/ws-grid-search on this dataset.
- Do not treat the dataset as proof of edge.
- No live orders, API keys, leverage, margin, paper-forward, or investment advice.

## Swarm
- Workflow: `2026-07-02-011649-606893-trading-mvp-ws-dataset-rejected-checkpoint`
- Next agent: `Antigravity CLI L1`
- Task: independently review rejection, safe partial analysis, and next proof-step.

## Next Step
Await swarm checkpoint or manually decide the next proof branch. Candidate directions: cleaner visible WS collect with fixed exchange stability, narrower MEXC-only research collect with explicit single-exchange criteria, or pivot back to perp/funding branch. Actual replay/grid remains blocked for this artifact.
