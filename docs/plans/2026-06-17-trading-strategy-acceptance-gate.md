# trading_mvp Strategy Acceptance Gate

Дата: 2026-06-17  
Статус: read-only acceptance contract для активной цели.

## Purpose

`tools/trading_strategy_acceptance_gate.ps1` формально отвечает на вопрос: есть ли сейчас стратегия, которую можно считать accepted research setup.

Это не collector, не backtest, не replay и не postprocess. Скрипт только читает текущие артефакты и проверяет, не подменяем ли мы edge высоким winrate на слабой/тонкой выборке.

## Command

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_strategy_acceptance_gate.ps1
```

JSON mode:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_strategy_acceptance_gate.ps1 -Json
```

Fail if no accepted strategy:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_strategy_acceptance_gate.ps1 -RequireAccepted
```

## Current Contract

A strategy is not accepted unless it clears:

- scorecard verdict not in rejected/failed/inconclusive/excluded/tooling/mandatory buckets;
- accepted final research artifact;
- data quality accepted;
- backtest acceptance accepted;
- OOS accepted;
- walk-forward accepted;
- stress accepted;
- funding watchlist review supports the same predeclared markets and does not flag off-watchlist cherry-picking;
- rank/trade count gate;
- win rate >= configured threshold;
- positive expectancy;
- positive net PnL after costs;
- profit factor >= configured threshold;
- drawdown within cap.

Default thresholds:

| Gate | Default |
|---|---:|
| `MinTrades` | `20` |
| `MinWinRate` | `0.60` |
| `MinExpectancyQuote` | `0.0` |
| `MinNetPnlQuote` | `0.0` |
| `MinProfitFactor` | `1.20` |
| `MaxDrawdownQuote` | `5.0` |

## Stage Semantics

| Stage | Meaning |
|---|---|
| `research_only_no_accepted_strategy` | No strategy can move to paper-forward/live |
| `research_accepted_paper_forward_required` | Research passed, but independent paper-forward is still required |
| `paper_forward_validated_live_still_blocked` | Paper-forward passed, but live still needs separate readiness review and explicit approval |

## Current Expected State

The current expected state is `research_only_no_accepted_strategy`.

This is correct because current local evidence shows:

- scorecard accepted trading strategies: `0`;
- funding 24h result: `rank_eligible=0`, `total_trades=0`, `research_accepted=false`;
- funding watchlist review: `NO_CURRENT_COST_EDGE_IN_WATCHLIST_OR_RANK`;
- paper-forward has not been accepted;
- live remains blocked.

If this changes, the gate must point to concrete accepted artifacts, not narrative confidence.
