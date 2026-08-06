# Anufriev Channel Strategy Economics v2

Дата: 2026-06-08  
Статус: research-only decision/economics layer. Не является инвестсоветом, торговой рекомендацией или юридической консультацией.  
Supersedes по coverage: `docs/analysis/2026-06-06-anufriev-strategy-decision-matrix.md`.

## 1. Что обновлено

Этот файл закрывает следующий слой долгой цели: не просто перечислить стратегии канала, а связать их с экономикой, доказательностью и текущим состоянием `trading_mvp`.

Authoritative local evidence:

| Evidence | Path | Current value |
|---|---|---:|
| Full channel catalog | `exports/youtube-anufriev/anufriev_video_catalog_20260606.csv` | 461 videos |
| Trading-relevant scorecard | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv` | 287 videos |
| Trading-relevant summary | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_summary_20260606.json` | 20,562,076 views |
| Transcript-backed union | `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json` | 77 unique videos |
| Metadata-only rows | same summary | 210 videos |
| Clean retry cards | `exports/youtube-anufriev/anufriev_transcript_retry_claim_cards_clean_20260606.jsonl` | 31 success, 1 rate-limit failure |
| Last retry blocker | `exports/youtube-anufriev/anufriev_transcript_retry_state_clean_20260606.json` | `HTTPError:429` on `gQ9f2fFnDn8` |
| Setup registry | `exports/trading-mvp/experiments/setup_registry.json` | 5 research-only setups |
| Experiment ledger | `exports/trading-mvp/experiments/experiment_ledger.jsonl` | hypothesis/result/verdict JSONL ledger |
| Fresh 6h maker grid | `exports/trading-mvp/backtests/ws_grid_search_signal_type_maker_quality_6h_20260608.json` | 472,583 events / 192 configs / 0 eligible |
| Funding quality backtest | `exports/trading-mvp/backtests/funding_backtest_quality_gate_20260606.json` | 41 markets / 0 trades |

External primary/reliable sources checked on 2026-06-08:

| Topic | Source | Project use |
|---|---|---|
| HFT/microstructure | SEC, `High Frequency Trading` market structure literature review: https://www.sec.gov/file/high-frequency-trading-market-structure | Confirms HFT/order-book dynamics are real research topics; does not prove retail profitability. |
| HFT liquidity nuance | FCA, `The role of High Frequency Traders in FX markets`: https://www.fca.org.uk/publications/research-articles-fca-research/role-high-frequency-traders-fx-markets-0 | Supports market-quality and regime filters; HFT behavior differs by market condition. |
| Spoofing / intent | CFTC Panther/Coscia spoofing action: https://www.cftc.gov/PressRoom/PressReleases/6649-13 | Spoofing exists, but code must detect observable events, not assert manipulative intent. |
| Perpetual derivatives risk | ESMA perpetual futures / CFD statement, 2026-02-24: https://www.esma.europa.eu/press-news/esma-news/esma-reminds-firms-their-obligations-under-cfd-product-intervention-measures | Perp replay can be researched; live leverage requires strict controls and risk warnings. |
| Day trading risk | FINRA Rule 2270: https://www.finra.org/rules-guidance/rulebooks/finra-rules/2270 | Reject "easy daily profit" framing; require costs, risk, capital and drawdown gates. |
| Day-trader base rate | Barber, Lee, Liu, Odean, SSRN 529063: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=529063 | Less than 1% predictably profitable net of fees in that study; use as base-rate warning, not impossibility proof. |
| Crypto venue risk | IOSCO FR11/23: https://www.iosco.org/library/pubdocs/pdf/IOSCOPD747.pdf | Venue, custody, conflicts, market-abuse and retail-risk checks are mandatory before live-like operation. |

## 2. Current proof state

| Requirement from objective | Current status | Evidence strength |
|---|---|---|
| Analyze maximum channel coverage | 461 full catalog, 287 trading-relevant metadata, 77 transcript-backed | Strong at map level, partial at transcript level |
| Identify strategy families | Achieved for major families | Strong |
| Compare participants | Conservative participant matrix exists, but many rows metadata-heavy | Medium |
| Check truth against external sources | Achieved for main claim families | Strong for risk framing, weak for individual profit stories |
| Compare with `trading_mvp` | Fresh 6h maker grid and funding backtest available | Strong |
| Economic model | This v2 document adds branch-level economics | Medium; precise ROI needs future paper-forward/live infra assumptions |
| Conclude highest-viability path | Perp replay + sweep/reversal + quality/fill + ledger | Strong as research roadmap, unproven as profitable trading |

The full goal is still not complete at video-by-video transcript level because YouTube timedtext access remains rate-limited. It is sufficient for the next engineering decision.

## 3. Strategy/economics matrix

| Rank | Strategy family | Channel signal | External truth check | Current `trading_mvp` evidence | Economic model | Decision |
|---:|---|---|---|---|---|---|
| 1 | Perp long/short microstructure | Futures, prop, stop cascades, market-maker narratives recur across channel clusters | ESMA flags complexity/risk; HFT sources support microstructure relevance, not profit | Spot replay has thousands of `short_disabled` signals: 9,301 for `flow_continue`, 8,542 for `fade_exhaustion` | Revenue from long/short micro-moves; costs are fees, funding, slippage, liquidation risk, venue risk | Build next as research-only |
| 2 | Market-quality + fill probability | Risk/playbook and order-book guests emphasize selecting right market/session | FCA HFT work supports regime-dependent liquidity; FINRA supports cost/risk caution | Maker skips are material: entry/exit expirations and quality-filter skips appear in 6h grid | Not alpha itself; increases expected value by blocking bad regimes | Mandatory gating layer |
| 3 | Liquidity sweep / reversal | Stop-loss hunting and forced cascade narratives appear in channel | CFTC confirms spoofing exists but intent requires evidence; observable sweep features are acceptable | Existing `fade_exhaustion` raises trades to 77 but remains negative EV | Potential edge if post-sweep adverse selection is controlled | Build after perp scaffold |
| 4 | Risk/playbook/process engine | Strong recurring theme: discipline, limits, setup database | FINRA/day-trading sources support hard risk disclosure and controls | Current project already benefits by rejecting failed grids before live | No direct revenue; prevents ruin and false deployment | Mandatory |
| 5 | Funding/basis carry | Funding/passive/arbitrage cluster exists | Funding/carry is real mechanism, but venue/basis/margin risk dominates | Quality-gated funding backtest: 41 markets, 0 trades | Revenue from funding payout plus basis convergence; capital/time intensive | Keep separate, multi-day horizon |
| 6 | AI trading / bots | AI/bots cluster is large and current | External sources do not validate autonomous AI alpha | Useful for tooling/classification, not signal proof | Productivity gain, not trading edge | Use as research automation only |
| 7 | News/event/regime filter | News/cycle/Polymarket cluster is smaller but relevant | Event volatility can matter; automation risks late/false signals | Not yet implemented | Improves selectivity if labels are timely and testable | Later as filter |
| 8 | High win-rate / deposit growth stories | 60 videos, high views, strong marketing pull | Barber/Odean and FINRA strongly warn on base rates and large-profit claims | Existing grids fail EV gates despite tuning | Negative if used as KPI; useful only as claims audit | Do not optimize for win-rate alone |
| 9 | P2P/airdrops/legal crypto | Older high-view cluster and legal episodes | IOSCO and regulatory sources support venue/legal risk concerns | Not aligned with current bot | Operational/counterparty edge, not HFT | Exclude from bot; keep as risk/compliance context |

## 4. Current project verdict from fresh 6h grid

Input: `exports/trading-mvp/backtests/ws_grid_search_signal_type_maker_quality_6h_20260608.json`.

Grid:
- events: 472,583
- combinations: 192
- eligible combinations: 0
- execution: maker/post-only
- queue model: `top_qty_fraction`
- quality filter: enabled
- signal types: `flow_continue`, `fade_exhaustion`

| Signal | Trades | Win rate | Net PnL quote | Expectancy | Profit factor | Main failure |
|---|---:|---:|---:|---:|---:|---|
| `flow_continue` | 45 | 42.22% | -0.206488 | -0.004589 | 0.7215 | Fails win-rate, expectancy, net PnL, PF |
| `fade_exhaustion` | 77 | 45.45% | -0.437481 | -0.005682 | 0.6483 | More trades, worse net EV |

Interpretation:

1. `fade_exhaustion` increases activity but does not improve economics.
2. Spot-only long replay is structurally narrow because short signals are blocked.
3. Maker simulation exposes fill-quality friction; expired entries/exits are not edge, they are cost/risk signals.
4. The channel's order-book ideas remain useful as hypotheses, but current implementation is not live-viable.

## 5. Economics by branch

| Branch | Setup cost | Operating cost | Capital need | Revenue mechanism | Main failure mode | Minimum proof before live-like paper |
|---|---:|---:|---:|---|---|---|
| Spot maker microstructure | Low; already built | Low data/storage | Low | Spread/micro-move capture | Negative EV after fills, no short side | Positive 24h+ replay across markets; current result fails |
| Perp microstructure | Medium; new schema/adapters/replay | Medium; perp WS/REST, funding, mark/index | Medium to high if live | Long/short micro-moves, liquidation/sweep response | Liquidation, funding drag, toxic fills, venue risk | 6-24h replay, then 3-7d paper-forward |
| Sweep/reversal signal | Medium; labeling and event features | Low to medium | Same as perp branch | Reversal after forced flow exhaustion | False sweeps and continuation against position | Out-of-sample PF >= 1.2 with fill/adverse-move metrics |
| Funding/basis carry | Medium; already v1 exists | Low frequency data, but longer horizon | Higher; symmetric spot/perp notional | Funding payout plus basis convergence | Basis widening, exchange/custody/margin risk | 7-30d backtest with positive net after all costs |
| Market-quality scheduler | Low to medium | Low | None by itself | Blocks negative-EV periods | Too strict, no trades | Improves expectancy without collapsing trade count |
| AI research layer | Low to medium | API/model cost if used | None | Faster analysis, monitoring, data labeling | Hallucinated signals and overfitting | AI outputs never bypass deterministic replay gates |
| News/regime layer | Medium | Data feed and labeling cost | None by itself | Better timing/selectivity | Late/false catalysts | Replay with/without regime labels shows lift after costs |

## 6. Required corrections to `trading_mvp`

Immediate:

1. Stop treating spot maker imbalance as the main path to live.
2. Keep current spot replay as a regression/sanity layer, not as the production strategy.
3. Extend `perp_replay` with real perp adapters/data before adding more spot-only indicators.
4. Convert "win-rate target" into an EV gate: net PnL, expectancy, PF, drawdown, trade count, fill probability.
5. Keep funding/basis as a separate carry engine; do not mix it into the intraday signal score.
6. Standardize on the experiment ledger so every channel-derived hypothesis has source, dataset, config, result, and verdict.
7. Add venue risk cards before any live-like phase: API reliability, fees, liquidation rules, withdrawal/custody risk, compliance restrictions.

Do not do:

1. Do not launch live orders.
2. Do not return to Binance testnet as a venue proxy.
3. Do not optimize for a high win-rate with negative expectancy.
4. Do not name the system HFT; current system is event-driven replay/paper research.
5. Do not write code that says "market maker manipulation" as a factual label. Use observable labels: sweep, cancel burst, depth imbalance, quote update burst, adverse move.

## 7. Acceptance gates for the next viable candidate

Research candidate:

- 6-24h replay minimum.
- At least 50 trades across more than one market, unless explicitly marked market-specific.
- Net PnL > 0 after fees, slippage, funding where applicable, and conservative fill assumptions.
- Profit factor >= 1.2.
- Expectancy > 0.
- Max drawdown inside configured cap.
- Per-market contribution visible.
- Skipped signal reasons and fill quality included.

Paper-forward candidate:

- 3-7 days paper-forward.
- API outage log.
- Fill probability and adverse move after fill.
- Daily loss cap.
- Kill switch.
- Position and venue exposure limits.
- No live keys required during validation.

## 8. Next engineering action

`perp_replay` scaffold is implemented and the first public REST `perp-collect` path now feeds it real MEXC/Gate perp fields. The next research step is to run 6-24h collection on MEXC/Gate and then replay/grid-search that dataset.

Concrete scope:

1. Run `perp-collect` for 6-24h on MEXC/Gate no-Binance universe candidates.
2. Keep normalized schema: `exchange`, `symbol`, `event_kind`, bid/ask, trade side/qty/price, mark price, index price, funding rate, open interest where available.
3. Reuse `StrategyConfig.signal_type`.
4. Default `allow_short=True` only for perp replay, not spot.
5. Account for maker/taker fees, funding, slippage, mark/index based liquidation approximation, and force-end close.
6. Run the same `flow_continue` and `fade_exhaustion` grids on the real perp dataset.
7. If still negative, add `liquidity_sweep_reversal` rather than loosening eligibility gates.

Why this is the right next step:

- It follows the most transferable channel themes: derivatives, stop cascades, market structure, playbook.
- It directly addresses the strongest current limitation: short side is disabled in spot.
- It remains research-only and avoids live risk.
- It can falsify or validate channel claims with measurable artifacts.

## 9. Current conclusion

The best current model is not "high win-rate bot". The defensible model is:

`perp long/short replay + sweep/reversal signal family + market-quality/fill-probability gate + experiment ledger + separate funding carry engine`

Expected viability today:

- Spot maker bot: low; current evidence is negative.
- Funding short-horizon engine: low as HFT substitute; medium as longer-horizon carry research.
- AI autonomous trader: low as execution edge; high as research tooling.
- Perp microstructure replay: highest research priority, but profitability unproven.

This keeps the project aligned with the useful parts of the channel while rejecting the unsafe parts: marketing win-rate, unverified deposit-growth stories, intent narratives, and live trading before replay/paper proof.
