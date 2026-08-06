# Strategy Playbook v1: From Anufriev Channel Hypotheses to trading_mvp Experiments

Дата: 2026-06-06  
Статус: research-only. Не является инвестсоветом, торговой рекомендацией или инструкцией к live-торговле.

## 1. Purpose

Этот playbook переводит анализ канала «Хедлайнеры | Никита Ануфриев» в проверяемые стратегии для `trading_mvp`.

Правило: канал дает гипотезу, внешний источник задает риск-контекст, replay/backtest решает, есть ли edge после комиссий, спреда, очереди, проскальзывания и funding.

External verification companion: `docs/analysis/2026-06-06-anufriev-external-evidence-register.md`.

## 2. Source families

| Family | Channel coverage | Most useful source examples | Project use |
|---|---:|---|---|
| Orderbook / tape / market maker | 17 all-287 videos / 944k views | `Csj02qT4F00`, `PYfFtOIp84U`, `vKunPVUP1nk`, `mcYMwpHCdVM`, `Z5UjQOF7QI0` | Microstructure replay, perp long/short, liquidity sweep detector |
| High win-rate / deposit growth | 60 / 4.26M views | `IpeygkYEk6o`, `DLjlFGdx32M`, `eUZcEUH_3Ak`, `-6tKe1FIG4I` | Claims to audit, not a target metric |
| Risk / psychology / playbook | 36 / 2.09M views | `eUZcEUH_3Ak`, `rdEqMiqSJNU`, `fuQgXJAgmBU`, `RYGI1LrFfgA`, `V6xNos8rAs4` | Risk gates, experiment ledger, stop conditions |
| AI / bots / tooling | 50 / 3.25M views | `gNQYvQp3lDM`, `Jt46X8Vp1a8`, `jSh-7dm9KhY`, `tw1OFVWsdHU` | Research automation and monitoring |
| Funding / passive / P2P | 14 / 1.88M views | `PWbSsDQv5j8`, `QR9TWOo_cC4`, `DLjlFGdx32M`, `eUZcEUH_3Ak` | Separate carry engine |
| Legal / regulatory crypto | 12 / 1.10M views | `18UNEZr2odw`, `pF181EcDFQc`, `Pc4llCsVeRQ`, `5nYcxDAGyIU` | Compliance/risk checklist |
| Futures / prop / derivatives | 12 / 1.10M views | `AodqaoVPLOY`, `nmWaxiP58V4`, `uNYfylFFQ7g`, `PUAyUaSommg` | Perp replay and short-side research |
| News / event / regime | 6 / 179k views | `IpRpJ4F3rjk`, `hRQ21mkJVJQ`, `zf8a7-Ob5C4` | Regime filter |

## 3. Playbook entries

### P0. Perp Long/Short Microstructure Replay

Channel rationale:
- Orderbook and futures/prop clusters imply that spot-only long bias is too narrow.
- Current spot replay has thousands of `short_disabled` skipped signals.

Setup definition:
- Instrument: USDT perpetual contracts on MEXC/Gate first.
- Data: BBO, L2 depth, trades, mark price, index price, funding rate, next funding time.
- Signals: `flow_continue`, `fade_exhaustion`, then `liquidity_sweep_reversal`.
- Execution modes: maker and taker, both simulated.
- Shorting enabled by default in replay, not live.

Entry candidates:
- Long continuation: bid imbalance plus positive signed flow.
- Short continuation: ask imbalance plus negative signed flow.
- Long fade: strong sell flow fails to break bid/mark support.
- Short fade: strong buy flow fails to break ask/mark resistance.

Exit:
- Take-profit bps, stop-loss bps, max hold seconds.
- Force exit on funding flip, mark/index divergence, spread blowout, or quality failure.

Economics:
- PnL = price PnL - fees - slippage +/- funding impact.
- Maker fills need queue/adverse-selection modeling.

Acceptance gate:
- Minimum 50 trades across 6-24h replay.
- Net PnL > 0 after fees/funding/slippage.
- Profit factor >= 1.2.
- Expectancy > 0.
- No single market > 60% of net PnL unless explicitly market-specific.

Verdict now:
- Build next. No live orders.

### P0. Liquidity Sweep Reversal

Channel rationale:
- Better matches stop-hunting / market-maker narratives than raw imbalance.
- Uses observable data, not claims about participant intent.

Setup definition:
- Detect rapid sweep through recent best bid/ask or local low/high.
- Require large taker volume and temporary spread expansion.
- Require reclaim/rejection within a short window.
- Enter only if queue/fill probability is acceptable.

Long version:
- Sell sweep below recent bid/low.
- Bid depth replenishes or price reclaims sweep level.
- Signed flow remains negative but price stops falling.
- Enter long passively or with conservative taker simulation.

Short version:
- Buy sweep above recent ask/high.
- Ask depth replenishes or price rejects breakout.
- Signed flow remains positive but price stops rising.
- Enter short in perp replay.

Invalidation:
- Sweep continues without reclaim.
- Spread remains wide.
- Mark/index divergence increases.
- Fill would happen only after adverse move.

Acceptance gate:
- Out-of-sample PF >= 1.2.
- Net PnL > 0.
- Minimum 50 trades.
- Explicit false-sweep rate metric.

Verdict now:
- Build after perp replay scaffold.

### P1. Market Quality and Fill Probability Filter

Channel rationale:
- Good traders in the channel emphasize selectivity, not trading every signal.
- Current maker replay shows `maker_entry_expired`, `maker_exit_expired`, quality filters, and sparse-flow skips.

Setup definition:
- Score each market/time window before allowing any signal.
- Inputs: trade count, trade notional, quote updates, average spread, min top qty, fill rate, adverse move after fill.

Allow trading only when:
- Trade-flow density exceeds threshold.
- Average spread below threshold.
- Quote update count high enough.
- Maker fill probability above threshold.
- Adverse selection after recent fills below threshold.

Acceptance gate:
- Higher expectancy than unfiltered baseline.
- Not just lower trade count.
- Same or better net PnL with lower drawdown.

Verdict now:
- Mandatory infrastructure layer.

### P1. Risk / Playbook Process Engine

Channel rationale:
- Risk/playbook/process is one of the strongest repeat themes in the channel.
- It is directly transferable even before alpha is proven.

Setup definition:
- Every experiment has a hypothesis, source video, external rationale, dataset, config, result, verdict.
- Daily stop conditions: max drawdown, consecutive failed fills, API/data errors, spread regime failure.
- No strategy promoted without replay evidence.

Acceptance gate:
- Experiment ledger exists.
- Every strategy config maps to source and result.
- No orphaned "promising" claims without metrics.

Verdict now:
- Mandatory. Should be implemented before live-like paper.

### P2. Funding / Basis Carry

Channel rationale:
- Funding/passive crypto cluster is meaningful but not HFT.
- Existing module already separates carry from L2 scalping.

Setup definition:
- Long spot + short perp.
- Entry when positive funding, acceptable basis, both legs liquid, spreads controlled.
- Exit on negative funding, basis widening, liquidity deterioration, or score drop.

Economics:
- PnL = funding payout + basis PnL - spot fees - perp fees - slippage - borrow/margin costs.
- Requires longer holding horizon than scalping.

Acceptance gate:
- 7-30 day simulation.
- Net carry positive after all costs.
- Stress test for basis widening.
- Exchange risk noted per venue.

Verdict now:
- Keep as separate low-frequency engine. Do not mix into HFT score.

### P2. News / Event / Regime Filter

Channel rationale:
- Channel has news/cycle/Polymarket content.
- Pure L2 edge is weak; regime labels may improve selectivity.

Setup definition:
- Add labels for market regime: high volatility, low volatility, listing, delisting, major news, event market catalyst, BTC macro move.
- Replay same signals with/without regime filter.

Acceptance gate:
- Filter improves expectancy and net PnL without overfitting one event.
- Works across at least several market windows.

Verdict now:
- Useful after perp replay and sweep detector.

### P3. AI Research Tooling

Channel rationale:
- AI/bot content is popular, but autonomous trade profitability is unproven.

Valid uses:
- Classify videos and claims.
- Build experiment summaries.
- Detect anomalies in logs.
- Generate candidate features for replay.
- Monitor data quality.

Invalid uses:
- No AI-only live orders.
- No "GPT says buy/sell" path.
- No bypass of replay gates.

Acceptance gate:
- AI outputs produce deterministic artifacts reviewed by code/tests.
- Any trade feature must survive replay.

Verdict now:
- Use for research velocity, not alpha.

### P3. Legal / Regulatory Risk Layer

Channel rationale:
- Legal crypto videos have high views and practical risk relevance.

Project use:
- Exchange jurisdiction notes.
- Withdrawal/P2P restrictions.
- Account blocking risks.
- Terms-of-service constraints for market data and automation.

Acceptance gate:
- Before live-like mode, each venue has a risk card.
- P2P/withdrawal workflows are outside trading alpha.

Verdict now:
- Compliance layer, not a trading strategy.

## 4. Metrics that matter

Do not optimize:
- Raw win-rate.
- Number of trades.
- One lucky market.
- Gross PnL before fees.

Optimize:
- Net PnL after all costs.
- Expectancy.
- Profit factor.
- Max drawdown.
- Fill rate.
- Adverse selection after fill.
- Stability across markets.
- Out-of-sample consistency.

## 5. Immediate engineering sequence

1. Build `perp_replay` data schema and simulation accounting.
2. Add public MEXC/Gate perp market data collection.
3. Port `flow_continue` and `fade_exhaustion` to perps with short enabled.
4. Add `liquidity_sweep_reversal`.
5. Add market-quality/fill metrics to every replay result.
6. Create experiment ledger.
7. Only then consider longer paper forward runs.

## 6. Explicit no-live threshold

No live orders until:
- At least one strategy passes 6-24h replay gates.
- It then passes 3-7 days paper forward.
- All costs are included.
- Data outages and API errors are measured.
- There is a hard kill switch and daily loss cap.

Current state:
- Spot maker continuation failed.
- Spot maker fade/exhaustion failed.
- Short-horizon funding failed.
- Therefore live trading is not justified.
