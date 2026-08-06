# Funding Watchlist Review

Дата: 2026-06-17  
Статус: read-only anti-cherry-picking review for funding/basis final-review.

## Purpose

`tools/funding_watchlist_review.ps1` compares a funding rank/postprocess result against the predeclared watchlist created before the long collect.

It answers one narrow question: did the result improve inside the predeclared watch markets, or would accepting it require cherry-picking a new market after the fact?

This review is not a trade signal and cannot accept a strategy by itself.

## Default Inputs

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_rank_24h_spotliq_relaxed15_20260615_202709.json
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json
```

## Default Outputs

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_watchlist_review_20260617.json
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_watchlist_review_20260617.csv
```

## Commands

Readable:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_watchlist_review.ps1
```

JSON:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_watchlist_review.ps1 -Json
```

Shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_FUNDING_WATCHLIST_REVIEW.cmd
```

## Decision Meaning

- `NO_CURRENT_COST_EDGE_IN_WATCHLIST_OR_RANK`: no current-cost eligible markets; do not paper-forward.
- `WATCHLIST_HAS_ELIGIBLE_MARKETS_BUT_RESEARCH_NOT_ACCEPTED`: rank has candidates, but full gates still reject.
- `OFF_WATCHLIST_ONLY_REQUIRES_CHERRY_PICK_REVIEW`: only new/off-watchlist markets passed; treat as a new hypothesis requiring independent data.
- `ACCEPTANCE_CONFLICT_NO_WATCHLIST_SUPPORT`: final-review accepted but not inside watchlist; must be reviewed before any promotion.
- `WATCHLIST_SUPPORTED_ACCEPTANCE_REVIEW_REQUIRED`: predeclared markets support acceptance, but strategy still needs normal final decision and paper-forward gates.

## Integration

`tools/run_funding_final_review_visible.ps1` runs this review after successful `funding-final-review` and saves timestamped artifacts next to funding final-review outputs.

If `funding-final-review` creates a ready paper-forward plan while this review does not return `WATCHLIST_SUPPORTED_ACCEPTANCE_REVIEW_REQUIRED`, the wrapper must replace that paper plan with `blocked_by_watchlist_review` and preserve a `.pre_watchlist_review.json` backup. This prevents accepting post-hoc market selection as an edge.
