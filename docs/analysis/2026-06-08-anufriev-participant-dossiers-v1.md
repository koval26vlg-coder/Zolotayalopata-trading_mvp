# Anufriev Channel Participant Dossiers v1

Дата: 2026-06-08  
Статус: source-grounded participant layer. Не является инвестсоветом или рекомендацией к live-торговле.

## 1. Purpose

Этот документ закрывает отдельный слой долгой цели: сравнить участников канала не по популярности, а по тому, что реально переносимо в `trading_mvp`.

Правило доказательности:

- `transcript-backed`: есть `metadata+transcript_card` или `metadata+transcript_retry_card`.
- `metadata-backed`: имя/тема есть в title/metadata, но тезисы не подтверждены claim windows.
- `external/project-checked`: применимость дополнительно проверена через внешние источники или артефакты `trading_mvp`.

Основные источники:

- Scorecard: `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv`
- Transcript union: `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json`
- HFT source packet: `docs/analysis/2026-06-01-hft-scalping-kriticheskiy-razbor.md`
- Strategy economics v2: `docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md`
- Fresh project grid: `exports/trading-mvp/backtests/ws_grid_search_signal_type_maker_quality_6h_20260608.json`

## 2. Participant coverage summary

| Participant | Videos in all-287 scorecard | Views | Transcript-backed videos | Main clusters | Evidence grade |
|---|---:|---:|---:|---|---|
| Андрей Тугарин | 4 | 790,203 | 1 | legal/regulatory, P2P/funding risk | medium |
| Khairullin | 3 | 660,635 | 0 | general trading | low |
| Игорь Андреев | 5 | 576,616 | 2 | futures/prop, general trading, high-return claims | medium |
| HAMAHA / Максим HAMAHA | 7 | 456,815 | 3 | futures/prop, risk, orderbook, market context | medium |
| Иван Шашков | 4 | 360,468 | 2 | DeFi/passive/funding carry | medium |
| Роман Пищулов / OpenClaw | 1 | 187,033 | 1 | AI/product/bots | medium-high |
| Сергей Алексеев | 3 | 136,503 | 3 | high-return, psychology, cycle/success narratives | high for channel claims, low for profit proof |
| Михаил Успенский | 2 | 118,800 | 1 | legal/regulatory crypto | medium |
| Денис Стукалин | 2 | 110,061 | 1 | risk, small-deposit claims | medium-low |
| Калой Ахильгов | 2 | 83,448 | 2 | legal/regulatory crypto | medium-high |
| Нарэк Григорян | 3 | 77,321 | 2 | orderbook, market-maker/manipulation, deposit growth | medium-high for hypotheses |
| Михаил Латогузов | 3 | 76,677 | 3 | orderbook scalping, playbook, risk | high for process transfer |
| Тимур Султанов | 2 | 70,213 | 1 | AI trading | medium |
| Влад Утушкин | 1 | 68,458 | 1 | crypto opportunity / high-return framing | medium-low |
| Крипто Котлета | 1 | 67,456 | 1 | beginner/high-return crypto | medium-low |
| Андрей Демченко | 2 | 59,333 | 1 | orderbook/high-winrate/process | high for microstructure thesis, not profit proof |
| Льюис Борселино | 1 | 58,839 | 1 | futures/prop historical context | medium |

Important limitation: `views` and `video count` measure channel attention, not strategy profitability.

## 3. Dossiers

### 3.1. Михаил Латогузов

Local evidence:

| Video | Date | Views | Evidence | Cluster |
|---|---:|---:|---|---|
| `Z5UjQOF7QI0` / "Где на самом деле делаются деньги в трейдинге? Взгляд скальпера с 7-летним опытом" | 2025-12-23 | 62,464 | transcript-backed | orderbook/general |
| `Gz3k_Z-1_fY` / "Не заходи в трейдинг, пока не посмотришь ЭТО!" | 2026-05-26 | 9,240 | transcript-backed | general |
| `mx2E3iC0SRM` / "Эта стратегия СПАСЕТ твой депозит..." | 2026-02-19 | 4,973 | transcript-backed | high-return/risk/general |

What is transferable:

- Pre-session briefing.
- Playbook of repeatable setups.
- "Do not trade if you do not understand the setup" rule.
- Orderbook/tape as execution context, not a magic signal.

What is not proven:

- Automated edge.
- Stable high win-rate after fees.
- Direct portability from manual scalping to bot execution.

Project decision:

- Transfer as `process_engine`, `experiment_ledger`, `setup_registry`, and hard no-trade gates.
- Do not treat as proof that current maker strategy is profitable.

### 3.2. Андрей Демченко

Local evidence:

| Video | Date | Views | Evidence | Cluster |
|---|---:|---:|---|---|
| `dLpQ6oHnJIY` / "Трейдинг без иллюзий..." | 2025-09-27 | 52,663 | metadata; source packet manually inspected | risk/general |
| `xmXWwzRxYAw` / "Как делать 90% винрейт без предсказываний рынка?" | 2026-05-28 | 6,670 | transcript-backed | high-winrate |

Source packet findings:

- Discusses iceberg-like hidden liquidity.
- Prioritizes order book/tape review and video replay.
- Talks about listings and less liquid instruments.
- The "90%" claim is local to a recognizable pattern, not validated as a full-system metric.
- Direct `R:R 1:1` proof was not found in the inspected source packet.

What is transferable:

- Frame-by-frame review of order book and tape.
- Build labeled examples before automating.
- Avoid assuming top liquid markets are easiest.
- Treat illiquid listings as separate high-risk/high-anomaly regime.

What is not transferable:

- "90% win-rate" as project KPI.
- Manual pattern recognition without statistical replay.
- Any claim that a human/bot is guaranteed to beat HFT in illiquid coins.

Project decision:

- Build `liquidity_sweep_reversal` only after `perp_replay`.
- Add dataset labeling tools before more signal tuning.
- Use win-rate only together with expectancy, profit factor, costs and drawdown.

### 3.3. Нарэк Григорян

Local evidence:

| Video | Date | Views | Evidence | Cluster |
|---|---:|---:|---|---|
| `mcYMwpHCdVM` / "Как СНГ трейдеры зарабатывают на манипуляциях маркетмейкеров" | 2025-09-07 | 62,702 | metadata; source packet manually inspected | orderbook/general |
| `Z-LlG2o1Hd0` / "Как РАЗОГНАТЬ ДЕПОЗИТ..." | 2025-10-08 | 9,170 | transcript retry-backed | high-return/risk/general |
| `3mBYoA6gqh8` / "НЕ ТОРГУЙ ЭТИ МОНЕТЫ..." | 2026-05-21 | 5,449 | transcript-backed | orderbook/general |

Source packet findings:

- Uses stack/tape/clusters framing.
- Mentions stops, milliseconds, professional software.
- Gives market-maker/manipulation interpretation.
- Strongest project value is as a hypothesis source for stop-cascade and liquidity-sweep behavior.

What is transferable:

- Observable features: sweep, stop cascade candidate, depth imbalance, quote burst, post-sweep reversal.
- Market selection and "do not trade these coins" style filters.

What is not transferable:

- Intent claims like "market maker hunted stops" as factual code labels.
- Any strategy that depends on proving manipulation without order-level data.

Project decision:

- Rename all implementation concepts to observable features.
- Build detectors with neutral labels: `liquidity_sweep`, `cancel_burst`, `adverse_move_after_fill`.

### 3.4. HAMAHA / Максим HAMAHA

Local evidence:

| Videos | Count | Views | Evidence |
|---|---:|---:|---|
| HAMAHA / Максим HAMAHA rows | 7 | 456,815 | 3 transcript-backed, 4 metadata-only |

Notable videos:

- `uNYfylFFQ7g` / Wall Street/professional trading, 210,766 views, metadata-only.
- `O_mq6qXd2oM` / stop-loss / market-maker framing, 20,318 views, transcript-backed.
- `8gVTiVL5vRI` / risk and emotion control, 25,303 views, transcript-backed.

What is transferable:

- Professional-process framing.
- Risk and emotion control.
- Derivatives/prop/futures mindset as reason to build perp research.

What is not proven:

- Specific Wall Street methods from metadata-only videos.
- Direct CEX bot edge.

Project decision:

- Use as support for `perp_replay` and risk process.
- Do not use metadata-only Wall Street claims as proof.

### 3.5. Игорь Андреев

Local evidence:

| Videos | Count | Views | Evidence |
|---|---:|---:|---|
| Игорь Андреев rows | 5 | 576,616 | 2 transcript-backed, 3 metadata-only |

Notable videos:

- `AodqaoVPLOY` / futures strategy, 86,850 views, transcript-backed.
- `6PIei-ajaHA` / live trading with $1M+, 67,356 views, transcript-backed.
- Older strategy/interview videos are higher-view but metadata-only.

What is transferable:

- Futures/derivatives branch.
- Live-trading observation as research material, not proof.

What is not transferable:

- Any claim that a discretionary futures method becomes a CEX spot bot.
- "Made most millionaires" style title as evidence of profitability.

Project decision:

- Use as another reason to prioritize `perp_replay`.
- Require separate derivatives accounting: maker/taker fees, funding, mark/index, liquidation risk.

### 3.6. Иван Шашков

Local evidence:

| Videos | Count | Views | Evidence |
|---|---:|---:|---|
| Иван Шашков rows | 4 | 360,468 | 2 transcript-backed, 2 metadata-only |

Notable videos:

- `PWbSsDQv5j8` / crypto without trading and nerves, transcript-backed.
- `QR9TWOo_cC4` / passive crypto income, transcript-backed.
- DeFi videos are high-view but metadata-only.

What is transferable:

- Funding/basis/carry and passive-yield research branch.
- Capital allocation thinking.

What is not transferable:

- High-frequency win-rate.
- Low-risk or "without nerves" framing without counterparty, basis and liquidity risk.

Project decision:

- Keep `funding/basis carry engine` separate from microstructure scalping.
- Move funding tests to 7-30 day horizon; current short-horizon gate gave 41 markets and 0 trades.

### 3.7. Роман Пищулов / OpenClaw

Local evidence:

| Video | Date | Views | Evidence | Cluster |
|---|---:|---:|---|---|
| `gNQYvQp3lDM` / "250 000$ на ботах..." | 2026-03-03 | 187,033 | transcript-backed | AI/product/bots |

What is transferable:

- Productization.
- Bot operations.
- Research tooling and automation.

What is not transferable:

- AI/bot revenue as proof of trading alpha.
- Autonomous AI execution.

Project decision:

- Use AI for research pipeline: classification, monitoring, report generation, experiment summaries.
- AI cannot bypass deterministic replay and risk gates.

### 3.8. Сергей Алексеев

Local evidence:

| Videos | Count | Views | Evidence |
|---|---:|---:|---|
| Сергей Алексеев rows | 3 | 136,503 | 3 transcript-backed |

Notable videos:

- `-6tKe1FIG4I` / "1000% годовых", transcript retry-backed.
- `SEgQTlJF9Ho` / psychology of crowd, transcript-backed.
- `a1JwFxfgnlc` / trading as fastest success cycle, transcript-backed.

What is transferable:

- Crowd psychology as hypothesis source.
- High-return stories as claims to audit.

What is not transferable:

- 1000% annualized claims as system expectation.
- Success-cycle narrative as engineering evidence.

Project decision:

- Treat as `high-risk claim family`.
- Any strategy derived here needs extra proof: out-of-sample replay, fees, slippage, drawdown, sample size.

### 3.9. Legal-risk group: Андрей Тугарин, Михаил Успенский, Калой Ахильгов

Local evidence:

| Participant | Videos | Views | Transcript-backed | Project role |
|---|---:|---:|---:|---|
| Андрей Тугарин | 4 | 790,203 | 1 | withdrawals/P2P/legal risk |
| Михаил Успенский | 2 | 118,800 | 1 | regulatory risk |
| Калой Ахильгов | 2 | 83,448 | 2 | criminal/legal crypto risk |

What is transferable:

- Venue risk cards.
- Withdrawal/P2P restrictions.
- Jurisdiction and compliance checks.
- "Do not build a profitable bot that cannot safely move funds" rule.

What is not transferable:

- Alpha.
- High-frequency execution logic.

Project decision:

- Add venue risk cards before any live-like stage.
- Separate compliance risk from signal research.

### 3.10. AI-trading group: Тимур Султанов and AI/bot episodes

Local evidence:

| Participant | Videos | Views | Transcript-backed | Role |
|---|---:|---:|---:|---|
| Тимур Султанов | 2 | 70,213 | 1 | AI trading framing |
| Роман Пищулов / OpenClaw | 1 | 187,033 | 1 | product/bot operations |
| `ou2b3e0Q3t8` AI engineer episode | 1 | 7,392 | transcript retry-backed | agents vs bots framing |

What is transferable:

- AI as research assistant.
- Agents/bots distinction for operational tooling.
- Automated monitoring and report generation.

What is not transferable:

- LLM deciding trades live.
- "AI profitable trading" without replay.

Project decision:

- AI can suggest hypotheses and summarize experiments.
- Deterministic code and replay must make final signal acceptance decisions.

## 4. Participant ranking for `trading_mvp`

| Rank | Participant/group | Why | Transfer mode | Current action |
|---:|---|---|---|---|
| 1 | Михаил Латогузов | Best process/playbook transfer, transcript-backed | Risk/process engine | Use experiment ledger and setup registry |
| 2 | Андрей Демченко | Strong orderbook/tape review thesis | Labeling + sweep/reversal research | Build labeled event review after perp replay |
| 3 | Нарэк Григорян | Stop cascade / market-maker narratives | Observable sweep features | Build neutral detector, avoid intent labels |
| 4 | HAMAHA / Максим | Derivatives/pro process/risk | Perp replay justification | Use as support, not proof |
| 5 | Игорь Андреев | Futures/derivatives branch | Perp replay | Build derivatives accounting |
| 6 | Иван Шашков | Funding/carry branch | Separate carry engine | Extend to multi-day backtest |
| 7 | Legal-risk group | Compliance and venue risk | Venue risk cards | Add before live-like paper |
| 8 | Роман Пищулов / AI group | Productization/tooling | Research automation | Use AI for reports, not execution |
| 9 | Сергей Алексеев / high-return group | Strong marketing/high-return claims | Claim audit | Do not use as KPI |

## 5. What changes in project decisions

The participant layer reinforces the same project pivot:

1. `perp_replay` is the next engineering module, not another spot-only signal tweak.
2. `liquidity_sweep_reversal` should be built as an observable event detector, not a "market-maker manipulation" detector.
3. `experiment_ledger` and `setup_registry` should be the standard interface before live-like paper.
4. `funding/basis` remains a separate carry branch with longer horizon.
5. AI is tooling, not autonomous execution.
6. Legal/venue risk is not optional if project moves toward real exchanges.

## 6. No-go interpretations

- Do not rank participants by views as if views prove profitability.
- Do not turn "90% win-rate" or "1000% годовых" titles into target metrics.
- Do not infer market-maker intent from a single order-book pattern.
- Do not mix DeFi/passive, funding carry and intraday microstructure into one score.
- Do not use metadata-only videos as hard proof of strategy mechanics.

## 7. Next work

Best next research actions:

1. Implement `perp_replay` for MEXC/Gate public perps.
2. Extend the experiment ledger with fields: source participant, video id, claim family, config, dataset, result, verdict.
3. Keep the setup registry synchronized for `flow_continue`, `fade_exhaustion`, `liquidity_sweep_reversal`.
4. Continue transcript retries later with `--stop-on-rate-limit`; priority starts at `gQ9f2fFnDn8`.
