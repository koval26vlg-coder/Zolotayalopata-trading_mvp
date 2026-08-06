# trading_mvp Edge Preflight

Дата: 2026-06-17  
Статус: read-only guard перед следующими шагами активной цели.

## Purpose

`tools/trading_edge_preflight.ps1` - быстрый операторский чек перед любым следующим шагом по `trading_mvp` edge-proof pipeline.

Он не запускает collector, replay, grid-search, backtest или postprocess. Он только проверяет, что:

- active-run gate не `RUNNING` и не `STOPPED_INCOMPLETE`;
- новый контент канала заморожен;
- цель сфокусирована на proof of edge/high-winrate strategy в `trading_mvp`;
- live/API/leverage остаются заблокированы;
- текущий 24h funding/basis результат честно зафиксирован как rejected/failed;
- visible 7d collector и guarded final-review wrappers существуют;
- funding candidate watchlist существует и привязан к visible 7d launcher metadata;
- следующий длинный прогон требует явного подтверждения пользователя.

## Command

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_edge_preflight.ps1
```

JSON mode:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_edge_preflight.ps1 -Json
```

## Decision Semantics

| Status | Meaning | Allowed work |
|---|---|---|
| `READY_FOR_EDGE_PROOF_STEP` | Gate open and project controls are aligned | Short edge-proof engineering; 7d visible collect only after explicit approval |
| `BLOCKED_RUNNING` | Long run is active | Status/ETA checks only |
| `BLOCKED_STOPPED_INCOMPLETE` | Dataset is incomplete | Visible resume or explicit rejection of incomplete dataset |
| `FAILED_PREFLIGHT` | A required control is missing/broken | Fix failed checks before continuing |

## Current Goal Rule

Do not resume YouTube/RSS/transcript/source-packet work. Existing channel work is only a hypothesis source. The active goal is to prove or reject a working, economically viable strategy in `trading_mvp`.

High win-rate alone is not accepted. A candidate needs positive expectancy, net PnL after costs, sufficient sample, OOS/walk-forward, stress, liquidity/fill realism and paper-forward before any live discussion.
