# SPEC2 — test channel strategies on available public data (frozen 2026-10-07)

Principle (user directive): TEST strategies now on data that is already publicly downloadable in one shot.
Do NOT build collectors, do NOT wait for perfect data. Where exact data is missing, use the declared proxy and
label it. If a source fails, try ONE alternative public source; if still unavailable -> verdict NOT_TESTED with reason.
Parameters below are frozen. No tuning, no extra variants beyond those listed.

## Common rules
- Signals use only closed bars; execution at the NEXT bar open (or next day open for daily rules).
- Last usable data: bars closed on or before 2026-10-06 23:59 UTC.
- Periods: IS = data start .. 2022-12-31; OOS = 2023-01-01 .. 2026-10-06. FULL = both. If data starts after 2022,
  report FULL only and say so.
- Costs per side (fee + slippage): crypto spot 20 bps; crypto perp 10 bps per leg; US stocks 5 bps; DAX index CFD/fut
  proxy 3 bps; gold 5 bps; options see C11. Cost stress: 2x costs.
- Position sizing: no leverage unless stated. Fractional units allowed in the research math, but ALSO report
  "$100 feasibility": can this be done with $100 given real minimum order/contract sizes? (yes/no + why).
- Metrics: trades, win rate, profit factor (PF = gross wins / gross losses, net of costs), net return %, CAGR %,
  max drawdown % (equity, daily marks), exposure %, benchmark (stated per strategy) same metrics, 2x-cost net return.
  Separate IS / OOS / FULL.
- Verdict (pre-registered, apply mechanically on OOS; FULL if no OOS):
  - FAIL: OOS net return <= 0, or PF < 1.0, or worse than benchmark on BOTH return and max drawdown.
  - INCONCLUSIVE: fewer than 30 OOS trades (event/trade strategies), or proxy judged too weak.
  - PASS_CANDIDATE: net positive, PF >= 1.2 (trade strategies) or annualised net > 4% with max DD < 10% (carry/yield
    strategies), beats benchmark on return/maxDD ratio, and still net positive at 2x costs.
  PASS_CANDIDATE is NOT a trading permission; it means "worth paper/forward testing".

## Strategies (source in channel -> frozen rule)

C1 FUNDING_CARRY (Codex model 7; channel: фандинг/арбитраж). Binance BTCUSDT & ETHUSDT. Data: spot 8h klines
   (or 1h), perp funding history fapi/v1/fundingRate (from 2019-09/2019-11), perp klines.
   Rule per asset, each asset 50% of capital: position = long spot + short perp, equal notional; capital per asset
   split 50% spot / 50% perp margin (so notional = 50% of sleeve). Enter when trailing 3-day mean funding > 0.01% per
   8h; exit when trailing 3-day mean funding < 0. Funding received/paid on short perp at each settlement while in position.
   P&L = funding + (spot - perp price change, use closes) - costs (2 legs). Benchmark: cash 0%. Type: carry.

C2 FUNDING_OVERHEAT_FILTER (channel: Геворкян/Радченко "перегретые фандинги"). BTC spot long by default; go to USDT
   when trailing 7-day mean BTC funding > 0.03%/8h; re-enter BTC when trailing 7-day mean < 0.01%/8h. Evaluate daily
   at 00:00 UTC using funding settled before then. Benchmark: BTC buy&hold same period. Type: directional filter.

C3 CROSS_VENUE_FUNDING (Codex model 8). BTCUSDT perps Binance vs Bybit (Bybit v5/market/funding/history, public).
   Align settlements to 8h (if a venue settles more often, sum its funding within each 8h window). When trailing
   7-day mean spread (Bybit - Binance) > +0.01%/8h: short Bybit perp, long Binance perp (equal notional = 50% of capital,
   rest margin); reverse sign when spread < -0.01%; flat when |spread| < 0.003%. P&L = funding difference + price
   difference between venues (use 8h closes) - costs (2 legs). Benchmark: cash. Type: carry.

C5 FEAR_GREED_CONTRARIAN (channel: Михеев, индекс страха и жадности). alternative.me FGI daily (api.alternative.me/fng/?limit=0).
   Buy 100% BTC at next day open when FGI <= 20; sell to USDT at next day open when FGI >= 80. Start in USDT.
   Benchmark: BTC buy&hold from first FGI date. Type: directional.

C6 RELATIVE_STRENGTH_IN_SELLOFF (Codex model 1; channel: HAMAHA/Rast, 09–10.09). Universe frozen = Binance USDT spot
   pairs that had daily klines on 2020-01-01 among: ETH, BNB, XRP, ADA, DOGE, LTC, LINK, BCH, TRX, XLM, EOS, ATOM, XTZ,
   ETC, NEO, VET, ZEC, DASH, IOTA, ONT (survivorship bias: all still listed today — state this).
   Event: BTC 7-day return <= -10% at a daily close, and no open trade. Rank universe by (coin 7d return - BTC 7d return).
   Buy top 3 equal weight at next day open, hold 14 days, exit at open. Control (report): bottom 3 same timing, and
   BTC same timing. Benchmark: equal-weight universe buy&hold. Type: event.

C7 TREND_PULLBACK_4H (Codex model 2; channel: "откат к поддержке по старшему тренду"). BTCUSDT, ETHUSDT, SOLUSDT 4h spot.
   Trend: close > EMA200. Setup: bar low <= EMA50 and close > EMA50 and close > EMA200. Entry next bar open. Stop =
   lowest low of last 10 bars before entry. Take profit = entry + 2 x (entry - stop). Risk 1% of equity per trade,
   position notional capped at 100% equity; one position per asset; each asset its own 1/3 sleeve. Intrabar: if stop and
   TP both touched in one bar, assume stop first. Benchmark: equal-weight buy&hold of the 3. Type: trade.

C8 IMPULSE_PULLBACK_BREAKOUT_4H (Codex model 3; channel: Андреев волны, "импульс -> откат -> продолжение").
   Same assets/sleeves as C7. ATR(14). Impulse: (close_t - min(low over t-5..t)) >= 3 x ATR_t. Impulse high = max high
   t-5..t. Within next 12 bars a pullback must retrace >= 38.2% and <= 61.8% of impulse (low-based) without closing
   below impulse start low; entry on next-bar-open after a close > impulse high; stop = pullback low; TP = 3R;
   risk 1% per trade, cap 100% sleeve. Intrabar stop-first. Benchmark as C7. Type: trade.

C9 BREAKOUT_TREND_4H (Codex model 4 family; channel: trend following). Same assets/sleeves. Long when close > highest
   high of prior 55 bars; exit when close < lowest low of prior 20 bars. 100% sleeve when in position. Benchmark as C7. Type: trade.

C10 SPOT_GRID_WEEKLY (Codex model 14; channel: сетки/боты). BTCUSDT 1h. Each Monday 00:00 UTC: rebalance to 50% BTC /
   50% USDT at open (costs apply), set 7 levels at open x (1 + k x 1.5%), k = -3..+3 (center = open). Each level holds
   1/6 of the sleeve notional. When price (1h high/low) crosses a level upward, sell one unit at that level if BTC
   inventory allows; downward, buy one unit if USDT allows. One fill per level per crossing direction; re-arm after the
   opposite neighbor fills. Costs per fill. Mark at hourly closes. Benchmark: 50/50 BTC/USDT rebalanced weekly
   (no grid). Type: trade (count fills as trades; PF computed on round trips).

C11 CASH_SECURED_PUT_BTC (Codex model 12; channel: Иванов, продажа путов). Proxy (label clearly): Deribit DVOL index
   (public/get_volatility_index_data, BTC, daily, from 2021) as implied vol; underlying = Binance BTCUSDT close.
   Every Monday 08:00 UTC (use Monday open if intraday unavailable): sell 7-day European put, strike = 0.95 x spot,
   price with Black-76 (r=0) at IV = DVOL x 1.10 (put skew), then take 85% of model premium (bid haircut); fee =
   min(0.0003 x spot, 0.125 x premium). Collateral = strike in USDT (fully cash-secured, 1 contract notional = what
   collateral allows). Settle at expiry: payoff = max(0, strike - spot_expiry). Benchmark: cash 0% and BTC B&H.
   $100 feasibility: Deribit min contract 0.1 BTC -> state it. Type: carry/short vol (use trade metrics + PF).

C13 GOLD_MACD_TREND (Codex model 15; channel: Коннор Вудс). Gold daily: Yahoo chart API GC=F (range=max, interval=1d),
   fallback PAXGUSDT daily (Binance). Long when MACD(12,26,9) line > signal AND close > EMA220; else flat. Daily
   evaluation, next-day open execution. Benchmark: gold buy&hold. Type: trade.

C14 DAX_ORB (Codex model 16; channel: Коннор Вудс). ^GDAXI intraday from Yahoo chart API (interval=60m, max range
   available ~730d; if 5m available for more days use 60m anyway for consistency). Session 09:00–17:30 Europe/Berlin
   (handle DST). Range = first hourly bar (09:00–10:00) high/low. After that, first hourly close > range high -> long at
   next bar open; first close < range low -> short at next bar open; stop = opposite range boundary; exit at last bar
   close of session. Max one trade per day. Risk sizing: 100% notional. Benchmark: DAX buy&hold over same days. Type: trade.

C15A US_GAP_CONTINUATION / C15B US_GAP_FADE (Codex models 17/18; channel: HAMAHA 10.09).
   Universe frozen: AAPL MSFT AMZN GOOGL META NVDA TSLA JPM BAC XOM CVX JNJ PFE KO PEP WMT HD DIS INTC CSCO ORCL NFLX
   ADBE CRM AMD QCOM T VZ MRK BA (survivorship: current megacaps — state this). Yahoo daily OHLC, 2010-01-01..2026-10-06.
   Gap = open_t / close_{t-1} - 1. C15A: gap >= +2% -> buy open, sell close same day. C15B: gap >= +2% -> short open,
   cover close (proxy: ignore borrow cost, state it). Equal-weight across same-day signals, capital split equally.
   Benchmark: equal-weight universe buy&hold. Type: trade.

C16 AAVE_V3_USDC (Codex model 19; channel: Шашков, доход вне трейдинга). DefiLlama yields API: find Aave v3 USDC
   Ethereum pool and fetch daily APY history (yields.llama.fi/chart/<pool>). Net result on $100 and on $10,000:
   compounded APY minus gas for one deposit + one withdrawal (assume $5 total per round trip unless a sourced gas
   figure is used). Benchmark: 0% cash. Also report max single-day APY drop and any days with APY < 1%. Type: yield.

## Not tested (state reason in final report, do not attempt)
- Orderbook continuation/reclaim (Codex 5/6): no free historical L2 book; Codex already rejected live orderflow variants.
- Prefunded cross-venue spot dislocation (9) and basis convergence (10): Codex already rejected / covered by C1/C3.
- Long ATM put (11), bear put spread (13): skip, C11 covers option pricing proxy; long puts are hedges not edge.
- Wallet following (20): needs block-level DEX data (not one-shot downloadable).
- Elliott waves / Smart Money / AI: no causal specification (C8 is the closest objective proxy).
