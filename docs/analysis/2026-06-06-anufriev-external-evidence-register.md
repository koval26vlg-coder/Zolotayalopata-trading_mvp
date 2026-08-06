# External Evidence Register: Trading Claims, Market Microstructure, Day Trading Risk

Дата: 2026-06-06  
Статус: research-only source register. Не является инвестсоветом или юридической консультацией.

## 1. Purpose

Этот register связывает claim families из канала «Хедлайнеры | Никита Ануфриев» с внешними первичными/надежными источниками. Цель: отделить проверяемые market-structure факты от недоказанных обещаний доходности.

## 2. Evidence table

| Claim family from channel | External source | What it supports | What it does not support | Project implication |
|---|---|---|---|---|
| HFT/orderbook matters | SEC HFT literature review | HFT is a recognized market-structure topic; speed/order-book dynamics matter | Does not prove a retail/manual scalper can beat HFT | Keep L2/tape replay, but avoid calling bot "HFT" |
| HFT role is nuanced | FCA HFT in FX markets | HFT can affect liquidity and price discovery; effect varies by market/condition | Does not support simple "HFT is always enemy" narrative | Measure market quality empirically per venue/pair |
| Spoofing exists | CFTC Panther/Coscia spoofing action | Spoofing is real and illegal when orders are placed with intent to cancel | Does not prove every large/cancelled order is manipulation | Build observable liquidity-sweep features, not intent claims |
| Perpetual futures / CFDs are risky | ESMA 2026 perpetual futures / CFD statement | Perpetual derivatives may fall under CFD product intervention scope; investor protection concerns are active | Does not forbid research/backtest; does not prove perps are profitable | Perp replay is research-only; no live leverage without controls |
| Day trading is high-risk | FINRA Rule 2270 risk disclosure | Day trading can be extremely risky, expensive, and unsuitable for many investors | Does not prove nobody can day trade profitably | Require hard gates, risk limits, and no "easy daily income" language |
| Leveraged/intraday trading needs risk awareness | Investor.gov day trading risk note | Day trading is fast, speculative, often uses leverage/margin | Does not provide a strategy | Add risk disclosures and reject live trading until paper proof |
| Margin/day trading rules are operationally important | SEC margin rules for day trading bulletin | Pattern day trading/margin rules affect operational constraints | Does not directly govern crypto perps, but gives risk analogy | Track margin, liquidation, and venue rules for perps |
| Most day traders lose; a few may have skill | Barber, Lee, Liu, Odean research | Aggregate day-trader performance is negative; only a small minority is predictably profitable | Does not prove every strategy is doomed | Optimize for out-of-sample expectancy, not win-rate stories |
| Crypto venues have market integrity and conflict risks | IOSCO crypto/digital asset recommendations | Crypto intermediaries raise investor protection, market abuse, custody, conflict, and retail distribution risks | Does not rank specific exchanges | Add venue risk cards and compliance layer |

## 3. Source notes and links

### SEC: high-frequency trading literature review

Source: https://www.sec.gov/file/high-frequency-trading-market-structure  
Direct PDF: https://www.sec.gov/marketstructure/research/hft_lit_review_march_2014.pdf

Use in audit:
- Supports treating HFT/microstructure as a real research area.
- Does not validate marketing claims such as "manual scalper has 90% win-rate because of HFT patterns".

### FCA: role of high-frequency traders in FX markets

Source: https://www.fca.org.uk/publications/research-articles/role-high-frequency-traders-fx-markets

Use in audit:
- Supports a nuanced view: HFT's role differs across liquidity regimes and participants.
- Reinforces need for `market_quality` and `fill_probability` metrics.

### CFTC: spoofing enforcement

Source: https://www.cftc.gov/PressRoom/PressReleases/6649-13

Use in audit:
- Supports that spoofing exists as a legally recognized form of market abuse.
- Does not allow us to infer intent from any single order-book pattern.
- Code should label observable events: sweep, cancel burst, depth imbalance, quote stuffing candidate, not "market maker hunting".

### ESMA: perpetual futures and CFD product intervention

Source: https://www.esma.europa.eu/press-news/esma-news/esma-reminds-firms-their-obligations-under-cfd-product-intervention-measures

Use in audit:
- Supports caution around leveraged crypto perpetuals.
- Perp replay is justified as a research path because spot-only limits the strategy space, but live perps are not justified until replay + forward-paper gates pass.

### FINRA: day-trading risk disclosure

Source: https://www.finra.org/rules-guidance/rulebooks/finra-rules/2270

Use in audit:
- Supports strict skepticism toward "easy daily profit" and "large profit" claims.
- Reinforces that trading costs can dominate high-frequency strategies.

### Investor.gov / SEC investor education

Sources:
- https://www.investor.gov/additional-resources/spotlight/formerdirectorlorischock-directors-take/thinking-day-trading-know-risks
- https://www.sec.gov/investor/alerts/daytrading.pdf

Use in audit:
- Supports operational risk controls for intraday/margin trading.
- Provides risk framing for beginner-facing claims on the channel.

### Barber, Lee, Liu, Odean: day trading skill

Sources:
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=529063
- https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf

Use in audit:
- Supports the base-rate view: most day traders are not predictably profitable; some skilled traders may exist.
- This maps directly to our acceptance gates: net PnL, expectancy, profit factor, out-of-sample stability.

### IOSCO: crypto and digital asset markets

Source: https://www.iosco.org/library/pubdocs/pdf/IOSCOPD747.pdf

Use in audit:
- Supports venue-risk and compliance concerns: market abuse, conflicts, custody, operational risk, retail distribution.
- Reinforces that `trading_mvp` needs venue risk cards before live-like operation.

## 4. Practical implications for trading_mvp

1. Use external sources as risk constraints, not as strategy proof.
2. Require replay evidence before accepting any channel strategy.
3. Replace intent-based labels with observable market features.
4. Treat perps as research-only until replay and paper-forward gates pass.
5. Keep funding/basis separate from microstructure scalping.
6. Treat high-winrate/deposit-growth videos as claims requiring source audit.
7. Add venue risk cards for MEXC, Gate, OKX, Bybit before any live-like stage.

## 5. Current verdict after external check

The most defensible project path remains:

1. `perp_replay`
2. `liquidity_sweep_reversal`
3. `market_quality + fill_probability`
4. experiment ledger
5. only then extended paper-forward runs

External evidence strengthens the no-live conclusion. It does not invalidate the channel as a hypothesis source; it invalidates using channel claims as proof of profitability.
