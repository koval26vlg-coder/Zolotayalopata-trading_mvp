# Funding Candidate Watchlist

Дата: 2026-06-17  
Статус: read-only market selector for the next funding/basis proof step.

## Purpose

`tools/funding_candidate_watchlist.ps1` converts the latest 24h funding rank artifact into a research watchlist for the next visible 7d collect.

This is not a trade signal. It does not override the current verdict: accepted trading strategies remain `0`, and current-cost funding/basis economics are not accepted.

## Inputs

Default input:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_rank_24h_spotliq_relaxed15_20260615_202709.json
```

## Outputs

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.csv
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json
```

## Commands

Readable:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_candidate_watchlist.ps1
```

JSON:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_candidate_watchlist.ps1 -Json
```

Shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_FUNDING_WATCHLIST.cmd
```

## Priority Meaning

- `primary_7d_watch`: useful focus market for longer collection if funding stays positive and execution quality is acceptable.
- `secondary_7d_watch`: useful but has weaker liquidity, spread, or basis stability.
- `diagnostic_coverage`: keep for coverage and failure analysis, not for candidate acceptance.
- `drop_from_primary_watchlist`: do not let it drive strategy conclusions unless conditions materially change.

## Hard Rule

The watchlist cannot accept a strategy. Acceptance still requires rank/backtest/OOS/walk-forward/stress under the current cost model, then paper-forward gates.
