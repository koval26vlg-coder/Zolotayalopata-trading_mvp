# Funding Viability Gap Checker

Дата: 2026-06-17  
Статус: read-only diagnostic для funding/basis branch.

## Purpose

`tools/funding_viability_gap.ps1` отвечает на практический вопрос:

> Что именно должно улучшиться, чтобы funding/basis carry стал жизнеспособным setup, а не просто дал высокий winrate на слабой экономике?

Скрипт читает текущие локальные артефакты:

- `funding_rank_24h_spotliq_relaxed15_20260615_202709.json`;
- `funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json`;
- `funding_economic_thresholds_20260617.csv`.

Он не запускает сбор данных, backtest, postprocess, API calls или live orders.

## Commands

Readable:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_viability_gap.ps1
```

JSON:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_viability_gap.ps1 -Json
```

Shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_FUNDING_GAP.cmd
```

## Current Expected Decision

```text
NOT_VIABLE_CURRENT_COST_MODEL
```

Reason:

- `rank_eligible=0`;
- `total_trades=0`;
- current taker-like one-interval cost requires about `39 bps`;
- observed p99 funding was about `10.15 bps`;
- top blockers are expected edge, risk-adjusted edge, break-even horizon and liquidity/volume.

## How To Use

Use this before approving a longer data run or changing the carry model. It should answer whether the next valid move is:

- longer visible data collection;
- lower-cost maker/VIP sensitivity, only if operationally real;
- exchange/universe expansion;
- rejecting the funding branch for now.

It must not be used to relax acceptance gates or justify live trading.

Before treating lower-cost assumptions as evidence, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_cost_assumption_gate.ps1
```
