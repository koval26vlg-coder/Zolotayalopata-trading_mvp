# trading_mvp skills/tooling selection and gate update

- Time: 2026-07-08 12:54:00 +03:00
- Agent: Codex
- User request: find top skills/MCP/apps for trading/crypto/backtesting/finance/bot development and install only what is actually worth installing.

## Actions
- Checked active run gate: no active long run; prior gate was stale and pointed to rejected one-exchange market-filter artifact.
- Used Skills CLI search for trading, crypto trading, backtesting, finance, quant trading, algorithmic trading, ccxt.
- Used MCP/tool discovery for documentation/security/GitHub capabilities.
- Installed only two skills:
  - ccxt-python from ccxt/ccxt@ccxt-python into C:\Users\koval\.agents\skills\ccxt-python.
  - acktest from marketcalls/vectorbt-backtesting-skills@backtest into C:\Users\koval\.agents\skills\backtest.
- Did not install signal/advisor/vendor live-trading skills because they add strategy-bias, API-key/live-order risk, or weak relevance.
- Updated docs/agent-log/active-run-gate.json to latest accepted artifact:
  - C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_postprocess_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.json
  - replay_allowed=true
  - accepted_markets=32
  - output_exchanges=2
  - output_rows=51278447
  - max_gap_sec=215.2226049900055

## Current gate
- READY_FOR_REPLAY_VALIDATION_PLANONLY.
- Next goal step: visible replay-validation PlanOnly only.
- Still blocked: live orders, API keys, leverage/margin, grid/live/paper-forward until separate gates pass.

## Risks
- ccxt-python skill includes live-order examples; agents must keep current research-only/no API keys/no live orders rule.
- acktest skill is VectorBT/OpenAlgo/India-market oriented; use as analytical template/reference only, not as replacement for event-driven L2 replay.
