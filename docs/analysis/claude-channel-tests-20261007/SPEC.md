# Frozen backtest spec v1 (2026-10-07) — low-time strategies for a $100 spot beginner

Purpose: educational historical comparison. NOT tuned. Parameters below are frozen before any result is seen.
Do not add, drop or retune strategies. Report every strategy, including bad ones.

## Data (all in this folder)
- BTCUSDT_1d.csv, ETHUSDT_1d.csv (Binance spot daily, from 2017-08-17), SOLUSDT_1d.csv (from 2020-08-11).
  Columns: open_time_utc_ms, open, high, low, close, volume, close_time_ms.
  DROP every row whose open_time is 2026-10-07 or later (incomplete candle). Last usable day = 2026-10-06.
- BTC_blockchaininfo_daily.csv (ts_utc_s, price_usd; daily average price since 2009). Use ONLY for the
  extended-history robustness run (from 2014-01-01), treating price_usd as both close and next open.

## Weekly bars
Build weekly bars from daily data: week = Monday 00:00 UTC .. Sunday close. Weekly close = Sunday daily close.
Signals are computed on the weekly close (Sunday) and executed at the NEXT daily open (Monday open).
Only include complete weeks.

## Execution and costs
- Start: $100 cash (USDT). Spot only, no leverage, no shorting, fractional units allowed.
- Every buy or sell: fee 0.10% + adverse slippage 0.10% (total 20 bps per side), applied to traded notional.
- Cash yield: 0% (primary). Sensitivity run: 4%/year on idle USDT, accrued daily.
- Equity marked daily at daily close.

## Periods
- FULL: first possible signal date .. 2026-10-06 (each strategy needs warm-up; start ALL strategies on the same
  date = first Monday on which every indicator for every BTC/ETH strategy is defined, so comparisons are fair).
- IS: start .. 2021-12-31; OOS: 2022-01-01 .. 2026-10-06 (restart with $100 at 2022-01-03 Monday open,
  with indicators warmed up from earlier data). No parameter changes between IS and OOS.
- Rolling starts: start with $100 every Monday from the common start; report the distribution of value after
  52, 104 and 156 weeks (median, 10th percentile, worst, % of starts below $100).

## Strategies (frozen)
- S0 BH_BTC: buy BTC with all cash at start, hold.
- S0b BH_ETH: same with ETH. S0c BH_SOL: same with SOL (own shorter window, report separately).
- S0d BH_50_50: 50% BTC / 50% ETH at start, no rebalancing.
- S1 DCA_BTC_52W: split $100 into 52 equal weekly buys (every Monday open) over the first 52 weeks, then hold.
  (For rolling starts, same: 52 buys from each start date.)
- S2 TREND_BTC_40W: each weekly close, if BTC weekly close > its 40-week simple moving average of weekly closes
  -> hold 100% BTC from next Monday open; else hold 100% USDT. (~10 min per week.)
- S3 DUAL_MOM_12W: each weekly close compute 12-week return (close_t / close_{t-12} - 1) for BTC and ETH.
  Pick the higher one; if its 12-week return > 0 hold 100% of it, else 100% USDT. Switch at next Monday open.
- S4 RSI_GATED_DCA_BTC: same 52-week budget schedule as S1 ($100/52 per week), but a weekly buy is executed only
  if BTC weekly RSI(14, Wilder) at the prior weekly close < 50; otherwise that week's amount stays in cash and is
  carried forward (it is spent on the next allowed week in addition to that week's amount). After week 52, any
  unspent cash continues to wait and is spent at the first allowed week. Never sell. (Channel idea: "копить кэш,
  покупать на дне по недельному RSI", formalised.)
- S5 TREND_PULLBACK_BTC: hold USDT by default. Enter 100% BTC at next Monday open when, at a weekly close,
  BTC close > 40W SMA AND weekly RSI(14) < 50 (pullback inside an up-trend). Exit to USDT at next Monday open when
  a weekly close < 40W SMA. (Formalisation of "откат к поддержке по старшему тренду".)
- S6 TREND_50_50_40W: apply S2's rule separately to BTC and to ETH, each sleeve 50% of starting capital,
  no cross-rebalancing.

## Pre-registered sensitivity (report only; never pick the best one)
- S2 with SMA length 30W and 50W; S3 with lookback 8W and 26W.
- 2x costs (40 bps per side) for all strategies.
- Cash yield 4%/yr for S2, S3, S5, S6.
- Extended BTC history from 2014 (blockchain.info) for S0, S1, S2, S4, S5.

## Required metrics per strategy and period
final value of $100, CAGR, max drawdown (daily equity), worst calendar year, % time in market,
number of trades (each buy or sell = 1), total fees+slippage paid ($), and weekly time burden (minutes, assume
10 min per weekly check, +5 min per trade). Rolling-start distributions as above.

## Look-ahead rules (must be respected and self-checked)
- Weekly signal uses only data up to that Sunday close; trade at Monday open.
- SMA/RSI computed only from past weekly closes inclusive of the signal week.
- No use of the incomplete 2026-10-07 candle.
