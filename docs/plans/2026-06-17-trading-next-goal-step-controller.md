# trading_mvp Next Goal Step Controller

Дата: 2026-06-17  
Статус: read-only controller для активной цели.

## Purpose

`tools/trading_next_goal_step.ps1` объединяет:

- active-run gate;
- edge preflight;
- strategy acceptance gate;
- goal status dashboard.

Он не запускает collectors, backtests, grids, paper-forward, API calls, live orders или background jobs. Его задача - дать одно решение: что делать следующим шагом и что сейчас заблокировано.

## Commands

Readable:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1
```

JSON:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1 -Json
```

Shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_NEXT_STEP.cmd
```

## Decision Values

| Decision | Meaning | Allowed next action |
|---|---|---|
| `STATUS_ONLY` | A long run is active | Status/ETA only |
| `RESUME_OR_REJECT_INCOMPLETE_DATASET` | Gate says data stopped incomplete | Visible resume or explicitly reject dataset |
| `FIX_PREFLIGHT` | Preflight failed | Fix controls before goal work |
| `AWAIT_USER_APPROVAL_FOR_VISIBLE_7D_COLLECT` | No accepted strategy; next proof step needs longer data | Wait for explicit approval or do short gate-quality work |
| `PAPER_FORWARD_REQUIRED` | Research accepted but paper-forward not accepted | Prepare visible paper-forward; no live |
| `LIVE_READINESS_REVIEW_REQUIRED` | Paper-forward passed | Separate live-readiness review; live still blocked |
| `MANUAL_REVIEW_REQUIRED` | Unexpected state | Inspect gate/preflight/acceptance manually |

## Current Expected Decision

Current expected decision:

```text
AWAIT_USER_APPROVAL_FOR_VISIBLE_7D_COLLECT
```

Reason:

- no accepted strategy exists;
- channel intake is frozen;
- 24h funding/basis branch is rejected economically;
- funding candidate watchlist is available as read-only research focus, not as acceptance evidence;
- live and paper-forward are blocked;
- visible 7d funding/basis collect requires explicit user approval.

Safe preview shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_PREVIEW_7D_FUNDING.cmd
```

Watchlist shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_FUNDING_WATCHLIST.cmd
```

Watchlist review shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_FUNDING_WATCHLIST_REVIEW.cmd
```

Start shortcut, only after explicit approval, with an extra `START7D` prompt:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_START_7D_FUNDING_CONFIRMED.cmd
```
