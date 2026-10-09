# Independent verifier for T3 (SPEC3). Written without reading ctrl/T3/run.py.
# Strategy equity series come from the unchanged prior code (reproduced in verify/repro, exact match to prior results).
import json, os, sys, math, importlib.util
import numpy as np
import pandas as pd

V = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.abspath(os.path.join(V, "..", ".."))
REPRO = os.path.join(V, "repro")

# ---------------- T-bill ----------------
fr = pd.read_csv(os.path.join(V, "fred_dl", "DTB3.csv"))
fr.columns = ["date", "d"]
fr["date"] = pd.to_datetime(fr["date"])
fr["d"] = pd.to_numeric(fr["d"], errors="coerce")
obs = fr.dropna().set_index("date")["d"] / 100.0
assert obs.index.is_monotonic_increasing

cal = pd.date_range("2018-12-01", "2026-10-10", freq="D")
# rate in force for calendar day D = last observation with date <= D-1 (no look-ahead), or <= D (same-day variant)
d_lag1 = obs.reindex(cal.union(obs.index)).ffill().reindex(cal - pd.Timedelta(days=1)).values
d_same = obs.reindex(cal.union(obs.index)).ffill().reindex(cal).values
d_lag1 = pd.Series(d_lag1, index=cal)
d_same = pd.Series(d_same, index=cal)

def bey(d):
    return 365.0 * d / (360.0 - 91.0 * d)

FALLBACK = {2018: 2.1, 2019: 2.1, 2020: 0.4, 2021: 0.05, 2022: 2.0, 2023: 5.0, 2024: 5.0, 2025: 4.2, 2026: 3.8}

def daily_log(conv):
    """log growth per calendar day for each calendar day in cal."""
    if conv == "bey_lag1":
        y = bey(d_lag1)
        return np.log1p(y / 365.0)
    if conv == "bey_same":
        y = bey(d_same)
        return np.log1p(y / 365.0)
    if conv == "disc_365":
        return np.log1p(d_lag1 / 365.0)
    if conv == "disc_360":
        return np.log1p(d_lag1 / 360.0)
    if conv == "bey_cont":            # treat BEY as continuously compounded (slightly higher)
        return bey(d_lag1) / 365.0
    if conv == "fallback":
        y = pd.Series([FALLBACK[t.year] / 100.0 for t in cal], index=cal)
        return np.log1p(y / 365.0)
    raise ValueError(conv)

CONVS = ["bey_lag1", "bey_same", "disc_365", "disc_360", "bey_cont", "fallback"]
DL = {c: daily_log(c) for c in CONVS}
CUM = {c: pd.Series(np.concatenate([[0.0], np.cumsum(DL[c].values)]),
                    index=cal.append(pd.DatetimeIndex([cal[-1] + pd.Timedelta(days=1)]))) for c in CONVS}

def tb_logcum(t, conv):
    """cumulative log growth from cal[0] 00:00 to timestamp t (tz-naive UTC), linear within day."""
    t = pd.Timestamp(t).tz_localize(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t)
    day = t.normalize()
    frac = (t - day) / pd.Timedelta(days=1)
    c = CUM[conv]
    return c.loc[day] + frac * DL[conv].loc[day]

def tb_growth(t0, t1, conv="bey_lag1"):
    return math.exp(tb_logcum(t1, conv) - tb_logcum(t0, conv))

def cagr_from_growth(g, years):
    return (g ** (1.0 / years) - 1.0) * 100.0

# yearly average of DTB3 (discount) for reporting
yavg = obs.groupby(obs.index.year).mean() * 100
print("DTB3 yearly avg:", {int(k): round(v, 2) for k, v in yavg.items() if k >= 2019})
print("last obs", obs.index[-1].date(), obs.iloc[-1])

out = {"rows": []}

def sharpe(marks, conv="bey_lag1"):
    """marks: Series of equity at times (tz-aware). simple returns minus TB return over same interval."""
    m = marks.sort_index()
    r = m.pct_change().dropna()
    tbr = np.array([tb_growth(a, b, conv) - 1 for a, b in zip(m.index[:-1], m.index[1:])])
    ex = r.values - tbr
    dt = np.array([(b - a) / pd.Timedelta(days=1) for a, b in zip(m.index[:-1], m.index[1:])])
    per_year = 365.25 / dt.mean()
    return float(ex.mean() / ex.std(ddof=1) * math.sqrt(per_year)), len(ex), per_year

def verdict(ex1, ex2, dd):
    if ex1 <= 0:
        return "FAIL"
    if abs(dd) < 10 and ex2 > 0:
        return "PASS_CANDIDATE"
    return "INCONCLUSIVE"

# ---------------- C1 ----------------
spec = importlib.util.spec_from_file_location("c1run", os.path.join(REPRO, "C1", "run.py"))
c1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c1)
data = {s: c1.load_asset(s) for s in c1.ASSETS}
start = max(d[0].index[0] for d in data.values())
last_bar = min(d[0].index[-1] for d in data.values())
W1 = {"IS": (start, c1.IS_END - c1.H8), "OOS": (c1.IS_END, last_bar), "FULL": (start, last_bar)}
c1res = json.load(open(os.path.join(REPRO, "C1", "result.json")))["results"]
C1 = {}
for lab, (a, b) in W1.items():
    m, sleeves, eq, trs = c1.run_window(data, a, b, 1.0)
    assert abs(m["net_return_pct"] - c1res[lab]["net_return_pct"]) < 1e-9
    t0, t1 = a, eq.index[-1]
    years = (t1 - t0).total_seconds() / (365.25 * 86400)
    g = eq.iloc[-1] / 100.0
    cg = cagr_from_growth(g, years)
    g2 = 1 + c1res[lab]["net_return_2x_cost_pct"] / 100
    cg2 = cagr_from_growth(g2, years)
    tbs = {c: cagr_from_growth(tb_growth(t0, t1, c), years) for c in CONVS}
    tb = tbs["bey_lag1"]
    # daily marks as in prior code: last 8h close of each UTC day, plus start mark
    daily = eq.groupby((eq.index - pd.Timedelta(milliseconds=1)).floor("D")).last()
    # timestamp of the mark = the actual close time (end of day)
    daily.index = daily.index + pd.Timedelta(days=1)
    marks = pd.concat([pd.Series([100.0], index=[t0]), daily])
    sh, n, py = sharpe(marks)
    C1[lab] = dict(net=g * 100 - 100, cagr=cg, tb=tb, ex=cg - tb, ex2=cg2 - tb, dd=c1res[lab]["max_dd_pct"],
                   sharpe=sh, n=n, years=years, tb_all={c: round(v, 3) for c, v in tbs.items()},
                   ex_range=[round(cg - max(tbs.values()), 3), round(cg - min(tbs.values()), 3)],
                   verdict=verdict(cg - tb, cg2 - tb, c1res[lab]["max_dd_pct"]), t0=str(t0), t1=str(t1))
    print("C1", lab, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in C1[lab].items()})

# ---------------- C11 ----------------
c11res = json.load(open(os.path.join(REPRO, "C11", "result.json")))["periods"]
C11 = {}
for lab in ["IS", "OOS", "FULL"]:
    eq = pd.read_csv(os.path.join(REPRO, "C11", f"equity_{lab}.csv"), index_col=0, parse_dates=True)["equity"]
    r = c11res[lab]
    t0, t1 = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
    assert eq.index[0] == t0 and eq.index[-1] == t1
    years = (t1 - t0) / pd.Timedelta(days=365.25)
    g = eq.iloc[-1] / eq.iloc[0]
    cg = cagr_from_growth(g, years)
    cg_rep = r["cagr_pct"]
    cg2 = cagr_from_growth(1 + r["net_return_2x_cost_pct"] / 100, years)
    tbs = {c: cagr_from_growth(tb_growth(t0, t1, c), years) for c in CONVS}
    tb = tbs["bey_lag1"]
    # sharpe on the 08:00 marks (drop the +1s post-sale mark)
    marks = eq[(eq.index.second == 0)]
    sh, n, py = sharpe(marks)
    # alternative: include all marks (incl +1s) -> irregular; skip. Also weekly settlement Sharpe
    wk = eq[eq.index.isin(pd.DatetimeIndex([t0]).append(eq.index[(eq.index.weekday == 0) & (eq.index.second == 0)]))]
    shw, nw, pyw = sharpe(wk)
    dd = r["max_dd_pct"]
    C11[lab] = dict(net=g * 100 - 100, cagr=cg, tb=tb, ex=cg - tb, ex2=cg2 - tb, dd=dd, sharpe=sh, sharpe_weekly=shw,
                    n=n, years=years, tb_all={c: round(v, 3) for c, v in tbs.items()},
                    ex_range=[round(cg - max(tbs.values()), 3), round(cg - min(tbs.values()), 3)],
                    verdict=verdict(cg - tb, cg2 - tb, dd), pf=r["pf"], trades=r["trades"])
    print("C11", lab, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in C11[lab].items()})

# ---------------- C16 (re-implemented) ----------------
raw = json.load(open(os.path.join(CTRL, "data", "C16", "chart_aa70268e.json")))
df = pd.DataFrame(raw["data"])
df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values("ts").drop_duplicates("ts")
df = df[df["ts"] <= pd.Timestamp("2026-10-06 23:59:59", tz="UTC")].reset_index(drop=True)
ts = df["ts"]; apy = df["apy"].astype(float).values / 100
dtd = np.diff(ts.values).astype("timedelta64[ms]").astype(float) / 86400000.0
growth = (1 + apy[:-1]) ** (dtd / 365.0)
years16 = dtd.sum() / 365.0
G16 = float(np.prod(growth))
c16res = json.load(open(os.path.join(REPRO, "C16", "result.json")))
t0, t1 = ts.iloc[0], ts.iloc[-1]
tbs16 = {c: cagr_from_growth(tb_growth(t0, t1, c), years16) for c in CONVS}
tb16 = tbs16["bey_lag1"]

def c16_final(cap, gas):
    return (cap - gas / 2) * G16 - gas / 2

def c16_marks(cap, gas):
    bal = (cap - gas / 2) * np.concatenate([[1.0], np.cumprod(growth)])
    return pd.Series(np.concatenate([[cap], bal - gas / 2]), index=pd.DatetimeIndex([t0 - pd.Timedelta(seconds=1)]).append(pd.DatetimeIndex(ts)))

C16 = {}
for cap in [10000.0, 100.0]:
    f1, f2 = c16_final(cap, 5.0), c16_final(cap, 10.0)
    print("C16 final mine vs prior", f1, c16res["results"][str(int(cap))]["x1"]["final"]); assert abs(f1 / c16res["results"][str(int(cap))]["x1"]["final"] - 1) < 1e-6
    cg = cagr_from_growth(f1 / cap, years16)
    cg2 = cagr_from_growth(f2 / cap, years16)
    mk = c16_marks(cap, 5.0)
    # sharpe: use the snapshot marks (the pre-deposit mark collapsed into first interval)
    mk2 = mk.iloc[1:].copy(); mk2.iloc[0] = cap  # gas at deposit charged within first interval
    mk2 = pd.concat([pd.Series([cap], index=[t0]), mk.iloc[2:]])
    mk2.iloc[0] = cap
    sh, n, py = sharpe(mk2)
    dd = c16res["results"][str(int(cap))]["x1"]["maxdd_pct"]
    C16[cap] = dict(final=f1, net=f1 / cap * 100 - 100, cagr=cg, tb=tb16, ex=cg - tb16, ex2=cg2 - tb16, dd=dd, sharpe=sh,
                    years=years16, tb_all={c: round(v, 3) for c, v in tbs16.items()},
                    ex_by_conv={c: round(cg - v, 3) for c, v in tbs16.items()},
                    verdict=verdict(cg - tb16, cg2 - tb16, dd))
    print("C16", cap, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in C16[cap].items()})

# ---------------- $100 retail frictions ----------------
def friction_final(g_strat_fn, c, net_fee_each_way):
    u = 1 - c / 2
    x = 100 * u - net_fee_each_way
    x = g_strat_fn(x) - net_fee_each_way
    return x * u

FR = {}
for c in [0.0, 0.02, 0.035, 0.05]:
    o1 = C1["OOS"]; g1 = 1 + o1["net"] / 100
    f = friction_final(lambda x: x * g1, c, 0.0)
    FR[("C1", c)] = (f, cagr_from_growth(f / 100, o1["years"]), o1["tb"])
    o11 = C11["OOS"]; g11 = 1 + o11["net"] / 100
    f = friction_final(lambda x: x * g11, c, 1.0)
    FR[("C11", c)] = (f, cagr_from_growth(f / 100, o11["years"]), o11["tb"])
    f = friction_final(lambda x: c16_final(x, 5.0), c, 1.0)
    FR[("C16", c)] = (f, cagr_from_growth(f / 100, years16), tb16)
    # alternative reading: round-trip cost applied once multiplicatively at the end (1-c)
for k, v in FR.items():
    print("FR", k, "final=%.2f ann=%.2f tb=%.2f excess=%.2f" % (v[0], v[1], v[2], v[1] - v[2]))
# alt reading: (1-c) once + fees
for c in [0.02, 0.035, 0.05]:
    g1 = 1 + C1["OOS"]["net"] / 100
    print("ALT C1 c=%.3f final=%.2f" % (c, 100 * g1 * (1 - c)))
    print("ALT C16 c=%.3f final=%.2f" % (c, (c16_final(99.0, 5.0) - 1) * (1 - c)))

# T-bill with the same RUB frictions (fairness check: a RU retail buyer also pays conversion to reach a T-bill)
for nm, yrs, tb in [("C1", C1["OOS"]["years"], C1["OOS"]["tb"]), ("C16", years16, tb16)]:
    gtb = (1 + tb / 100) ** yrs
    for c in [0.02, 0.035, 0.05]:
        f = 100 * (1 - c / 2) ** 2 * gtb
        print("TB-with-frictions", nm, c, "final=%.2f ann=%.2f" % (f, cagr_from_growth(f / 100, yrs)))

# breakeven RUB round trip for C11 vs TB
from scipy.optimize import brentq
o11 = C11["OOS"]; g11 = 1 + o11["net"] / 100
target = 100 * (1 + o11["tb"] / 100) ** o11["years"]
be = brentq(lambda c: friction_final(lambda x: x * g11, c, 1.0) - target, 0, 1.9)
print("C11 breakeven RUB round-trip cost: %.3f" % be)

# feasibility
fx = json.load(open(os.path.join(CTRL, "data", "C1", "fapi_exchangeInfo.json")))
btc_px = float(json.load(open(os.path.join(CTRL, "data", "C1", "perp_klines_8h_BTCUSDT.json")))[-1][4])
eth_px = float(json.load(open(os.path.join(CTRL, "data", "C1", "perp_klines_8h_ETHUSDT.json")))[-1][4])
for s in fx:
    f = {x["filterType"]: x for x in s["filters"]}
    px = btc_px if s["symbol"] == "BTCUSDT" else eth_px
    minleg = max(float(f["MIN_NOTIONAL"]["notional"]), float(f["LOT_SIZE"]["minQty"]) * px)
    print("feas", s["symbol"], "min perp notional=%.2f leg_at_100=25 min_capital=%.0f" % (minleg, minleg / 0.25))
print("C11 min collateral 0.1 BTC at K=0.95*S: %.0f" % (0.1 * 0.95 * btc_px))

json.dump(dict(C1=C1, C11=C11, C16={str(int(k)): v for k, v in C16.items()},
               FR={f"{k[0]}_{k[1]}": v for k, v in FR.items()}), open(os.path.join(V, "verify_result.json"), "w"),
          indent=1, default=str)
