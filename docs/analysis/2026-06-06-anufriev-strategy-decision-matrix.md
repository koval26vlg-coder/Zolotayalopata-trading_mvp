# Anufriev Channel Strategy Decision Matrix for trading_mvp

Дата: 2026-06-06  
Статус: research-only decision layer. Это не инвестсовет и не рекомендация к live-торговле.

Companion artifact: `docs/analysis/2026-06-06-anufriev-strategy-playbook-v1.md` turns this matrix into setup/data/entry/exit/risk/acceptance definitions.

External verification companion: `docs/analysis/2026-06-06-anufriev-external-evidence-register.md`.

## 1. Evidence base

| Источник | Coverage | Назначение |
|---|---:|---|
| Full channel flat catalog | 461 видео | Карта всего канала |
| Trading/crypto/investing catalog | 287 видео | Полная рабочая выборка по цели |
| All-287 metadata scorecard | 287 видео / 20 562 076 views | Strategy clusters, views, participants, dates |
| Transcript-backed claim cards | 46 видео | Проверка формулировок и high-risk claims |
| trading_mvp 6h spot maker replay | 472 583 events / 192 configs | Проверка переносимости orderbook ideas |
| funding/basis quality gate | 41 markets | Проверка short-horizon carry economics |

Transcript gap:
- У 287 видео есть ru auto-captions в metadata.
- Прямой transcript API остановился после 46 видео из-за IP block.
- timedtext/json3 attempt дал 22 success, затем `HTTP 429`; union coverage остался 46.

Вывод: all-287 можно использовать как карту канала, но claims о доходности, win-rate и переносимости в код подтверждать только transcript-backed + external + replay evidence.

## 2. Strategy decision matrix

| Rank | Strategy family | Channel evidence | External truth check | trading_mvp fit | Economics | Decision |
|---:|---|---|---|---|---|---|
| 1 | Perp long/short microstructure replay | Futures/prop + orderbook clusters: 29 видео совокупно | Derivatives real, but leverage/regulatory risk high | Снимает spot-only ограничение и `short_disabled` | Research cost low; live capital/risk medium | Build next, no live |
| 2 | Market-quality + fill probability model | Risk/playbook + orderbook тезисы | Execution quality is decisive in microstructure | Уже видно через maker expired/skipped signals | Infra feature, improves all strategies | Build as gating layer |
| 3 | Liquidity sweep / stop cascade detector | Market-maker/stop-loss narratives | Spoofing/stop cascades exist, intent hard to prove | Better match than raw imbalance/fade | Potential alpha, needs labeling | Build after perp replay scaffold |
| 4 | Risk/playbook/process engine | 36 all-287 videos, 2.09M views | Strongly aligned with professional risk practice | Directly maps to experiment ledger and stop rules | No alpha, but prevents blow-ups | Mandatory |
| 5 | Funding/basis carry | 14 videos, 1.88M views | Real carry mechanism, not HFT | Module exists; short horizon weak | Capital/time-horizon heavy | Keep separate |
| 6 | News/event/regime filter | 6 videos, 179k views | Can improve selectivity, hard to automate safely | Useful as regime label over replay | Low infra cost; uncertain edge | Later |
| 7 | AI-assisted research | 50 videos, 3.25M views | Useful for tooling, weak proof for autonomous profit | Good for classification and monitoring | High productivity, low direct alpha | Use as tooling |
| 8 | High-winrate/deposit growth | 60 videos, 4.26M views | High survivorship/selection bias | Dangerous if used as KPI | Misleading without EV | Treat as claims to audit, not strategy |

## 3. Participant/usefulness matrix

| Participant / source | Cluster | Useful project transfer | Risk |
|---|---|---|---|
| Михаил Латогузов | Orderbook scalping / playbook | Briefing, playbook, only trade understood setups | Does not prove automated edge |
| Андрей Демченко | Orderbook/tape, listings, nilliquid markets | L2/tape review, avoid top saturated markets, frame-by-frame setup work | 90% win-rate is local claim, not system metric |
| Нарэк Григорян | Market maker / manipulation | Liquidity sweep and stop cascade hypotheses | Intent attribution can become narrative trap |
| HAMAHA / Максим | Futures/Wall Street/professional trading | Professional process and risk culture | Metadata-heavy; needs more transcript verification |
| Игорь Андреев | Futures strategy | Supports derivatives branch | Not directly transferable to CEX spot |
| Иван Шашков | Passive/funding/DeFi | Carry/yield branch and capital allocation thinking | Counterparty/regulatory/liquidity risk |
| Андрей Тугарин / Михаил Успенский / Калой Ахильгов | Legal crypto | Compliance, withdrawals, P2P risk | Not alpha |
| Роман Пищулов / OpenClaw | AI/product/bots | Productization, tooling, bot operations | Not evidence of trading profitability |
| Сергей Алексеев / high-return videos | High-winrate/deposit growth | Hypotheses to audit | High marketing/survivorship risk |

## 4. Current trading_mvp verdict against channel claims

| Claim family | Current test | Result | Verdict |
|---|---|---|---|
| Spot maker orderbook continuation | 6h maker replay, `flow_continue` | 45 trades, 42.22% win-rate, net PnL -0.2065, PF 0.721 | Not live-viable |
| Spot maker fade/exhaustion | 6h maker replay, `fade_exhaustion` | 77 trades, 45.45% win-rate, net PnL -0.4375, PF 0.648 | More trades, worse EV |
| Funding/basis short horizon | 41 markets quality gate | 0 trades, no positive short-horizon carry | Not high-frequency strategy |
| High win-rate objective | EV gates in replay | Failed `min_win_rate`, `expectancy`, `net_pnl`, `profit_factor` | Win-rate alone rejected |

The project is aligned with the channel's useful ideas only if it stays evidence-first. The channel supplies hypotheses; replay decides whether they survive fees, fill quality, and adverse selection.

## 5. Build backlog with acceptance gates

| Priority | Work item | Why now | Acceptance gate |
|---:|---|---|---|
| P0 | `perp_replay` normalized event model | Spot-only blocks short-side microstructure | Replay artifact over 6-24h, long+short, maker+taker, fees/funding/slippage |
| P0 | Perp exchange adapters for public data | Need realistic bid/ask/trades for futures | MEXC/Gate first, optional OKX/Bybit next |
| P0 | `liquidity_sweep_reversal` signal definition | Better maps stop-hunting claims | Detects sweep, reversal, post-sweep fill quality; unit tests included |
| P1 | Market/hour quality scheduler | Avoid dead periods and bad spread regimes | Heatmap by market/hour: trade density, spread, fill rate, adverse selection |
| P1 | Fill model v2 | Maker fills can be toxic | Metrics: fill_rate, queue_time, adverse_move_after_fill |
| P1 | Experiment ledger | Channel has too many claims to track manually | Every hypothesis has source, config, dataset, result, verdict |
| P2 | News/regime labels | Improve selectivity | Replay with/without regime filter comparison |
| P2 | Funding carry multi-day backtest | Funding horizon mismatch | 7-30 day simulation with basis, fees, funding, margin assumptions |

## 6. Economic model by branch

| Branch | Cost center | Revenue mechanism | Main failure mode | Scale condition |
|---|---|---|---|---|
| Perp microstructure | Data, infra, latency, fees, funding | Short micro-moves, spread capture, adverse-flow avoidance | Toxic fills, overfit thresholds, liquidation risk | Stable PF > 1.2 out-of-sample, controlled drawdown |
| Liquidity sweep detector | Labeling, replay, feature work | Reversal after forced liquidation/stop cascade | False sweep detection, no fill, continuation against us | Works across markets/regimes, not one coin |
| Market-quality scheduler | Data storage and analytics | Removes negative-EV periods | Too strict = no trades | Higher expectancy with acceptable trade count |
| Funding carry | Capital, margin, borrow, basis risk | Funding payout + basis convergence | Basis widening, exchange/margin risk | Multi-day positive net after fees/slippage |
| News/event filter | Data feed quality, labeling | Trade only during catalyst regimes | Late/false news, volatility spikes | Improves replay selectivity after costs |
| AI tooling | Prompting, scripts, evaluation | Faster research and monitoring | Hallucinated signals | AI output never bypasses replay gates |

## 7. No-go rules

- No live orders until a strategy passes replay and forward paper gates.
- No Binance testnet as trading venue.
- No optimization for win-rate without net PnL, expectancy, profit factor, drawdown, fees, slippage, and fill probability.
- No mixing funding carry into HFT signal scoring.
- No market-maker intent claims in code; use observable features only.
- No AI autonomous execution without deterministic gates and replay proof.

## 8. Next engineering step

`perp_replay` scaffold is in place. The next research module step is to wire real perp adapters/data into it:

1. Add perpetual normalized event schema: exchange, symbol, bid/ask, trades, mark price, index price, funding rate.
2. Add public WS/REST adapters for MEXC and Gate perps first.
3. Reuse `StrategyConfig.signal_type`, add `allow_short=True` by default for perp replay.
4. Add funding/fee/slippage accounting in replay.
5. Run same grid families: `flow_continue`, `fade_exhaustion`, then `liquidity_sweep_reversal`.
6. Gate with `min_trades`, `win_rate`, `expectancy`, `net_pnl`, `profit_factor`, `max_drawdown`, and fill-quality metrics.

Acceptance target for first viable candidate:
- Minimum 50 trades across 6-24h replay.
- Net PnL > 0 after fees/funding/slippage.
- Profit factor >= 1.2.
- Expectancy > 0.
- Max drawdown within configured cap.
- No single market contributes more than 60% of net PnL unless explicitly marked as market-specific.
