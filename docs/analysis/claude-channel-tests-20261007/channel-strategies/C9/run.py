# C9 BREAKOUT_TREND_4H -- frozen rule from SPEC2.md (2026-10-07)
# Assets: Binance spot BTCUSDT, ETHUSDT, SOLUSDT, 4h klines. Each asset = own 1/3 sleeve (no cross-sleeve rebalancing).
# Long when close_t > highest high of PRIOR 55 bars (t-55..t-1); exit when close_t < lowest low of PRIOR 20 bars.
# Signal on closed bar t, execution at open of bar t+1. 100% sleeve when in position. Costs 20 bps/side (2x = 40 bps).
# Benchmark: equal-weight (1/3 each) buy&hold of the 3, same sleeve logic (SOL sleeve in cash until SOL listing).
import os, sys, json, time, hashlib, urllib.request
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
END_MS = int(pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC").value // 10**6)  # last usable close
IS_START = pd.Timestamp("2000-01-01", tz="UTC")
IS_END = pd.Timestamp("2022-12-31 23:59:59.999", tz="UTC")
OOS_START = pd.Timestamp("2023-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC")
COST = 0.0020
N_ENTRY, N_EXIT = 55, 20
URL_T = "https://api.binance.com/api/v3/klines?symbol={s}&interval=4h&startTime={st}&endTime={et}&limit=1000"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qav", "trades", "tbb", "tbq", "ignore"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(sym):
    path = os.path.join(DATA, f"{sym}_4h_binance_spot.csv")
    if os.path.exists(path):
        return path
    rows, st = [], 0
    while True:
        url = URL_T.format(s=sym, st=st, et=END_MS)
        with urllib.request.urlopen(url, timeout=30) as r:
            chunk = json.loads(r.read().decode())
        if not chunk:
            break
        rows.extend(chunk)
        last_open = chunk[-1][0]
        if len(chunk) < 1000:
            break
        st = last_open + 1
        time.sleep(0.25)
    df = pd.DataFrame(rows, columns=COLS)
    df.to_csv(path, index=False)
    return path


def load(sym):
    path = download(sym)
    df = pd.read_csv(path)
    df = df.drop_duplicates("open_time").sort_values("open_time")
    df = df[df["close_time"] <= END_MS].reset_index(drop=True)
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    df["t_open"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["t_close"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df, path


def signals(df):
    """Target position after close of bar t (executed at open t+1). Uses only bars <= t."""
    hh = df["high"].shift(1).rolling(N_ENTRY, min_periods=N_ENTRY).max()   # prior 55 bars (t-55..t-1)
    ll = df["low"].shift(1).rolling(N_EXIT, min_periods=N_EXIT).min()      # prior 20 bars (t-20..t-1)
    entry = (df["close"] > hh).to_numpy()
    exitc = (df["close"] < ll).to_numpy()
    tgt = np.zeros(len(df), dtype=np.int8)
    inpos = 0
    for t in range(len(df)):
        if inpos == 0 and entry[t]:
            inpos = 1
        elif inpos == 1 and exitc[t]:
            inpos = 0
        tgt[t] = inpos
    return tgt, hh.to_numpy(), ll.to_numpy()


def sim_sleeve(df, tgt, i0, i1, cap, cost, sym):
    """Simulate one sleeve on bars i0..i1 (inclusive). Holding during bar i = tgt[i-1] (decided at close of i-1).
    Returns per-bar equity at bar close (index i0..i1), per-bar invested flag, trade list. Liquidate at close i1."""
    o = df["open"].to_numpy(); c = df["close"].to_numpy()
    cash, units = cap, 0.0
    eq = np.empty(i1 - i0 + 1); inv = np.zeros(i1 - i0 + 1)
    trades, cur = [], None
    for k, i in enumerate(range(i0, i1 + 1)):
        want = int(tgt[i - 1]) if i >= 1 else 0
        if want == 1 and units == 0.0:
            spent = cash
            units = cash * (1 - cost) / o[i]; cash = 0.0
            cur = dict(asset=sym, signal_idx=i - 1, exec_idx=i, signal_time=str(df["t_close"].iat[i - 1]),
                       entry_time=str(df["t_open"].iat[i]), entry_px=o[i], spent=spent,
                       carried_in=bool(i == i0))
        elif want == 0 and units > 0.0:
            cash = units * o[i] * (1 - cost); units = 0.0
            cur.update(exit_signal_idx=i - 1, exit_idx=i, exit_time=str(df["t_open"].iat[i]), exit_px=o[i],
                       pnl=cash - cur["spent"], ret=cash / cur["spent"] - 1, forced_end=False)
            trades.append(cur); cur = None
        eq[k] = cash + units * c[i]
        inv[k] = 1.0 if units > 0 else 0.0
    if units > 0.0:  # liquidate at last close of period (with cost)
        cash = units * c[i1] * (1 - cost); units = 0.0
        cur.update(exit_signal_idx=i1, exit_idx=i1, exit_time=str(df["t_close"].iat[i1]), exit_px=c[i1],
                   pnl=cash - cur["spent"], ret=cash / cur["spent"] - 1, forced_end=True)
        trades.append(cur)
        eq[-1] = cash
    return eq, inv, trades


def sim_bh(df, i0, i1, cap, cost):
    o = df["open"].to_numpy(); c = df["close"].to_numpy()
    units = cap * (1 - cost) / o[i0]
    eq = units * c[i0:i1 + 1]
    eq = eq.copy(); eq[-1] = units * c[i1] * (1 - cost)
    return eq


def period_idx(df, p0, p1):
    m = (df["t_open"] >= p0) & (df["t_close"] <= p1)
    idx = np.flatnonzero(m.to_numpy())
    if len(idx) == 0:
        return None
    return int(idx[0]), int(idx[-1])


def metrics_from_equity(series, start_val):
    """series: pd.Series of equity indexed by bar-close time. Daily marks for maxDD."""
    daily = series.resample("1D").last().dropna()
    daily = pd.concat([pd.Series([start_val], index=[series.index[0] - pd.Timedelta(hours=4)]), daily])
    dd = daily / daily.cummax() - 1
    t0 = series.index[0] - pd.Timedelta(hours=4); t1 = series.index[-1]
    yrs = (t1 - t0).total_seconds() / (365.25 * 86400)
    ret = series.iloc[-1] / start_val - 1
    cagr = (series.iloc[-1] / start_val) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    return ret * 100, cagr * 100, dd.min() * 100, yrs


def run_period(data, p0, p1, cost, cap_total=100.0):
    cap = cap_total / 3.0
    sleeves, invs, bh, all_trades = {}, {}, {}, []
    first_t, last_t = None, None
    for sym, (df, tgt) in data.items():
        r = period_idx(df, p0, p1)
        if r is None:
            continue
        i0, i1 = r
        eq, inv, tr = sim_sleeve(df, tgt, i0, i1, cap, cost, sym)
        idx = df["t_close"].iloc[i0:i1 + 1].to_numpy()
        sleeves[sym] = pd.Series(eq, index=pd.DatetimeIndex(idx))
        invs[sym] = pd.Series(inv, index=pd.DatetimeIndex(idx))
        bh[sym] = pd.Series(sim_bh(df, i0, i1, cap, cost), index=pd.DatetimeIndex(idx))
        all_trades += tr
        ts0 = df["t_close"].iat[i0]; ts1 = df["t_close"].iat[i1]
        first_t = ts0 if first_t is None else min(first_t, ts0)
        last_t = ts1 if last_t is None else max(last_t, ts1)
    grid = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in sleeves.values()])))
    tot = pd.Series(0.0, index=grid); totbh = pd.Series(0.0, index=grid); invval = pd.Series(0.0, index=grid)
    for sym in data:
        if sym not in sleeves:
            tot += cap; totbh += cap; continue
        s = sleeves[sym].reindex(grid).ffill()
        b = bh[sym].reindex(grid).ffill()
        iv = invs[sym].reindex(grid).ffill().fillna(0.0)
        s = s.fillna(cap); b = b.fillna(cap)   # before asset listing: sleeve sits in cash
        # after asset's last bar (should not happen except tiny gaps) ffill keeps value
        tot += s; totbh += b; invval += iv * s
    ret, cagr, mdd, yrs = metrics_from_equity(tot, cap_total)
    bret, bcagr, bmdd, _ = metrics_from_equity(totbh, cap_total)
    expo = float((invval / tot).mean() * 100)
    pnl = np.array([t["pnl"] for t in all_trades])
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl < 0].sum()
    pf = wins / losses if losses > 0 else np.nan
    wr = (pnl > 0).mean() * 100 if len(pnl) else np.nan
    return dict(ret=ret, cagr=cagr, mdd=mdd, yrs=yrs, bret=bret, bcagr=bcagr, bmdd=bmdd, expo=expo,
                trades=len(pnl), wr=wr, pf=pf, trade_list=all_trades, start=str(grid[0]), end=str(grid[-1]),
                n_forced=sum(t["forced_end"] for t in all_trades), n_carried=sum(t["carried_in"] for t in all_trades))


def self_checks(data, raw):
    out = {}
    rng = np.random.default_rng(7)
    # 1) indicator uses strictly prior bars
    ok_ind = True
    for sym, (df, tgt) in data.items():
        _, hh, ll = signals(df)
        for t in rng.integers(N_ENTRY + 1, len(df), 200):
            if not np.isclose(hh[t], df["high"].iloc[t - N_ENTRY:t].max()):
                ok_ind = False
            if not np.isclose(ll[t], df["low"].iloc[t - N_EXIT:t].min()):
                ok_ind = False
    out["indicator_prior_bars_only"] = ok_ind
    # 2) truncation invariance: targets computed on data cut at T equal full-history targets for t < T
    ok_tr = True
    for sym, (df, tgt) in data.items():
        for T in rng.integers(500, len(df) - 10, 5):
            tgt_cut, _, _ = signals(df.iloc[:T].reset_index(drop=True))
            if not np.array_equal(tgt_cut, tgt[:T]):
                ok_tr = False
    out["truncation_invariance"] = ok_tr
    # 3) every trade: signal bar < execution bar (entry and exit except forced end-of-period liquidation)
    ok_ord = True
    for t in raw:
        if not (t["signal_idx"] < t["exec_idx"]):
            ok_ord = False
        if not t["forced_end"] and not (t["exit_signal_idx"] < t["exit_idx"]):
            ok_ord = False
    out["signal_bar_before_execution_bar"] = ok_ord
    out["stop_first_intrabar"] = "N/A: no intrabar stops/targets, exits only on closed-bar signal at next open"
    return out


def main():
    data, srcs, quality = {}, [], {}
    for sym in SYMS:
        df, path = load(sym)
        tgt, _, _ = signals(df)
        data[sym] = (df, tgt)
        d = df["open_time"].diff().dropna()
        quality[sym] = dict(rows=len(df), gaps_gt_4h=int((d > 4 * 3600 * 1000).sum()),
                            max_gap_h=float(d.max() / 3.6e6),
                            ohlc_bad=int(((df["high"] < df[["open", "close"]].max(axis=1)) |
                                          (df["low"] > df[["open", "close"]].min(axis=1))).sum()))
        srcs.append(dict(name=f"Binance spot {sym} 4h klines (api/v3/klines)",
                         url=URL_T.format(s=sym, st="<paged>", et=END_MS),
                         start=str(df["t_open"].iat[0]), end=str(df["t_close"].iat[-1]),
                         rows=int(len(df)), sha256=sha256(path), file=path))
    periods = {"IS": (IS_START, IS_END), "OOS": (OOS_START, OOS_END), "FULL": (IS_START, OOS_END)}
    res = {}
    for name, (p0, p1) in periods.items():
        r1 = run_period(data, p0, p1, COST)
        r2 = run_period(data, p0, p1, 2 * COST)
        r1["ret_2x"] = r2["ret"]; r1["pf_2x"] = r2["pf"]; r1["cagr_2x"] = r2["cagr"]
        # per-asset breakdown
        per = {}
        for sym in SYMS:
            tl = [t for t in r1["trade_list"] if t["asset"] == sym]
            p = np.array([t["pnl"] for t in tl])
            per[sym] = dict(trades=len(tl), pnl=float(p.sum()) if len(p) else 0.0,
                            pf=float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else None,
                            win_rate=float((p > 0).mean() * 100) if len(p) else None)
        r1["per_asset"] = per
        res[name] = r1
    raw_full = res["FULL"]["trade_list"]
    checks = self_checks(data, raw_full + res["OOS"]["trade_list"] + res["IS"]["trade_list"])

    o = res["OOS"]
    ratio = o["ret"] / abs(o["mdd"]) if o["mdd"] < 0 else np.inf
    bratio = o["bret"] / abs(o["bmdd"]) if o["bmdd"] < 0 else np.inf
    fail = (o["ret"] <= 0) or (o["pf"] < 1.0) or ((o["ret"] < o["bret"]) and (o["mdd"] < o["bmdd"]))
    inconcl = o["trades"] < 30
    passc = (o["ret"] > 0) and (o["pf"] >= 1.2) and (ratio > bratio) and (o["ret_2x"] > 0)
    if fail:
        verdict = "FAIL"
    elif inconcl:
        verdict = "INCONCLUSIVE"
    elif passc:
        verdict = "PASS_CANDIDATE"
    else:
        verdict = "INCONCLUSIVE"
    vd = dict(verdict=verdict, oos_ret=o["ret"], oos_pf=o["pf"], oos_mdd=o["mdd"], bench_ret=o["bret"],
              bench_mdd=o["bmdd"], ratio=ratio, bench_ratio=bratio, oos_ret_2x=o["ret_2x"], oos_trades=o["trades"],
              fail_cond=bool(fail), inconclusive_cond=bool(inconcl), pass_cond=bool(passc))

    vd["rule_order"] = ("FAIL checked first, then INCONCLUSIVE(<30 OOS trades), then PASS_CANDIDATE; if neither FAIL "
                        "nor PASS conditions hold, the case is not covered by the rule -> reported as INCONCLUSIVE")
    notes = dict(
        method=("Continuous signal state on full history; each period simulated from fresh equal 1/3 sleeves; "
                "if state at period start is long, entry at first bar open of the period (carried_in); open position "
                "liquidated at last close of period with cost. Benchmark: 1/3 per asset bought at first open in period "
                "(SOL sleeve in cash until SOL listing 2020-08-11), sold at last close, 20 bps each side."),
        metrics="PF/win rate on $ P&L per round trip (entry by bar time); maxDD on daily (UTC) equity marks; "
                "exposure = mean invested share of total portfolio equity over 4h bars.",
        bias="Asset list (BTC/ETH/SOL) chosen ex post (survivors/winners); Binance spot only; no RUB->USDT spread, "
             "withdrawal fees or taxes.",
        feasibility_100usd=("Yes by order size: $33 per sleeve vs Binance spot min notional ~5 USDT, lot steps "
                            "0.00001 BTC / 0.0001 ETH / 0.001 SOL. Practical issues: execution right after each 4h "
                            "close (6x/day) needs alerts/bot; Binance not available to RF residents."))
    out = dict(strategy="C9 BREAKOUT_TREND_4H", data_sources=srcs, data_quality=quality, self_checks=checks,
               verdict=vd, notes=notes, periods={})
    for name, r in res.items():
        out["periods"][name] = {k: (float(v) if isinstance(v, (np.floating, float)) else v)
                                for k, v in r.items() if k != "trade_list"}
    with open(os.path.join(BASE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str, ensure_ascii=False)
    pd.DataFrame(raw_full).to_csv(os.path.join(BASE, "trades_full.csv"), index=False)
    print(json.dumps({k: out[k] for k in ["data_quality", "self_checks", "verdict"]}, indent=1, default=str))
    for name, r in out["periods"].items():
        print(name, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k != "per_asset"})
        print("  per-asset", r["per_asset"])


if __name__ == "__main__":
    main()
