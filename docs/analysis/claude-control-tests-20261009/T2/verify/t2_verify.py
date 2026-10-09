# Independent re-implementation of SPEC3 T2 (rolling 3-year OOS-start windows).
# Written from SPEC.md / SPEC2.md / SPEC3.md and the prior strategy conventions; does NOT import T2/run.py
# and does NOT import prior_code modules (strategy logic re-coded here).
import json, glob, os, sys
from decimal import Decimal
import numpy as np
import pandas as pd

CTRL = sys.argv[1]
DATA = os.path.join(CTRL, "data")
OUT = os.path.join(CTRL, "T2", "verify")
C20, C40 = 0.002, 0.004
QSTARTS = list(pd.date_range("2018-07-01", "2023-07-01", freq="QS"))
assert len(QSTARTS) == 21
TIE = 0.01  # pp tolerance for maxDD tie


# ============================================================ weekly (SPEC: S1, S2, S6, B&H)
def load_daily_csv(sym):
    df = pd.read_csv(os.path.join(DATA, f"{sym}USDT_1d.csv"))
    df["d"] = pd.to_datetime(df["open_time_utc_ms"], unit="ms")
    df = df[df["d"] < pd.Timestamp("2026-10-07")].set_index("d")[["open", "close"]].astype(float)
    assert (df.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()
    return df

BTC = load_daily_csv("BTC"); ETH = load_daily_csv("ETH")
assert BTC.index.equals(ETH.index)

def trend_on(df, n=40):
    """Boolean Series indexed by Monday: weekly close (prior Sunday) > SMA_n of complete weekly closes."""
    sundays = df.index[df.index.weekday == 6]
    # complete week: Monday..Sunday all present (calendar is gap-free, so only the first partial week fails)
    comp = [s for s in sundays if (s - pd.Timedelta(days=6)) in df.index]
    wc = df.loc[comp, "close"]
    sm = wc.rolling(n, min_periods=n).mean()
    on = (wc > sm) & sm.notna()
    on.index = on.index + pd.Timedelta(days=1)
    defined = sm.notna(); defined.index = on.index
    return on, defined

ON_B, DEF_B = trend_on(BTC); ON_E, DEF_E = trend_on(ETH)

def sim_trend(df, on, defined, m0, m1_sun, cap, cost):
    days = df.loc[m0:m1_sun].index
    o = df["open"]; c = df["close"]
    cash, u = cap, 0.0
    eq = np.empty(len(days)); trips = []; spent = None; ntr = 0
    for i, d in enumerate(days):
        if d.weekday() == 0:
            assert defined.loc[d], f"SMA not warmed up at {d}"
            s = bool(on.loc[d])
            if s and u == 0.0:
                spent = cash; u = cash * (1 - cost) / o.loc[d]; cash = 0.0; ntr += 1
            elif (not s) and u > 0.0:
                cash = u * o.loc[d] * (1 - cost); trips.append(cash - spent); u = 0.0; ntr += 1
        eq[i] = cash + u * c.loc[d]
    if u > 0:  # open position valued at last close net of exit cost, for PF only
        trips.append(u * c.loc[days[-1]] * (1 - cost) - spent)
    return eq, trips, ntr, days

def sim_bh_w(dfs_w, m0, m1_sun, cost):
    eq = 0
    for df, cap in dfs_w:
        days = df.loc[m0:m1_sun].index
        u = cap * (1 - cost) / df.loc[m0, "open"]
        eq = eq + u * df.loc[days, "close"].to_numpy()
    return eq

def sim_dca(df, m0, m1_sun, cost):
    days = df.loc[m0:m1_sun].index
    cash, u, k = 100.0, 0.0, 0
    eq = np.empty(len(days))
    for i, d in enumerate(days):
        if d.weekday() == 0 and k < 52:
            amt = cash if k == 51 else 100.0 / 52
            u += amt * (1 - cost) / df.loc[d, "open"]; cash -= amt; k += 1
        eq[i] = cash + u * df.loc[d, "close"]
    return eq, k

def mets(eq, start_val, years):
    path = np.concatenate([[start_val], eq])
    mdd = (path / np.maximum.accumulate(path) - 1).min() * 100
    fin = eq[-1]
    net = (fin / start_val - 1) * 100
    cagr = ((fin / start_val) ** (1 / years) - 1) * 100
    return net, mdd, cagr

def pf_of(trips):
    t = np.array(trips)
    w = t[t > 0].sum(); l = -t[t <= 0].sum()
    if len(t) == 0: return None
    return float("inf") if l == 0 else w / l

def verdict(r, use_tradecount=False, pf_applicable=True):
    fail = (r["net"] <= 0) or (pf_applicable and r["pf"] is not None and r["pf"] < 1.0) or \
           ((r["net"] < r["b_net"]) and (r["mdd"] < r["b_mdd"] - TIE))
    if fail: return "FAIL"
    if use_tradecount and r["trades"] < 30: return "INCONCLUSIVE"
    pfok = (not pf_applicable) or (r["pf"] is not None and r["pf"] >= 1.2)
    ratio = r["net"] / abs(r["mdd"]); bratio = r["b_net"] / abs(r["b_mdd"])
    if r["net"] > 0 and pfok and ratio > bratio and r["net2x"] > 0: return "PASS_CANDIDATE"
    return "INCONCLUSIVE"

def verdict_strict_tie(r, **kw):
    """Alternative: a maxDD tie counts as 'not better' -> worse-on-both if net is also worse."""
    if (r["net"] < r["b_net"]) and (r["mdd"] <= r["b_mdd"] + TIE) and r["net"] > 0:
        return "FAIL"
    return verdict(r, **kw)

def add_ratios(r, years):
    r["ratio"] = r["net"] / abs(r["mdd"]); r["b_ratio"] = r["b_net"] / abs(r["b_mdd"])
    r["cagr_dd"] = r["cagr"] / abs(r["mdd"]); r["b_cagr_dd"] = r["b_cagr"] / abs(r["b_mdd"])
    return r

results = {}

def weekly_window(name, m0, m1):
    yrs = ((m1 - m0).days + 1) / 365.25
    out = {}
    for cost in (C20, C40):
        if name == "S1":
            eq, k = sim_dca(BTC, m0, m1, cost); trips = []; ntr = k
            beq = sim_bh_w([(BTC, 100.0)], m0, m1, cost)
        elif name == "S2":
            eq, trips, ntr, _ = sim_trend(BTC, ON_B, DEF_B, m0, m1, 100.0, cost)
            beq = sim_bh_w([(BTC, 100.0)], m0, m1, cost)
        else:
            e1, t1, n1, _ = sim_trend(BTC, ON_B, DEF_B, m0, m1, 50.0, cost)
            e2, t2, n2, _ = sim_trend(ETH, ON_E, DEF_E, m0, m1, 50.0, cost)
            eq = e1 + e2; trips = t1 + t2; ntr = n1 + n2
            beq = sim_bh_w([(BTC, 50.0), (ETH, 50.0)], m0, m1, cost)
        out[cost] = (eq, trips, ntr, beq)
    eq, trips, ntr, beq = out[C20]
    net, mdd, cagr = mets(eq, 100.0, yrs); bnet, bmdd, bcagr = mets(beq, 100.0, yrs)
    r = dict(start=str(m0.date()), end=str(m1.date()), net=net, mdd=mdd, cagr=cagr, b_net=bnet, b_mdd=bmdd,
             b_cagr=bcagr, net2x=(out[C40][0][-1] / 100 - 1) * 100, trades=ntr, pf=pf_of(trips))
    return add_ratios(r, yrs)

for name in ("S1", "S2", "S6"):
    rows = []
    for q in QSTARTS:
        m0 = q + pd.Timedelta(days=(7 - q.weekday()) % 7)
        m1 = m0 + pd.Timedelta(days=1091)
        r = weekly_window(name, m0, m1); r["q"] = str(q.date())
        r["V"] = verdict(r, pf_applicable=(name != "S1")); r["V_strict"] = verdict_strict_tie(r, pf_applicable=(name != "S1"))
        rows.append(r)
    ref = weekly_window(name, pd.Timestamp("2022-01-03"), pd.Timestamp("2026-10-06")); ref["q"] = "REF"
    ref["V"] = verdict(ref, pf_applicable=(name != "S1"))
    results[name] = dict(rows=rows, ref=ref)


# ============================================================ C5 (FGI contrarian)
fng = json.load(open(os.path.join(DATA, "C5", "fng.json")))["data"]
FGI = pd.Series({pd.to_datetime(int(x["timestamp"]), unit="s"): int(x["value"]) for x in fng}).sort_index()
FGI = FGI[FGI.index <= pd.Timestamp("2026-10-06")]
rows = []
for p in sorted(glob.glob(os.path.join(DATA, "C5", "btcusdt_1d_part*.json"))):
    rows += json.load(open(p))
K5 = pd.DataFrame([r[:5] for r in rows], columns=["ot", "open", "high", "low", "close"]).drop_duplicates("ot")
K5.index = pd.to_datetime(K5["ot"], unit="ms"); K5 = K5[["open", "close"]].astype(float).sort_index()
K5 = K5[K5.index <= pd.Timestamp("2026-10-06")]
# cross-check against the SPEC daily CSV
common = K5.index.intersection(BTC.index)
c5_vs_csv_maxdiff = float(np.abs(K5.loc[common, "close"] - BTC.loc[common, "close"]).max())

def c5_sim(d0, d1, cost, start_long=None):
    days = K5.loc[d0:d1].index
    cash, u, long_ = 1.0, 0.0, False
    trips, cin = [], None
    if start_long is not None and start_long:
        # continuous-state variant: buy at first open if the full-history state is long
        cin = cash; u = cash * (1 - cost) / K5.loc[days[0], "open"]; cash = 0.0; long_ = True
    eq = np.empty(len(days))
    for i, t in enumerate(days):
        sd = t - pd.Timedelta(days=1)
        if sd in FGI.index and not (start_long and i == 0 and long_ and FGI[sd] <= 20):
            v = FGI[sd]; o = K5.loc[t, "open"]
            if (not long_) and v <= 20:
                cin = cash; u = cash * (1 - cost) / o; cash = 0.0; long_ = True
            elif long_ and v >= 80:
                cash = u * o * (1 - cost); trips.append(cash - cin); u = 0.0; long_ = False
        eq[i] = cash + u * K5.loc[t, "close"]
    if long_:
        cash = u * K5.loc[days[-1], "close"] * (1 - cost); trips.append(cash - cin); eq[-1] = cash
    return eq, trips, days

def full_state_c5(at):
    """Position state of the continuous rule (from first FGI) on the evening before day `at`."""
    long_ = False
    for t in K5.loc[FGI.index[0]:at - pd.Timedelta(days=1)].index:
        sd = t - pd.Timedelta(days=1)
        if sd in FGI.index:
            v = FGI[sd]
            if (not long_) and v <= 20: long_ = True
            elif long_ and v >= 80: long_ = False
    return long_

def bh_daily(K, d0, d1, cost):
    days = K.loc[d0:d1].index
    u = (1 - cost) / K.loc[days[0], "open"]
    eq = u * K.loc[days, "close"].to_numpy(); eq = eq.copy(); eq[-1] *= (1 - cost)
    return eq

def daily_window(simf, K, d0, d1, **kw):
    eq, trips, days = simf(d0, d1, C20, **kw)
    eq2, _, _ = simf(d0, d1, C40, **kw)
    beq = bh_daily(K, d0, d1, C20)
    yrs = len(days) / 365.25
    net, mdd, cagr = mets(eq, 1.0, yrs); bnet, bmdd, bcagr = mets(beq, 1.0, yrs)
    r = dict(start=str(days[0].date()), end=str(days[-1].date()), net=net, mdd=mdd, cagr=cagr, b_net=bnet,
             b_mdd=bmdd, b_cagr=bcagr, net2x=(eq2[-1] - 1) * 100, trades=len(trips), pf=pf_of(trips))
    return add_ratios(r, yrs)

rows = []
for q in QSTARTS:
    d1 = q + pd.Timedelta(days=1094)
    r = daily_window(c5_sim, K5, q, d1); r["q"] = str(q.date())
    r["V"] = verdict(r); r["V_strict"] = verdict_strict_tie(r)
    st = full_state_c5(q)
    rc = daily_window(c5_sim, K5, q, d1, start_long=st)
    r["cont_state_long_at_start"] = st; r["cont_net"] = rc["net"]; r["cont_V"] = verdict(rc)
    rows.append(r)
ref = daily_window(c5_sim, K5, pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-06")); ref["q"] = "REF"; ref["V"] = verdict(ref)
results["C5"] = dict(rows=rows, ref=ref, c5_vs_csv_close_maxdiff=c5_vs_csv_maxdiff)


# ============================================================ C2 (funding overheat filter)
fu = pd.DataFrame(json.load(open(os.path.join(DATA, "C2", "binance_fapi_fundingRate_BTCUSDT.json"))))
fu["t"] = pd.to_datetime(fu["fundingTime"].astype("int64"), unit="ms")
fu["ri"] = fu["fundingRate"].map(lambda x: int(Decimal(x) * 10**8))
fu = fu.drop_duplicates("t").sort_values("t"); fu = fu[fu["t"] < pd.Timestamp("2026-10-07")]
kl = pd.DataFrame([r[:7] for r in json.load(open(os.path.join(DATA, "C2", "binance_spot_klines_BTCUSDT_1d.json")))],
                  columns=["ot", "open", "high", "low", "close", "v", "ct"])
kl.index = pd.to_datetime(kl["ot"].astype("int64"), unit="ms")
kl = kl[pd.to_datetime(kl["ct"].astype("int64"), unit="ms") < pd.Timestamp("2026-10-07")]
K2 = kl[["open", "close"]].astype(float)
K2 = K2[~K2.index.duplicated()].sort_index()
first_eval = (fu["t"].min() + pd.Timedelta(days=7)).ceil("D")
tt = fu["t"].to_numpy(); ri = fu["ri"].to_numpy()
cs = np.concatenate([[0], np.cumsum(ri)])
POS2 = {}
pos = 1
for D in K2.index[K2.index >= first_eval]:
    lo = np.searchsorted(tt, np.datetime64(D - pd.Timedelta(days=7)), "left")
    hi = np.searchsorted(tt, np.datetime64(D), "left")
    s = cs[hi] - cs[lo]
    if pos == 1 and s > 21 * 30000: pos = 0
    elif pos == 0 and s < 21 * 10000: pos = 1
    POS2[D] = pos
POS2 = pd.Series(POS2)

def c2_sim(d0, d1, cost, ones=False):
    days = K2.loc[d0:d1].index
    cash, u, cur, cin = 1.0, 0.0, 0, None
    eq = np.empty(len(days)); trips = []
    for i, D in enumerate(days):
        tgt = 1 if ones else int(POS2[D])
        if tgt != cur:
            o = K2.loc[D, "open"]
            if tgt == 1: cin = cash; u = cash * (1 - cost) / o; cash = 0.0
            else: cash = u * o * (1 - cost); trips.append(cash - cin); u = 0.0
            cur = tgt
        eq[i] = cash + u * K2.loc[D, "close"]
    if cur == 1:
        cash = u * K2.loc[days[-1], "close"] * (1 - cost); trips.append(cash - cin); eq[-1] = cash
    return eq, trips, days

rows = []; skipped = []
for q in QSTARTS:
    if q < first_eval:
        skipped.append(str(q.date())); continue
    d1 = q + pd.Timedelta(days=1094)
    r = daily_window(c2_sim, K2, q, d1); r["q"] = str(q.date())
    r["V"] = verdict(r); r["V_strict"] = verdict_strict_tie(r)
    rows.append(r)
ref = daily_window(c2_sim, K2, pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-06")); ref["q"] = "REF"; ref["V"] = verdict(ref)
results["C2"] = dict(rows=rows, ref=ref, skipped=skipped, first_eval=str(first_eval.date()))


# ============================================================ C9 (4h breakout, BTC/ETH/SOL sleeves)
END_MS = int(pd.Timestamp("2026-10-06 23:59:59.999").value // 10**6)
C9D = {}
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    df = pd.read_csv(os.path.join(DATA, "C9", f"{sym}_4h_binance_spot.csv"))
    df = df.drop_duplicates("open_time").sort_values("open_time")
    df = df[df["close_time"] <= END_MS].reset_index(drop=True)
    h = df["high"].to_numpy(float); l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    n = len(df)
    tgt = np.zeros(n, np.int8); st = 0
    for t in range(n):
        ent = t >= 55 and c[t] > h[t - 55:t].max()
        ex = t >= 20 and c[t] < l[t - 20:t].min()
        if st == 0 and ent: st = 1
        elif st == 1 and ex: st = 0
        tgt[t] = st
    C9D[sym] = dict(o=df["open"].to_numpy(float), c=c, to=df["open_time"].to_numpy(np.int64),
                    tc=df["close_time"].to_numpy(np.int64), tgt=tgt)

def c9_window(p0, p1, cost):
    cap = 100.0 / 3
    p0ms = int(p0.value // 10**6); p1ms = int(p1.value // 10**6)
    ser, bser, trips = [], [], []
    for sym, D in C9D.items():
        idx = np.flatnonzero((D["to"] >= p0ms) & (D["tc"] <= p1ms))
        if len(idx) == 0:
            continue
        i0, i1 = idx[0], idx[-1]
        cash, u, cin = cap, 0.0, None
        eq = np.empty(i1 - i0 + 1)
        for k, i in enumerate(range(i0, i1 + 1)):
            want = D["tgt"][i - 1] if i >= 1 else 0  # no wrap-around at listing bar
            if want == 1 and u == 0.0:
                cin = cash; u = cash * (1 - cost) / D["o"][i]; cash = 0.0
            elif want == 0 and u > 0.0:
                cash = u * D["o"][i] * (1 - cost); trips.append(cash - cin); u = 0.0
            eq[k] = cash + u * D["c"][i]
        if u > 0:
            cash = u * D["c"][i1] * (1 - cost); trips.append(cash - cin); eq[-1] = cash
        ix = pd.to_datetime(D["tc"][i0:i1 + 1], unit="ms")
        ser.append(pd.Series(eq, index=ix))
        bu = cap * (1 - cost) / D["o"][i0]
        be = bu * D["c"][i0:i1 + 1]; be = be.copy(); be[-1] *= (1 - cost)
        bser.append(pd.Series(be, index=ix))
    grid = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in ser])))
    tot = sum(s.reindex(grid).ffill().fillna(cap) for s in ser) + cap * (3 - len(ser))
    btot = sum(s.reindex(grid).ffill().fillna(cap) for s in bser) + cap * (3 - len(bser))
    def m(series):
        t0 = series.index[0] - pd.Timedelta(hours=4)
        daily = series.resample("1D").last().dropna()
        path = np.concatenate([[100.0], daily.to_numpy()])
        mdd = (path / np.maximum.accumulate(path) - 1).min() * 100
        yrs = (series.index[-1] - t0).total_seconds() / (365.25 * 86400)
        fin = series.iloc[-1]
        return (fin / 100 - 1) * 100, mdd, ((fin / 100) ** (1 / yrs) - 1) * 100
    net, mdd, cagr = m(tot); bnet, bmdd, bcagr = m(btot)
    return dict(net=net, mdd=mdd, cagr=cagr, b_net=bnet, b_mdd=bmdd, b_cagr=bcagr, trades=len(trips),
                pf=pf_of(trips), start=str(grid[0]), end=str(grid[-1]))

rows = []
for q in QSTARTS:
    p1 = q + pd.Timedelta(days=1095) - pd.Timedelta(milliseconds=1)
    r = c9_window(q, p1, C20); r["net2x"] = c9_window(q, p1, C40)["net"]; r["q"] = str(q.date())
    add_ratios(r, None); r["V"] = verdict(r, use_tradecount=True); r["V_strict"] = verdict_strict_tie(r, use_tradecount=True)
    rows.append(r)
ref = c9_window(pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-06 23:59:59.999"), C20)
ref["net2x"] = c9_window(pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-06 23:59:59.999"), C40)["net"]
add_ratios(ref, None); ref["q"] = "REF"; ref["V"] = verdict(ref, use_tradecount=True)
results["C9"] = dict(rows=rows, ref=ref)


# ============================================================ summaries
def summ(rows):
    n = len(rows)
    sh = lambda f: round(100 * sum(f(r) for r in rows) / n, 1)
    vc = {k: sum(r["V"] == k for r in rows) for k in ("PASS_CANDIDATE", "INCONCLUSIVE", "FAIL")}
    vcs = {k: sum(r["V_strict"] == k for r in rows) for k in ("PASS_CANDIDATE", "INCONCLUSIVE", "FAIL")}
    w = min(rows, key=lambda r: r["net"])
    return dict(n=n, beats_net=sh(lambda r: r["net"] > r["b_net"]),
                beats_dd=sh(lambda r: r["mdd"] > r["b_mdd"] + TIE),
                dd_ties=sum(abs(r["mdd"] - r["b_mdd"]) <= TIE for r in rows),
                beats_ratio=sh(lambda r: r["ratio"] > r["b_ratio"]),
                beats_cagr_dd=sh(lambda r: r["cagr_dd"] > r["b_cagr_dd"]),
                worst_net=round(w["net"], 2), worst_q=w["q"], bh_worst=round(min(r["b_net"] for r in rows), 2),
                med_net=round(float(np.median([r["net"] for r in rows])), 2),
                bh_med_net=round(float(np.median([r["b_net"] for r in rows])), 2),
                med_dd=round(float(np.median([r["mdd"] for r in rows])), 2),
                bh_med_dd=round(float(np.median([r["b_mdd"] for r in rows])), 2),
                verdicts=vc, verdicts_strict_tie=vcs,
                survivor_rule_gt50pass_0fail=bool(vc["PASS_CANDIDATE"] / n > 0.5 and vc["FAIL"] == 0))

summary = {k: summ(v["rows"]) for k, v in results.items()}
for k, v in results.items():
    v["summary"] = summary[k]

def clean(o):
    if isinstance(o, dict): return {a: clean(b) for a, b in o.items()}
    if isinstance(o, list): return [clean(b) for b in o]
    if isinstance(o, (np.floating, float)):
        o = float(o); return "inf" if o == float("inf") else round(o, 4)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    return o
json.dump(clean(results), open(os.path.join(OUT, "verify_result.json"), "w"), indent=1)
print(json.dumps(clean(summary), indent=1))
