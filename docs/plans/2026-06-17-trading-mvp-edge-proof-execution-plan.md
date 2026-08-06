# trading_mvp Edge Proof Execution Plan

Дата: 2026-06-17  
Статус: active execution plan после user scope correction. Новый контент канала больше не анализируется; канал используется только как уже собранный источник гипотез.

## 1. Objective

Найти и доказать рабочий trading edge/high-winrate схему для `trading_mvp`, а не продолжать мониторинг канала.

Working definition of edge:

- positive net PnL after fees, spread, slippage, funding/basis risk and stress;
- positive expectancy;
- sufficient trade count;
- OOS and walk-forward pass;
- concentration controlled by market and exchange;
- paper-forward accepted before any live discussion.

High win-rate without positive expectancy and cost realism is not accepted.

## 2. Scope Freeze

Frozen until explicit user reversal:

- new YouTube/RSS monitoring;
- transcript retry;
- fresh channel/source packet work;
- P2P/off-ramp/115-ФЗ/custody/legal content analysis for this trading-edge goal.

Persistent/internal goal text may still contain the earlier channel-analysis objective. Treat that as stale context, not an instruction to resume channel work. The active source of truth is the latest user scope correction plus `AGENTS.md`: solve and implement the existing strategy proof pipeline.

## 3. Machine-Readable Artifact

CSV: `exports/trading-mvp/analysis/trading_mvp_edge_proof_execution_plan_20260617.csv`

## 4. Execution Steps

| Step | Priority | Phase | Action | Status | Acceptance |
|---|---|---|---|---|---|
| E0 | P0 | scope | Freeze channel intake | active | No new YouTube/RSS/transcript work unless user explicitly reopens it |
| E1 | P0 | governance | Check active-run gate before every step | active | RUNNING only allows status/ETA; READY allows next proof step |
| E2 | P0 | no_live | Keep live/API/leverage blocked | active | No live until accepted research + paper-forward + explicit approval |
| E3 | P1 | primary_edge_candidate | Prove or reject funding/basis carry on longer data | needs_user_confirmation_for_visible_run | final manifest, broad coverage, positive net PnL after costs, OOS, walk-forward, stress, sensitivity |
| E4 | P1 | postprocess | Run guarded final review after 7d dataset | blocked_until_7d_final_manifest | decision report either accepts paper-forward or rejects branch |
| E5 | P1 | acceptance | Promote only if edge survives strict gates | defined | positive net PnL, expectancy, trade count, OOS, walk-forward, stress, concentration control |
| E6 | P2 | secondary_edge_candidate | Hold perp/orderbook until new dense independent data | held | multi-day final manifests and OOS replay; no tuning old data |
| E7 | P2 | feature_layer | Keep sweep/reclaim labels diagnostic | held | Only use if new data and replay prove target-before-stop and net execution edge |
| E8 | P2 | paper_forward | If accepted, freeze config and run paper-forward | blocked_until_accepted_final_review | independent forward window, enough trades, positive after costs, no manual intervention |
| E9 | P3 | rejection_policy | If funding fails again, do not force live | defined | watchlist-only, 14-30d extension if justified, or new signal family |

## 5. Current Strategy Position

Rejected or not accepted:

- spot maker continuation;
- fade/exhaustion;
- current perp flow/fade/sweep family;
- liquidity sweep reversal v2 execution;
- large-move breakout on current thin sample;
- current 24h funding/basis cost model.

Primary proof candidate:

- funding/basis carry on longer visible data with strict final-review.

Secondary proof candidate:

- perp/orderbook microstructure only after new dense independent dataset, not on old thin sample.

## 6. Next Concrete Action

Before any next goal step:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1
```

Then, if needed:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_edge_preflight.ps1
```

Only if preflight is clear and the user explicitly approves the long visible run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun
```

If not approved, the correct work is limited to code/gate quality improvements that do not require new long runs and do not reopen channel intake.

Before claiming that a setup is accepted or ready for paper-forward/live discussion:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_strategy_acceptance_gate.ps1
```

## 7. Non-Negotiables

- No hidden/background long runs.
- No live orders.
- No API keys.
- No leverage/margin execution.
- No claims of profit or high win-rate until accepted evidence exists.
- No channel content expansion unless explicitly reopened.

