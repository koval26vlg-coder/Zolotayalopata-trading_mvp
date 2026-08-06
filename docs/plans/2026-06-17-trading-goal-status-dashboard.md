# Trading Goal Status Dashboard

Дата: 2026-06-17

## Purpose

`tools/trading_goal_status.ps1` is a read-only dashboard for the active `trading_mvp` edge-proof goal.

It does not start collectors, backtests, grids, paper-forward, API calls, live orders, or background jobs.

Current scope rule: channel intake is frozen. The dashboard must not direct work toward new YouTube/RSS/transcript analysis unless the user explicitly reopens that scope.

## Commands

Readable status:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_goal_status.ps1
```

JSON status:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_goal_status.ps1 -Json
```

Windows shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_GOAL_STATUS.cmd
```

For the single next-action decision, use:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_NEXT_STEP.cmd
```

For the 7d funding collect preview without starting:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_PREVIEW_7D_FUNDING.cmd
```

For the confirmed visible start after explicit approval:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_START_7D_FUNDING_CONFIRMED.cmd
```

## What It Shows

- active-run gate status;
- objective focus: prove trading edge / high-winrate scheme in `trading_mvp`;
- channel intake status and freeze rule;
- live process ids, if any;
- completed cycles and funding rows/errors from the gate;
- number of strategies in the scorecard;
- accepted/rejected/inconclusive strategy counts;
- current funding verdict;
- primary edge candidate and current status;
- funding break-even thresholds for the current cost model;
- master evidence index path;
- edge proof execution plan path;
- next-step controller command;
- strategy acceptance gate command;
- funding viability gap command;
- funding cost assumption gate command;
- funding candidate watchlist command;
- funding watchlist review command;
- visible collect preview command and shortcut;
- visible collect confirmed command and shortcut;
- visible 7d collect command;
- final-review command;
- next allowed action under the active-run gate.

## Use Rule

Run this before any next goal step. If it says gate is `RUNNING`, do not do anything except status/ETA checks.

If gate is open, the next work must still be edge-first: funding/basis proof, guarded postprocess, paper-forward gates, or code/gate quality work. Do not resume channel monitoring or transcript/source work unless explicitly requested.
