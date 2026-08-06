# Anufriev Participant Transfer Scorecard Current

Дата: 2026-06-17  
Статус: source-grounded transfer matrix для активной цели `trading_mvp`. Research-only; не является инвестсоветом, юридической консультацией или рекомендацией к live-торговле.

## 1. Grounded Summary

Этот документ фиксирует, какие идеи участников канала можно переносить в `trading_mvp`, а какие нельзя использовать как доказательство прибыльной стратегии. Главный вывод: переносимы процесс, риск-гейты, replay-дисциплина, нейтральные order-book event labels, отдельная funding/basis ветка и автоматизация исследований. Не переносимы обещания высокого win-rate, маркетинговые доходности, намерения маркетмейкера без order-level proof и live-торговля без строгих gates. Текущий проектный статус остается прежним: ни одна trading-ветка пока не получила accepted high-winrate/positive-EV verdict.

## 2. Source Quality

| Source | Quality | Limitation |
|---|---|---|
| `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md` | primary local source for participant transfer | mixed transcript-backed and metadata-only coverage |
| `docs/analysis/2026-06-06-anufriev-strategy-decision-matrix.md` | source for strategy-family transfer/risk table | some participant rows are intentionally compact |
| `docs/analysis/2026-06-17-anufriev-goal-current-state-and-roadmap.md` | current project decision and transfer map | summarizes prior evidence, not raw transcript |
| `docs/analysis/2026-06-17-anufriev-strategy-scorecard-current.md` | current tested strategy outcomes | covers tested branches, not every channel claim |

## 3. Machine-Readable Artifact

CSV: `exports/trading-mvp/analysis/anufriev_participant_transfer_scorecard_current_20260617.csv`

## 4. Participant Transfer Matrix

| Participant / source | Cluster | Transferable to project | Not transferable / risk | Current project mapping | Evidence strength | Recommended action |
|---|---|---|---|---|---|---|
| Михаил Латогузов | orderbook scalping / playbook / risk process | Pre-session briefing; repeatable setup playbook; do-not-trade-if-setup-unclear rule; orderbook/tape as execution context | automated edge, stable high win-rate after fees and direct manual-to-bot portability are not proven | `process_engine`, `experiment_ledger`, `setup_registry`, hard no-trade gates | high for process transfer; not profit proof | make setup registry and experiment ledger mandatory before live-like paper |
| Андрей Демченко | orderbook/tape / listings / high-winrate claim family | frame-by-frame L2/tape review; labeled examples; market/regime separation | 90% win-rate as KPI; manual pattern recognition without replay; guaranteed edge over HFT; direct R:R 1:1 proof not found | labeling/review discipline; `liquidity_sweep_reversal` only after replay; evaluate win-rate with expectancy/PF/costs/drawdown | high for microstructure thesis; not profit proof | keep as event-labeling/review input; do not optimize toward headline win-rate |
| Нарэк Григорян | market-maker narratives / stop cascade / orderbook filters | observable sweep, stop-cascade candidate, depth imbalance, quote burst, post-sweep reversal, market filters | intent claims and manipulation labels without order-level proof | neutral labels: `liquidity_sweep`, `cancel_burst`, `adverse_move_after_fill` | medium-high for hypotheses; intent not proven | use only observable detectors and measure selectivity/adverse selection |
| HAMAHA / Максим HAMAHA | futures / prop / professional process / risk | process, risk control, derivatives/perp research justification | metadata-only Wall Street methods; direct CEX bot edge | support `perp_replay` and risk process only | medium; partly metadata-heavy | require replay evidence for every derivatives signal |
| Игорь Андреев | futures strategy / derivatives branch | derivatives branch and live-trading observation as research material | discretionary futures method as CEX spot bot; title claims as profit evidence | strict derivatives accounting: maker/taker fees, funding, mark/index, liquidation risk | medium | keep derivatives accounting strict; no spot-bot inference |
| Иван Шашков | passive crypto / funding / carry / DeFi | funding/basis/carry research; capital allocation thinking | high-frequency win-rate; low-risk framing without counterparty, basis and liquidity risk | separate `funding/basis carry engine`; current 24h funding cost model failed with 0 trades | medium for branch direction; current strategy not accepted | only visible 7d/multi-week research after explicit approval |
| Legal-risk group: Андрей Тугарин / Михаил Успенский / Калой Ахильгов | legal / regulatory / P2P / withdrawals | venue risk cards; withdrawal/P2P restrictions; jurisdiction/compliance checks | alpha and HFT execution logic | live-readiness/compliance gate, separate from alpha research | medium to medium-high for risk controls; not alpha | keep outside trading alpha; require before live-like stage |
| Роман Пищулов / OpenClaw and AI group | AI / product / bots / automation | productization, bot operations, AI as research assistant, monitoring/reporting | bot/AI revenue as trading alpha proof; autonomous AI execution; LLM live decisions | AI helps classification, monitoring, reports, experiment summaries; deterministic replay decides acceptance | medium-high for tooling; not profit proof | use for research automation only; never bypass gates |
| Сергей Алексеев / high-return group | high-return claims / crowd psychology | crowd psychology hypotheses; claims to audit | 1000% annualized claims and success narratives as engineering evidence | high-risk claim family requiring OOS, fees, slippage, drawdown and sample-size proof | high for channel claims; low for profit proof | do not use as KPI or product promise |

## 5. Project-Level Interpretation

Accepted transfer into `trading_mvp`:

- `process_engine`, `experiment_ledger`, `setup_registry` and hard no-trade gates.
- Observable event labels instead of manipulation-intent labels.
- Separate funding/basis carry branch, not mixed with intraday HFT-style signals.
- Derivatives/perp accounting only with fees, funding, mark/index and liquidation-risk modeling.
- AI for research automation, not autonomous live decisions.
- Venue/legal/off-ramp risk as a mandatory readiness gate.

Rejected transfer:

- High win-rate headlines as project KPI.
- Marketing yield claims as expected return.
- Metadata-only strategy claims as proof.
- Manual scalping intuition as bot alpha.
- Live orders/API keys/margin execution before accepted research plus paper-forward gates.

## 6. Evidence Notes

| Field | Provenance | Evidence |
|---|---|---|
| Михаил Латогузов transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:56-76` |
| Андрей Демченко transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:84-112` |
| Нарэк Григорян transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:120-144` |
| HAMAHA transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:152-174` |
| Игорь Андреев transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:182-203` |
| Иван Шашков transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:211-232` |
| Legal-risk group transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:293-312` |
| Роман Пищулов / AI group transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:240-256,320-338` |
| Сергей Алексеев transfer/risk | extracted | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md:264-285` |
| Current project direction | selected | `docs/analysis/2026-06-17-anufriev-goal-current-state-and-roadmap.md:126-150` |
| Current strategy status | selected | `docs/analysis/2026-06-17-anufriev-strategy-scorecard-current.md:25-35,46-53` |

## 7. Current Decision

Этот scorecard не открывает live-торговлю. Он уточняет, что следующий разрешенный proof path остается прежним: видимый 7d funding/basis collect после явного подтверждения пользователя, затем guarded final-review. Intraday/perp ветка требует новой независимой плотной multi-day выборки до дальнейшей оптимизации.
