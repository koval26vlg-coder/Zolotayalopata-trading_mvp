# Anufriev / trading_mvp Master Evidence Index

Дата: 2026-06-17  
Статус: единая карта доказательств активной цели. Research-only; не является инвестсоветом, юридической консультацией или рекомендацией к live-торговле.

## 1. Current Decision

Текущая цель не завершена.

Причина: канал и внешние источники изучены на уровне strategy families и major claims, но ни одна торговая стратегия в `trading_mvp` пока не прошла строгие gates: positive net PnL after costs, sufficient trades, OOS, walk-forward, stress, paper-forward.

Текущий разрешенный следующий proof step:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1
```

Preflight:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_edge_preflight.ps1
```

Если preflight разрешает следующий edge-proof шаг и пользователь явно подтверждает длинный видимый сбор:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun
```

После final manifest:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\run_funding_final_review_visible.ps1
```

Перед любым переходом к paper-forward/live-like discussion:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_strategy_acceptance_gate.ps1
```

## 2. One-Line Strategy Verdicts

| Branch | Current verdict | Evidence |
|---|---|---|
| Spot maker flow/imbalance | Rejected | negative EV in maker replay |
| Fade/exhaustion | Rejected | more activity, worse net EV |
| Perp flow/fade/sweep current family | Rejected current signal family | clean 6h duration-bound perp grid: `0` eligible |
| Liquidity sweep labels | Diagnostic only | many events, weak target-before-stop/selectivity |
| Liquidity sweep replay v2 | Rejected | maker win rate `10%`, net PnL negative |
| Large-move breakout | Rejected as overfit/thin sample | train positive, OOS failed |
| Funding/basis current cost model | Failed | `rank_eligible=0`, `total_trades=0` on 24h collect |
| P2P/off-ramp | Excluded from trading bot | legal/operational/custody risk, not alpha |
| AI trading | Tooling only | no deterministic replay proof of alpha |
| Risk/playbook/live-readiness | Mandatory | gates, checklist, no live before proof |

## 3. Primary Local Evidence

| Evidence group | Artifact | What it proves |
|---|---|---|
| Channel full catalog | `exports/youtube-anufriev/anufriev_video_catalog_20260606.csv` | Full map: `461` videos |
| Trading-relevant catalog | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv` | `287` trading/crypto/investing-relevant videos |
| Coverage summary | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_summary_20260606.json` | cluster counts, views, transcript/metadata split |
| Transcript union | `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json` | `77` transcript-backed unique videos |
| Transcript retry priority | `exports/youtube-anufriev/anufriev_transcript_retry_priority_current_20260617.csv` | ranked list of `210` metadata-only trading-relevant videos plus `2` latest RSS delta Shorts for future source checks |
| P0 transcript retry queue | `exports/youtube-anufriev/anufriev_transcript_retry_queue_p0_current_20260617.csv` | foreground-ready retry queue for the top `4` P0 videos already present in local metadata |
| Latest RSS metadata-needed queue | `exports/youtube-anufriev/anufriev_latest_rss_caption_metadata_needed_p0_20260617.csv` | `2` latest RSS Shorts requiring fresh metadata/caption extraction before transcript retry |
| Latest RSS | `exports/youtube-anufriev/anufriev_youtube_rss_latest_20260617.csv` | `15` latest entries as of 2026-06-17 snapshot |
| Latest RSS refresh | `exports/youtube-anufriev/anufriev_youtube_rss_refresh_delta_20260617_164026.csv` | `2` additional new Shorts at 15:00/16:00 |
| Latest two source packet | `docs/analysis/2026-06-17-anufriev-latest-two-source-packet.md` | new Shorts are metadata-only; caption tracks found but transcript extraction returned empty/429 |
| Current strategy scorecard | `exports/trading-mvp/analysis/anufriev_strategy_scorecard_current_20260617.csv` | machine-readable strategy comparison with verdicts, metrics, economics and provenance |
| Participant transfer scorecard | `exports/trading-mvp/analysis/anufriev_participant_transfer_scorecard_current_20260617.csv` | machine-readable participant-to-project transfer matrix: what can be used, what is blocked, and why |
| Evidence-to-engineering backlog | `exports/trading-mvp/analysis/trading_mvp_evidence_to_engineering_backlog_20260617.csv` | prioritized engineering backlog linking evidence to build/hold/block/reject decisions |
| Edge proof execution plan | `exports/trading-mvp/analysis/trading_mvp_edge_proof_execution_plan_20260617.csv` | strategy-edge-first execution plan after channel intake freeze |
| Goal gap matrix | `exports/trading-mvp/analysis/anufriev_goal_gap_matrix_current_20260617.csv` | requirement-by-requirement proof matrix showing completed, partial, blocked and missing evidence |
| Funding threshold model | `exports/trading-mvp/analysis/funding_economic_thresholds_20260617.csv` | break-even funding bps needed under fee/slippage/hold scenarios |
| Experiment ledger | `exports/trading-mvp/experiments/experiment_ledger.jsonl` | every tested hypothesis has result/verdict trail |
| Funding 24h collect | `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl` | completed funding dataset: `7659` rows |
| Funding postprocess | `exports/trading-mvp/funding/funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json` | current funding branch rejected/failed economically |

## 4. Analysis Documents

| Document | Role |
|---|---|
| `docs/analysis/2026-06-06-anufriev-channel-strategy-audit-v1.md` | broad channel strategy audit |
| `docs/analysis/2026-06-06-anufriev-strategy-playbook-v1.md` | converts channel themes into setup/data/risk definitions |
| `docs/analysis/2026-06-06-anufriev-external-evidence-register.md` | external source register for HFT, spoofing, risk, venue issues |
| `docs/analysis/2026-06-06-anufriev-strategy-decision-matrix.md` | strategy family ranking and initial project decisions |
| `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md` | participant transfer/risk matrix |
| `docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md` | branch economics and current project fit |
| `docs/analysis/2026-06-17-anufriev-latest-rss-and-project-delta.md` | latest RSS delta: funding/P2P/stops/volume implications |
| `docs/analysis/2026-06-17-anufriev-latest-two-source-packet.md` | source packet for the two newest RSS Shorts, with transcript probe status |
| `docs/analysis/2026-06-17-anufriev-transcript-retry-priority-current.md` | prioritized transcript/source retry list for remaining metadata-only channel coverage |
| `docs/analysis/2026-06-17-anufriev-p0-transcript-retry-runbook.md` | visible-run runbook for top P0 transcript retry; prepared, not launched |
| `docs/analysis/2026-06-17-anufriev-strategy-scorecard-current.md` | readable scorecard comparing strategy families, metrics, economics and next actions |
| `docs/analysis/2026-06-17-anufriev-participant-transfer-scorecard-current.md` | readable participant transfer scorecard with source-grounded evidence and project actions |
| `docs/analysis/2026-06-17-funding-economic-thresholds.md` | funding/basis carry break-even thresholds and current 24h observed funding distribution |
| `docs/analysis/2026-06-17-anufriev-goal-current-state-and-roadmap.md` | current state, roadmap, RSS refresh update |
| `docs/analysis/2026-06-17-anufriev-completion-audit.md` | requirement-by-requirement completion audit |
| `docs/analysis/2026-06-17-anufriev-goal-gap-matrix-current.md` | current gap matrix for the original objective: evidence, missing proof, next allowed action and completion criteria |
| `docs/analysis/live-readiness-checklist.md` | hard gate for live-like operations |
| `docs/plans/2026-06-17-trading-mvp-evidence-to-engineering-backlog.md` | prioritized build/hold/block/reject backlog derived from channel evidence and project results |
| `docs/plans/2026-06-17-trading-mvp-edge-proof-execution-plan.md` | active plan focused on finding/proving trading edge; channel intake frozen |

## 5. Execution Plans And Scripts

| Artifact | Purpose | Status |
|---|---|---|
| `docs/plans/2026-06-15-trading-mvp-research-goal.md` | implementation plan and checkpoints | active |
| `docs/plans/2026-06-17-trading-mvp-visible-long-data-plan.md` | 7d/multi-week visible collection plan | prepared |
| `docs/plans/2026-06-17-trading-edge-preflight.md` | read-only preflight before any next edge-proof step | active |
| `tools/trading_edge_preflight.ps1` | checks active-run gate, channel freeze, live block, 24h funding rejection and wrapper readiness | active |
| `docs/plans/2026-06-17-trading-strategy-acceptance-gate.md` | acceptance contract for strategy promotion | active |
| `tools/trading_strategy_acceptance_gate.ps1` | blocks strategy acceptance unless scorecard/final-review/OOS/walk-forward/stress/economics gates pass | active |
| `tools/start_funding_collect_visible.ps1` | visible 7d funding/basis collector with predeclared watchlist binding | prepared, not launched |
| `TRADING_PREVIEW_7D_FUNDING.cmd` | preview the 7d funding collect plan without starting | active |
| `TRADING_START_7D_FUNDING_CONFIRMED.cmd` | confirmed visible 7d funding collect launcher with extra `START7D` prompt | prepared, not launched |
| `docs/plans/2026-06-17-funding-after-collect-final-review.md` | after-collect final-review plan | prepared |
| `tools/run_funding_final_review_visible.ps1` | guarded final-review wrapper | prepared, not launched |
| `tools/start_anufriev_p0_transcript_retry_visible.ps1` | visible foreground wrapper for P0 channel transcript retry | frozen by user scope; requires explicit override |
| `docs/plans/2026-06-17-trading-mvp-evidence-to-engineering-backlog.md` | current prioritized backlog from evidence to engineering action | active |
| `docs/plans/2026-06-17-trading-mvp-edge-proof-execution-plan.md` | current strategy-edge execution plan | active |
| `tools/trading_goal_status.ps1` | read-only goal dashboard: gate, scorecard, thresholds, next allowed action | prepared |
| `TRADING_GOAL_STATUS.cmd` | Windows shortcut for read-only goal dashboard | prepared |
| `docs/plans/2026-06-17-trading-next-goal-step-controller.md` | read-only controller for deciding the next valid goal action | active |
| `tools/trading_next_goal_step.ps1` | combines gate/preflight/acceptance/status and emits the next allowed action | active |
| `TRADING_NEXT_STEP.cmd` | Windows shortcut for next-step controller | active |
| `docs/plans/2026-06-17-funding-viability-gap-checker.md` | read-only funding/basis viability gap diagnostic | active |
| `tools/funding_viability_gap.ps1` | explains why current funding branch fails and what must improve | active |
| `TRADING_FUNDING_GAP.cmd` | Windows shortcut for funding viability gap diagnostic | active |
| `docs/plans/2026-06-17-funding-cost-assumption-gate.md` | read-only gate for fee/cost scenario realism | active |
| `tools/funding_cost_assumption_gate.ps1` | blocks lower-fee/maker/VIP/zero-cost assumptions from acceptance without real fee-tier evidence | active |
| `TRADING_FUNDING_COST_GATE.cmd` | Windows shortcut for funding cost assumption gate | active |
| `docs/plans/2026-06-17-funding-candidate-watchlist.md` | read-only market selector for next funding/basis proof step | active |
| `tools/funding_candidate_watchlist.ps1` | creates primary/secondary/diagnostic watchlist from 24h rank artifact | active |
| `TRADING_FUNDING_WATCHLIST.cmd` | Windows shortcut for funding candidate watchlist | active |
| `docs/plans/2026-06-17-funding-watchlist-review.md` | anti-cherry-picking review against predeclared funding watchlist | active |
| `tools/funding_watchlist_review.ps1` | compares rank/postprocess output against predeclared watchlist | active |
| `TRADING_FUNDING_WATCHLIST_REVIEW.cmd` | Windows shortcut for funding watchlist review | active |
| `docs/agent-log/active-run-gate.json` | active run gate metadata | currently open / no live PID |
| `tools/check_active_run_gate.ps1` | gate status checker | required before goal steps |

## 6. External Evidence Index

| Claim family | Source type | Current conclusion |
|---|---|---|
| HFT/order-book dynamics exist | SEC/FCA market structure sources | real phenomenon, not proof of retail bot profitability |
| Spoofing/manipulation exists | CFTC enforcement example | use observable labels; do not infer intent in code |
| Perpetual derivatives are risky | ESMA/IOSCO sources | research allowed; live leverage blocked by risk gates |
| Day trading base rate is poor | FINRA/Barber-Odean evidence | reject easy-profit/high-winrate marketing |
| Crypto venues/custody/conflicts | IOSCO crypto-asset recommendations | venue/custody risk card mandatory |
| P2P/off-ramp/crypto exchangers | Bank of Russia and FNS sources | compliance/tax/off-ramp risk, not trading alpha |

## 7. Requirements Coverage

| Objective requirement | Current evidence status | Gap |
|---|---|---|
| Analyze maximum videos | strong metadata coverage, partial transcript coverage | channel intake now frozen by user scope; do not expand unless explicitly reopened |
| Identify strategies | achieved at family level | individual claims still uneven |
| Compare participants | achieved for major participants; current transfer scorecard created | some participant claims metadata-heavy |
| Truth-check claims | achieved for main claim families | individual PnL/win-rate claims not independently verified |
| Compare with `trading_mvp` | achieved for tested branches | no accepted profitable branch |
| Economic model | achieved for tested configs | no 7d/multi-week proof |
| High win-rate / scalable result | not achieved | no setup passes gates |
| Live/project readiness | blocked by checklist | needs accepted research + paper-forward |

## 8. Blocked / No-Go Actions

- No live orders.
- No API keys.
- No margin/leverage execution.
- No Binance testnet as venue proxy.
- No background long-running collectors without explicit approval.
- No new grid-search while an active run gate is `RUNNING`.
- No new YouTube/RSS/transcript/source-packet work unless the user explicitly reopens channel analysis.
- No optimizing for win-rate without net PnL, expectancy, PF, drawdown, costs and sample size.
- No P2P/off-ramp module inside `trading_mvp` alpha.
- No "market-maker intent" labels in code; use observable features only.

## 9. Next Work Queue

Priority 1:

- Run `tools/trading_next_goal_step.ps1` to decide the next valid goal action.
- Run `tools/trading_edge_preflight.ps1` before the next goal step.
- Run `tools/trading_strategy_acceptance_gate.ps1` before any claim that a setup is accepted or ready for paper-forward/live discussion.
- Run `tools/funding_viability_gap.ps1` when deciding whether the next funding/basis step should be longer data, lower-cost assumptions, exchange/universe expansion, or branch rejection.
- Run `tools/funding_cost_assumption_gate.ps1` before using lower-fee, maker/VIP or zero-cost sensitivity as evidence.
- Run `tools/funding_candidate_watchlist.ps1` before interpreting a 7d funding/basis collect; it is a research focus list, not a trading signal.
- Run `tools/funding_watchlist_review.ps1` after final-review rank/postprocess artifacts; guarded final-review wrapper does this automatically.
- Launch visible 7d funding/basis collect only after explicit user confirmation.
- Use `TRADING_PREVIEW_7D_FUNDING.cmd` for no-start preview and `TRADING_START_7D_FUNDING_CONFIRMED.cmd` only after explicit approval.
- During run: only status/ETA checks.
- After run: run guarded final-review wrapper.

Priority 2:

- If funding final-review fails: either extend to 14-30d or keep funding as watchlist-only.
- If funding final-review accepts: create paper-forward plan, still no live orders.

Priority 3:

- For intraday/perp branch: collect dense independent multi-day WS/perp dataset before any further signal tuning.
- Do not continue tuning on the current thin 1.35h/6h-labeled sample.

Frozen:

- Do not resume channel RSS, transcript retry, or new source-packet work unless the user explicitly reopens channel analysis.
- Existing channel evidence remains a hypothesis source only; the active goal is now strategy edge proof in `trading_mvp`.

## 10. Current Answer To The Core Question

Новый рабочий фокус после user correction:

`stop channel intake -> use existing evidence only -> prove or reject trading edge in trading_mvp`

Самая жизнеспособная модель на текущую дату:

`research-only funding/basis carry engine + strict economic gates + multi-day data + live-readiness/compliance gate`

Самая перспективная, но пока недоказанная intraday модель:

`perp long/short microstructure + sweep/reclaim event labels + market-quality/fill/adverse-selection filters`

Что нельзя честно обещать сейчас:

- большой win-rate;
- стабильный profit;
- live-ready bot;
- масштабируемую HFT/скальпинг стратегию.

Что можно честно сказать:

- проект стал evidence-first research engine;
- текущие неработающие ветки зафиксированы и не будут проталкиваться в live;
- следующий доказательный шаг ясен и воспроизводим;
- live заблокирован до research + paper-forward + readiness gates.

