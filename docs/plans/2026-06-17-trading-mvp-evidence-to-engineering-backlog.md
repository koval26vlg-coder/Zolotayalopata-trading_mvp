# trading_mvp Evidence-To-Engineering Backlog

Дата: 2026-06-17  
Статус: рабочий backlog корректировок проекта на основе уже собранного канала, внешней проверки и текущих результатов `trading_mvp`. Research-only; не является инвестсоветом или разрешением live-торговли.

## 1. Decision Summary

Текущий проект нельзя честно позиционировать как готовый high-winrate trading bot. Правильная инженерная форма сейчас:

`existing evidence -> strategy edge proof -> visible long data collection if needed -> guarded final-review/OOS/walk-forward/stress -> paper-forward only if accepted -> live-readiness gate only after separate approval`

Новая scope correction: больше не берем новый контент с канала, не мониторим RSS, не продолжаем transcript retries и не расширяем YouTube-анализ. Канал остается только уже собранным источником гипотез. Главная задача теперь: найти и доказать рабочий trading edge/high-winrate схему в `trading_mvp`.

Главная техническая корректировка остается прежней: не выжимать win-rate из тонких intraday samples. Funding/basis остается основным структурным кандидатом, но текущая 24h экономика провалена. Intraday/perp микроструктура остается экспериментальной веткой и не должна снова тюниться на старых данных.

## 2. Machine-Readable Artifact

CSV: `exports/trading-mvp/analysis/trading_mvp_evidence_to_engineering_backlog_20260617.csv`

## 3. Backlog

| ID | Priority | Branch | Decision | Item | Implementation status | Next required action | Acceptance / block gate |
|---|---|---|---|---|---|---|---|
| P0-001 | P0 | governance | keep_enforced | Next-step controller, active run gate, edge preflight and visible-run rule | implemented | Before every goal step run trading_next_goal_step.ps1; long collectors/backtests/replays/grid/paper-forward only in visible terminal or visible monitor. | Controller must not return STATUS_ONLY, RESUME_OR_REJECT_INCOMPLETE_DATASET, FIX_PREFLIGHT, or MANUAL_REVIEW_REQUIRED before engineering/postprocess work; RUNNING allows only short status/ETA checks. |
| P0-002 | P0 | live-readiness | block | Live orders, API keys, leverage and margin execution | blocked_by_policy | Do not add live execution, exchange API keys, leverage or margin order placement to the current path. | Only after accepted research, accepted paper-forward, live-readiness checklist, venue risk cards and explicit user approval. |
| P0-003 | P0 | scope_control | freeze_channel_intake | Stop new channel content analysis; use existing evidence only | active_scope_rule | Do not fetch, retry, monitor, or analyze new YouTube/RSS/transcript content unless user explicitly reopens that work. | All next work must advance strategy edge proof, economics, backtesting, data collection, or implementation in trading_mvp. |
| P0-004 | P0 | governance | keep_enforced | Strategy acceptance gate | implemented_watchlist_bound | Before any claim that a setup is accepted or ready for paper-forward/live discussion, run trading_strategy_acceptance_gate.ps1. | No setup is accepted unless scorecard, final-review, data quality, backtest, OOS, walk-forward, stress, watchlist review, sample size, winrate, expectancy, net PnL, PF and drawdown gates pass. |
| P0-005 | P0 | funding_basis_carry | keep_enforced | Funding viability gap diagnostic | implemented | Use funding_viability_gap.ps1 before approving longer funding collection or changing cost/hold assumptions. | Any next funding step must explicitly address expected edge, risk-adjusted edge, break-even horizon, liquidity/volume and fee/hold gaps. |
| P0-006 | P0 | funding_basis_carry | keep_enforced | Funding cost assumption gate | implemented | Run funding_cost_assumption_gate.ps1 before using reduced-fee, maker/VIP or zero-cost sensitivity as evidence. | Only current_taker_like is acceptance evidence until a non-secret accepted account fee-tier artifact exists; zero-cost is never acceptance evidence. |
| P0-007 | P0 | funding_basis_carry | keep_enforced | Funding candidate watchlist | implemented | Run funding_candidate_watchlist.ps1 before interpreting the 7d funding/basis collect; use it as research focus, not a trade signal. | Watchlist cannot accept a strategy; acceptance still requires current-cost rank/backtest/OOS/walk-forward/stress and paper-forward gates. |
| P0-008 | P0 | funding_basis_carry | keep_enforced | Funding watchlist review | implemented | Run funding_watchlist_review.ps1 after final-review rank/postprocess artifacts; wrapper now does this automatically. | If only off-watchlist markets pass, treat as new hypothesis requiring independent data; watchlist review cannot accept a strategy without normal final-review gates. |
| P1-001 | P1 | funding_basis_carry | build_next_after_user_confirmation | Visible 7d funding/basis collection | launcher_prepared_not_started_watchlist_bound | Preview with TRADING_PREVIEW_7D_FUNDING.cmd; after explicit user confirmation run TRADING_START_7D_FUNDING_CONFIRMED.cmd or tools/start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun in visible terminal; launcher binds funding_candidate_watchlist_20260617.json into plan/start metadata. | Final manifest true; completed cycles around 2016; broad market coverage; negative funding observations retained; line count matches manifest; error/cycle coverage acceptable; final-review compares output against predeclared watchlist. |
| P1-002 | P1 | funding_basis_carry | run_after_collect | Guarded funding final review | wrapper_prepared_watchlist_review_and_paper_block_bound | After 7d manifest final=true, run tools/run_funding_final_review_visible.ps1; do not run before final manifest. | Postprocess, rank, gate report, regime report, frontier, sensitivity, OOS, walk-forward, stress, watchlist review, watchlist paper block, decision report and paper plan generated; research accepted only if all gates pass and watchlist review supports promotion. If watchlist review conflicts with a ready paper plan, wrapper must replace it with blocked_by_watchlist_review. |
| P1-003 | P1 | funding_basis_carry | keep_and_verify | Funding persistence, regime, sensitivity, OOS and walk-forward gates | implemented_cli_and_tests_present | Use existing strict-research gates on longer data; verify no lookahead and ensure entry decisions use only past/current rows. | Positive net PnL after costs; positive expectancy; sufficient trades; OOS pass; walk-forward pass; stress pass; not one-market/one-venue artifact. |
| P1-004 | P1 | funding_basis_carry | tighten_economics | Funding cost model and break-even thresholds | analysis_done_needs_account_specific_inputs_later | Continue using round-trip cost model; later replace assumed fees with actual account maker/taker tiers only during paper/live readiness. | Any candidate must clear fees, spread, slippage, basis risk and stress; current 39 bps one-interval round-trip threshold makes short-horizon carry unattractive. |
| P1-005 | P1 | research_process | make_mandatory | Experiment ledger and setup registry as acceptance interface | implemented | Every strategy hypothesis must have setup id, source participant/theme, dataset, config, metrics, result artifact and verdict before promotion. | No setup can move to paper-forward unless experiment_ledger and strategy acceptance gate show accepted final-review/OOS/walk-forward/stress evidence. |
| P2-001 | P2 | perp_microstructure | hold_until_new_dense_data | Dense independent multi-day perp/WS collection | not_started_current_sample_too_thin | Do not tune current signal family on old sample; if approved later, collect multi-day dense perp/WS data visibly and independently. | Enough hours/days, sufficient trades per market, clean final manifests, OOS/walk-forward, fill/adverse-selection metrics. |
| P2-002 | P2 | perp_microstructure | reject_as_current_alpha | flow_continue, fade_exhaustion, liquidity_sweep_reversal v2 and large_move_breakout as live/paper candidates | rejected_or_inconclusive_baselines | Keep as regression baselines only; do not optimize on same data; do not paper/live. | Only reconsider if a materially independent dataset and predefined gates produce accepted results. |
| P2-003 | P2 | event_quality | keep_diagnostic_only | Observable sweep/reclaim labels | implemented_diagnostic | Use as feature diagnostics only; do not label market-maker intent in code; measure false-sweep, target-before-stop and adverse excursion. | Eligible event slices must survive execution replay and OOS, not just in-sample event stats. |
| P2-004 | P2 | market_selection | build_later_if_microstructure_resumes | Market-quality and fill-probability filters for non-Binance illiquid markets | partially_implemented_in_replay_quality_filters | If intraday branch resumes, expand filters for trade-flow density, spread, quote update density, top-of-book notional and adverse selection before any signal gate. | Filtering must improve OOS net PnL/expectancy without collapsing to tiny trade count. |
| P2-005 | P2 | venue_risk | build_before_paper_live | Machine-readable venue risk cards | document_gate_exists_code_artifact_missing | Create venue risk card artifact for each exchange before paper-forward/live-like phase: jurisdiction, API reliability, withdrawal status, fee tier, custody cap, incident plan. | Every venue in a paper/live plan has a completed risk card; no single venue is existential. |
| P3-001 | P3 | channel_evidence | frozen_by_user_scope | Transcript/RSS/new channel content intake | paused_superseded_by_edge_focus | Do not collect or analyze new channel content. Existing channel evidence remains a hypothesis source only. | Only reopen if user explicitly asks to resume channel/source coverage; otherwise focus on trading_mvp edge proof. |
| P3-002 | P3 | automation_tooling | use_as_tooling_only | AI/reporting automation and monitoring summaries | partially_implemented_status_dashboard | Use AI/scripts for classification, status dashboards, report generation and experiment summaries; never for autonomous live trade decisions. | Automation outputs are read-only or research-only and cannot bypass deterministic replay gates. |

## 4. What To Stop Doing

- Do not analyze new YouTube/RSS/transcript content from the channel.
- Do not spend time on P2P/off-ramp, 115-ФЗ, custody/storage, criminal/legal withdrawal content for this trading-edge goal.
- Do not tune `flow_continue`, `fade_exhaustion`, `liquidity_sweep_reversal_v2` or `large_move_breakout` on the same thin samples.
- Do not chase headline win-rate without net PnL, expectancy, profit factor, drawdown, fees, slippage and sample size.
- Do not mix funding carry and HFT/order-book alpha into one signal score.
- Do not use AI as a live trade decision maker.
- Do not run hidden/background collectors unless explicitly approved.

## 5. What To Build Next

Main edge proof path remains funding/basis because it is the cleanest surviving structural candidate. If the user explicitly confirms a long visible run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun
```

During that run: only status/ETA checks.

After final manifest:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\run_funding_final_review_visible.ps1
```

If the 7d funding final-review fails again, the correct decision is one of:

1. extend to 14-30d only if data quality is good but sample is still sparse;
2. keep funding as watchlist-only if economics remain weak;
3. switch to a materially different signal family, not another small tweak.

## 6. Evidence Basis

| Evidence | Role |
|---|---|
| `docs/analysis/2026-06-17-anufriev-strategy-scorecard-current.md` | current verdicts by strategy family |
| `docs/analysis/2026-06-17-anufriev-participant-transfer-scorecard-current.md` | already-collected participant transfer/risk matrix; no new intake |
| `docs/analysis/2026-06-17-funding-economic-thresholds.md` | funding/basis break-even economics |
| `docs/plans/2026-06-17-trading-mvp-visible-long-data-plan.md` | visible 7d data collection spec |
| `docs/analysis/live-readiness-checklist.md` | live/paper readiness hard gate |
| `exports/trading-mvp/experiments/experiment_ledger.jsonl` | tested hypotheses and verdicts |
| `exports/trading-mvp/funding/funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json` | current funding branch economic failure |
| `exports/trading-mvp/backtests/perp_grid_search_6h_duration_20260614_181422.json` | current perp signal family rejected |
| `exports/trading-mvp/backtests/breakout_oos_test30_20260604.json` | breakout overfit/OOS failure |

## 7. Current Operational Answer

The most aligned next engineering step is not more channel analysis. It is strategy edge proof: either run the visible 7d funding/basis collection after explicit confirmation, or make only engineering changes that improve proof quality, gates, and postprocess. Until accepted evidence exists, the project remains research-only with live blocked.

