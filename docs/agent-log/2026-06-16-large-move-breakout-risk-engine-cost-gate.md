# 2026-06-16 Large-Move Breakout + Risk Engine + Cost Gate

## Request
1. Harden the risk engine (per-market limit + unrealized PnL in the kill-switch) and enable the cost gate in `config.json`.
2. Add a new `large_move_breakout` (maker / large-TP) signal and replay it against `flow_continue`.
3. Record the experiment in the ledger, log it, wire the new signal/cost-gate into the CLI, and run grid + OOS.

## Code Changes
- `trading_mvp/src/config.py`
  - `RiskConfig`: added `min_net_take_profit_bps` (default `-1e9` = off for back-compat) and `max_open_positions_per_market`.
  - `StrategyConfig`: added `breakout_lookback_sec`, `breakout_bps`, `breakout_min_samples`.
- `trading_mvp/src/ws_replay.py`
  - `ReplayRisk`: unrealized PnL tracked via `mark_unrealized` + `_check_equity_kill_switch`; new `can_open` reason `max_open_positions_per_market`.
  - Engine marks unrealized PnL on every event (`_unrealized_pnl_quote`); cost gate now uses the **strictest** of the replay flag and `risk.min_net_take_profit_bps` (CLI can tighten but not disable the config floor).
  - New signal `large_move_breakout` + `MarketState.recent_extremes` / `breakout_history`.
- `trading_mvp/src/trading.py`: legacy `RiskEngine` gained the same unrealized kill-switch; `Backtester.run` marks unrealized while a position is open.
- `trading_mvp/src/ws_grid_search.py`: optional breakout grid dimensions (`breakout_bps`, `breakout_lookback_sec`, `breakout_min_samples`), back-compatible defaults from the base strategy.
- `trading_mvp/src/cli.py`: `ws-replay` gained `--breakout-lookback-sec/--breakout-bps/--breakout-min-samples`; `ws-grid-search` gained `--grid-breakout-bps/-lookback-sec/-min-samples`.
- `trading_mvp/src/experiments.py`: registered the `large_move_breakout` setup.
- `trading_mvp/config.json` + `config.example.json`: cost gate enabled (`min_net_take_profit_bps: 1.0`, `max_open_positions_per_market: 1`).
- `trading_mvp/config.breakout.json`: dedicated breakout config.
- Tests: +4 (`tests/test_risk.py`, `tests/test_ws_replay.py`).

## Verification
- Full suite: `python -m unittest discover -s tests` → **191 tests OK**.
- CLI smoke: `ws-replay --signal-type large_move_breakout` (maker, 30m WS) runs end-to-end.

## Results (research-only, no live orders)
Dataset `ws_normalized_6h_20260604.jsonl` (actual span only ~1.35h), time-split train70 (0.94h) / test30 (0.42h), maker, fee 0, top_qty_fraction queue, per-market=1, max_open_positions=10.

- **flow_continue** maker 6h: 96 trades, 29% win, net -0.83, PF 0.44 (negative, consistent with prior rejection).
- **flow_continue** taker: **0 trades** — cost gate blocks fee-dominated entries (netTP -14 bps). Gate works as intended.
- **large_move_breakout** train-best `bps3/look30/tp30/sl15/flow500`: 8 trades, 75% win, PF 4.74, net +0.279 (in-sample).
- **OOS holdout (test30)** same config: 2 trades, 50% win, PF 0.97, net -0.002 → **not eligible** (`min_trades`, `min_profit_factor`).
- Taker breakout: 22 trades, 9% win, net -1.82 (dead on perp fees).

Artifacts:
- `exports/trading-mvp/backtests/breakout_grid_train70_20260604.json`
- `exports/trading-mvp/backtests/breakout_oos_test30_20260604.json`

## Verdict
Ledger record `exp_20260616_192719_722444cfea07`, setup `large_move_breakout`, verdict **rejected**.
Note: the request anticipated `inconclusive`, but the OOS run (also requested) showed the in-sample edge does not survive the holdout, so `rejected` is the faithful verdict. Trade counts stay far below `min_trades=20`; the dataset is thin (~1.35h).

## Next Steps
- Collect a **longer, independent** dense WS dataset (multi-hour/day) before any breakout retest — the current single short window cannot prove generalization.
- Optional: expose breakout params for `perp-replay`/`perp-grid-search` if perp WS density ever supports intrabar breakouts (perp REST snapshots are too sparse).
- Cost gate + per-market limit + unrealized kill-switch are now defaults; future grids will not silently run structurally-losing taker configs.
