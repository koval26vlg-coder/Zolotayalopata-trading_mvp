"""C9 BREAKOUT_TREND_4H -- independent verifier re-implementation (written from SPEC2.md only).

Producer's earlier verify files were preserved as *_producer_backup.* (not read by this script/author).

Rule (SPEC2 C9): BTCUSDT, ETHUSDT, SOLUSDT 4h Binance spot. Each asset its own 1/3 sleeve, no cross-sleeve rebalance.
  Entry: close_t > max(high over the prior 55 bars t-55..t-1).
  Exit : close_t < min(low  over the prior 20 bars t-20..t-1).
  Signal on closed bar t -> execution at open of bar t+1. 100% sleeve while long. Spot, no leverage.
Costs: 20 bps per side (stress 40 bps). Benchmark: equal-weight 1/3 buy&hold BTC/ETH/SOL, same costs
  (SOL sleeve in cash until its first bar). MaxDD on daily UTC marks.
Periods: IS = start..2022-12-31, OOS = 2023-01-01..2026-10-06, FULL = whole. Each period fresh capital.
"""
import json
import sys
import hashlib
import numpy as np
import pandas as pd

BASE = "C:/Users/koval/AppData/Local/Temp/claude/C--Users-koval------------/c3d42fa1-b83c-49f0-8567-13ebcd1f7317/scratchpad/st/C9"
FILES = {
    "BTC": ("BTCUSDT_4h_binance_spot.csv", "017e67da6049ecae90a61f888312e224955c7372e7efbe7de25d7cc52dbfea6d"),
    "ETH": ("ETHUSDT_4h_binance_spot.csv", "e6a1ef2380d590d264d48cb9dfd019affbea0fba1818b1ee453987f6c0d7672f"),
    "SOL": ("SOLUSDT_4h_binance_spot.csv", "34a429e1518a02f000812f833a9afb446248959275811af757b4f8dda172db18"),
}
H_N, L_N = 55, 20
LAST_CLOSE_MS = int(pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC").value // 10**6)
IS_END = pd.Timestamp("2023-01-01", tz="UTC")       # exclusive (bar open time)
OOS_START = IS_END
END = pd.Timestamp("2026-10-07", tz="UTC")          # exclusive


def load(asset):
    fn, sha = FILES[asset]
    p = f"{BASE}/data/{fn}"
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert h == sha, (asset, h)
    d = pd.read_csv(p)
    d = d[d["close_time"] <= LAST_CLOSE_MS].copy()
    d["t"] = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    d = d.sort_values("t").drop_duplicates("t").reset_index(drop=True)
    for k in ["open", "high", "low", "close"]:
        d[k] = d[k].astype(float)
    # sanity
    assert (d["high"] >= d[["open", "close", "low"]].max(axis=1) - 1e-12).all()
    assert (d["low"] <= d[["open", "close", "high"]].min(axis=1) + 1e-12).all()
    return d


def desired_state(d):
    """Desired position (0/1) decided at close of each bar, using only bars <= t."""
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    n = len(d)
    st = np.zeros(n, dtype=int)
    pos = 0
    for t in range(n):
        if pos == 0:
            if t >= H_N and cl[t] > hi[t - H_N:t].max():
                pos = 1
        else:
            if t >= L_N and cl[t] < lo[t - L_N:t].min():
                pos = 0
        st[t] = pos
    return st


def run_period(data, states, start, end, cost):
    """Run strategy + benchmark for [start, end) with fresh 1/3 sleeves.
    Position held during bar i = desired state at close of bar i-1 (executed at open of bar i).
    Within the period: a position is only opened by an execution inside the period (no inherited position);
    an open position at the period end is closed at the last close (with cost)."""
    sleeves = {}
    trades = []
    for a, d in data.items():
        m = (d["t"] >= start) & (d["t"] < end)
        idx = np.where(m.values)[0]
        if len(idx) == 0:
            sleeves[a] = None
            continue
        o, c = d["open"].values, d["close"].values
        st = states[a]
        cash, units, inpos = 1.0 / 3, 0.0, False
        eq = np.empty(len(idx))
        held = np.zeros(len(idx), dtype=bool)
        ent = None
        for k, i in enumerate(idx):
            want = st[i - 1] if i >= 1 else 0
            # execution at open of bar i
            if k == 0:
                # fresh start: do not inherit a position from before the period;
                # only enter on a signal that fires at the close of a bar inside the period
                want_exec = 0
            else:
                want_exec = want
            if want_exec == 1 and not inpos:
                units = cash * (1 - cost) / o[i]
                ent = (i, o[i], cash)
                cash = 0.0
                inpos = True
            elif want_exec == 0 and inpos:
                cash = units * o[i] * (1 - cost)
                trades.append(dict(asset=a, sig_entry_t=d["t"].iloc[ent[0] - 1], entry_t=d["t"].iloc[ent[0]], entry_px=ent[1],
                                   sig_exit_t=d["t"].iloc[i - 1], exit_t=d["t"].iloc[i], exit_px=o[i], forced=False,
                                   pnl=cash - ent[2], ret=cash / ent[2] - 1))
                units = 0.0
                inpos = False
            held[k] = inpos
            eq[k] = cash + units * c[i]
        if inpos:  # forced close at last close of the period
            i = idx[-1]
            cash = units * c[i] * (1 - cost)
            trades.append(dict(asset=a, sig_entry_t=d["t"].iloc[ent[0] - 1], entry_t=d["t"].iloc[ent[0]], entry_px=ent[1],
                               sig_exit_t=pd.NaT, exit_t=d["t"].iloc[i] + pd.Timedelta(hours=4), exit_px=c[i], forced=True,
                               pnl=cash - ent[2], ret=cash / ent[2] - 1))
            eq[-1] = cash
        # benchmark sleeve: buy at first open, sell at last close
        bu = (1.0 / 3) * (1 - cost) / o[idx[0]]
        beq = bu * c[idx]
        beq[-1] = beq[-1] * (1 - cost)
        sleeves[a] = dict(t=d["t"].values[idx], eq=eq, held=held, beq=beq)

    # union timeline of bars in the period
    allt = sorted(set().union(*[set(pd.to_datetime(s["t"], utc=True)) for s in sleeves.values() if s is not None]))
    T = pd.DatetimeIndex(allt)
    tot = pd.Series(0.0, index=T)
    btot = pd.Series(0.0, index=T)
    expo = pd.Series(0.0, index=T)
    for a, s in sleeves.items():
        if s is None:
            tot += 1.0 / 3
            btot += 1.0 / 3
            continue
        se = pd.Series(s["eq"], index=pd.to_datetime(s["t"], utc=True)).reindex(T).ffill().fillna(1.0 / 3)
        sb = pd.Series(s["beq"], index=pd.to_datetime(s["t"], utc=True)).reindex(T).ffill().fillna(1.0 / 3)
        sh = pd.Series(s["held"].astype(float), index=pd.to_datetime(s["t"], utc=True)).reindex(T).ffill().fillna(0.0)
        tot += se
        btot += sb
        expo += sh / 3
    return tot, btot, expo, pd.DataFrame(trades)


def daily_dd(eq_bar_close):
    # eq indexed by bar OPEN time; value is at bar close. Daily mark = last bar of each UTC day (close at 24:00).
    s = eq_bar_close.copy()
    s.index = s.index + pd.Timedelta(hours=4)  # close time
    daily = s.groupby((s.index - pd.Timedelta(milliseconds=1)).floor("D")).last()
    daily = pd.concat([pd.Series([1.0]), daily.reset_index(drop=True)])
    peak = daily.cummax()
    return float((daily / peak - 1).min() * 100)


def metrics(tot, btot, expo, tr, start_t, end_t):
    years = (end_t - start_t).total_seconds() / (365.25 * 86400)
    R = tot.iloc[-1] - 1
    BR = btot.iloc[-1] - 1
    out = dict(trades=int(len(tr)))
    if len(tr):
        w = tr["pnl"] > 0
        out["win_rate_pct"] = round(100 * w.mean(), 2)
        out["pf"] = round(tr.loc[w, "pnl"].sum() / -tr.loc[~w, "pnl"].sum(), 3)
        wr = tr["ret"] > 0
        out["pf_pct_based"] = round(tr.loc[wr, "ret"].sum() / -tr.loc[~wr, "ret"].sum(), 3)
    out["net_return_pct"] = round(100 * R, 2)
    out["cagr_pct"] = round(100 * ((1 + R) ** (1 / years) - 1), 2)
    out["max_dd_pct"] = round(daily_dd(tot), 2)
    out["exposure_pct"] = round(100 * expo.mean(), 2)
    out["bench_net_return_pct"] = round(100 * BR, 2)
    out["bench_cagr_pct"] = round(100 * ((1 + BR) ** (1 / years) - 1), 2)
    out["bench_max_dd_pct"] = round(daily_dd(btot), 2)
    out["years"] = round(years, 3)
    return out


def main():
    data = {a: load(a) for a in FILES}
    states = {a: desired_state(d) for a, d in data.items()}
    # look-ahead check: truncating future data must not change past states
    for a, d in data.items():
        for cut in [3000, 9000, len(d) - 500]:
            st2 = desired_state(d.iloc[:cut].reset_index(drop=True))
            assert (st2 == states[a][:cut]).all(), (a, cut)
    first = min(d["t"].iloc[0] for d in data.values())
    periods = {"IS": (first, IS_END), "OOS": (OOS_START, END), "FULL": (first, END)}
    res = {}
    alltr = {}
    for name, (s, e) in periods.items():
        tot, btot, expo, tr = run_period(data, states, s, e, 0.002)
        tot2, _, _, tr2 = run_period(data, states, s, e, 0.004)
        start_t = max(s, first)
        end_t = min(e, max(d["t"].iloc[-1] for d in data.values()) + pd.Timedelta(hours=4))
        m = metrics(tot, btot, expo, tr, start_t, end_t)
        m["net_return_2x_cost_pct"] = round(100 * (tot2.iloc[-1] - 1), 2)
        w2 = tr2["pnl"] > 0
        m["pf_2x"] = round(tr2.loc[w2, "pnl"].sum() / -tr2.loc[~w2, "pnl"].sum(), 3)
        m["forced_closes"] = int(tr["forced"].sum())
        m["pf_by_asset"] = {a: round(g.loc[g.pnl > 0, "pnl"].sum() / -g.loc[g.pnl <= 0, "pnl"].sum(), 3)
                            for a, g in tr.groupby("asset")}
        m["trades_by_asset"] = tr.groupby("asset").size().to_dict()
        m["return_over_maxdd"] = round(m["net_return_pct"] / -m["max_dd_pct"], 3)
        m["bench_return_over_maxdd"] = round(m["bench_net_return_pct"] / -m["bench_max_dd_pct"], 3)
        res[name] = m
        alltr[name] = tr
    # state at OOS boundary
    for a, d in data.items():
        i = np.searchsorted(d["t"].values, np.datetime64(OOS_START.tz_convert(None)))
        res.setdefault("boundary", {})[a] = int(states[a][i - 1]) if i > 0 else None
    # all trades have signal bar strictly before execution bar
    for name, tr in alltr.items():
        assert (tr["sig_entry_t"] < tr["entry_t"]).all()
        ok = tr.dropna(subset=["sig_exit_t"])
        assert (ok["sig_exit_t"] < ok["exit_t"]).all()
    alltr["FULL"].to_csv(f"{BASE}/verify/verifier_trades_full.csv", index=False)
    json.dump(res, open(f"{BASE}/verify/verifier_result.json", "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
