# Trading MVP Visible Long Data Plan

Дата: 2026-06-17

## Current State

- Active run gate: open for the completed 24h funding collect.
- Latest 24h funding dataset: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl`.
- Data quality: usable for diagnostics; `7659` rows, `288/288` cycles, `30` markets, error rate about `9.7%`.
- Research result: rejected. No market cleared the economic gates after cost/risk assumptions.
- Intraday/order-book branch: not ready for more tuning because the available "6h" sample effectively covered about `1.35h`; current breakout/HFT-style signals are not proven out-of-sample.

## Decision

The next engineering step is not live trading and not another small grid search. The next step is a longer visible data collection phase:

1. `funding/basis carry`: 7d bridge collection, then 14-30d if the bridge is stable.
2. `perp/order-book microstructure`: pause until we approve and collect a dense multi-day WebSocket/perp dataset.

Funding remains a separate carry engine. Order-book data is useful for execution quality and fill/slippage estimation, not as a justification to bypass funding economics.

## Visible Run Rule

Any collector/backtest/grid/paper-forward that runs over time must be visible in a terminal or through a visible monitor. The prepared launcher is:

Preview without starting:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -PlanOnly
```

Shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_PREVIEW_7D_FUNDING.cmd
```

Start only after explicit user confirmation:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun
```

Shortcut with an extra `START7D` prompt:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_START_7D_FUNDING_CONFIRMED.cmd
```

This command is not auto-run by this plan. It will fail without `-ConfirmedLongRun`.

## Predeclared Watchlist Binding

The launcher binds the current research watchlist before preview/start:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json
```

Current watchlist summary:

- `primary_7d_watch`: `3` markets: `mexc:HYPE`, `mexc:PI`, `mexc:KAS`.
- `secondary_7d_watch`: `8` markets.
- `rank_eligible`: `0`.

This binding is only for research focus and later anti-cherry-picking review. It is not a trading signal, and it cannot accept a strategy.

## 7d Funding Collect Spec

- Exchanges: `mexc,gateio`.
- Duration: `7` days.
- Poll interval: `300` seconds.
- Cycles: `2016`.
- Max symbols: `300`.
- Max pairs per exchange: `15`.
- Notional quote: `100`.
- Spot/perp spread max for row diagnostics: `30 bps`.
- Max absolute basis: `500 bps`.
- Funding min rate for collection: `-1.0`, so negative funding rows are retained for flip/exit analysis.
- Strategy remains research-only: no API keys, no live orders, no margin execution.

Expected artifacts use a timestamped label:

- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_7d_spotliq_visible_<stamp>.jsonl`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_7d_spotliq_visible_<stamp>.manifest.json`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_collect_7d_spotliq_visible_<stamp>.out.log`
- `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\funding_collect_7d_spotliq_visible_<stamp>.err.log`

## Gate Behavior

When the visible collector starts, it writes:

- `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json`

The gate metadata includes the watchlist path, watchlist decision, watchlist summary and recommended markets, so postprocess can compare final results against the predeclared research focus.

During `RUNNING`, the only allowed work on this goal is short status/ETA checking. No new collectors, postprocess, grid-search, broad analysis, or code changes.

Status check:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1
```

## Postprocess After Final Manifest

Run only when:

- `manifest.final == true`.
- `manifest.completed_cycles >= manifest.cycles`.
- line count matches manifest rows.
- error rate and cycle coverage pass data-quality gates.

Required checks:

- `funding-postprocess`
- `funding-final-review`
- OOS split
- walk-forward
- stress scenarios
- cost sensitivity for maker/VIP-like assumptions, lower slippage, longer hold intervals, and different break-even horizons

## Acceptance Gates

Research can move to paper-forward only if all are true:

- positive net PnL after fees/slippage/spread/basis risk;
- positive expectancy;
- sufficient trade count, not one-off opportunities;
- market concentration controlled;
- exchange concentration controlled;
- OOS accepted;
- walk-forward accepted;
- stress accepted;
- no hidden live-trading dependency.

If these fail again, the correct conclusion is not to force live trading. The next action would be either a materially different signal family or a longer/cleaner data source.


