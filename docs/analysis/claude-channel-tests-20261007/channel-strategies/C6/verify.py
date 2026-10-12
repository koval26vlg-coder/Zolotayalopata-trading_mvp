# Independent re-implementation of C6 RELATIVE_STRENGTH_IN_SELLOFF from SPEC2.md
# Does NOT use run.py / result.json.
import json, hashlib, os, sys
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.dirname(os.path.abspath(__file__))

EXPECTED = {
 "BTCUSDT_1d.json":"05e66a34c4d3d277738ec2b919fe4bc6eb07cec5dbca85acc8d671afae5c4173",
 "ETHUSDT_1d.json":"c5a6257dcc5724abcdf03c7fd4f985fc49e8a8140811c3312b7c65b73b8ccdfd",
 "BNBUSDT_1d.json":"6a15ebd47f6039cd70d4f0310c3eee0a089601d71d9de4e9b3ef29d0e20ba6da",
 "XRPUSDT_1d.json":"99033bbf7f45f6d2594798d31b46fc2a17ff273e3d0d747cd11e54c7e3972eae",
 "ADAUSDT_1d.json":"4433574f28c3f0c80986d35d04db84fb851d585e24f5e3fe5a84e572e0a2f009",
 "DOGEUSDT_1d.json":"f7ef616ba64bff03f5c0620da236a8b1c9fad7c7970ad026c67a0551594d8ea2",
 "LTCUSDT_1d.json":"3b5dcb68dcf630197f0951cc4bddb307a6cc0c000275c279da3b9c6b0fd1745e",
 "LINKUSDT_1d.json":"ab08172c4c0a2459df8026944b511d69a32ace822b6bff4a8bd2316d9bc67e8b",
 "BCHUSDT_1d.json":"3b82eba83eb02f7d9c86967d15df6c89e9ff623713687807816b470315ebe7c0",
 "TRXUSDT_1d.json":"302c0e4ebd9315053d70f8d14919aa5003df46e0e74c054678960c64ab95b12d",
 "XLMUSDT_1d.json":"1771d618728e4c75df2ea7a21f0f17a20ee353a6348481f6ef3672c5f80d410f",
 "EOSUSDT_1d.json":"dda48b4fdd976a3145d67bb080cab7f100992a0d5b58bfb78e5be0a46f815b5c",
 "AUSDT_1d.json":"07fbe7a74b826c410a07ae897ffc9223356ba5f6c390c89015542e292f9eace3",
 "ATOMUSDT_1d.json":"e883186057c93c810a5f493d760f4abd0139b0845664b31fac9c7d8b108b3947",
 "XTZUSDT_1d.json":"9953ada89e139e2cbe809292ec64455c5d32b59513dbe71797c94a6489d04729",
 "ETCUSDT_1d.json":"ad58afdf584bd62b56bd50de4f67a011b3c67f2008aba6d7d05705a1462a69f2",
 "NEOUSDT_1d.json":"4463fe0f4fc2f3642fa6caee00519d42d0e26ffc533283ffd345d1a25ffb487f",
 "VETUSDT_1d.json":"ef26b6e5f922c171a6893d59c38fbadae53d4f24689c48412d5d121d9c855513",
 "ZECUSDT_1d.json":"ff4d5b5e7b70e52e18accb3fc69ec34cab66dbb4421cec253c8176ef776f8bda",
 "DASHUSDT_1d.json":"bbe81215e8837d640948b80e6c1d63c233f2a4740b0a10091fdadcd837b96297",
 "IOTAUSDT_1d.json":"191b3680c1c805836b95921fba68db22f2eb8714678ccf33e058e091de8ae3eb",
 "ONTUSDT_1d.json":"002eb363e02ac5c531e6807bfb291eb3cb0ab81c7d4b5363c42c94f58bbfe27d",
 "exchangeInfo_spot.json":"04d07bf5e64648d3eca522d534e5f22ae2fc2dce9ea79c7a8b8dbb6571c09238",
}
for fn, h in EXPECTED.items():
    got = hashlib.sha256(open(os.path.join(DATA, fn), "rb").read()).hexdigest()
    assert got == h, (fn, got)
print("sha256: all", len(EXPECTED), "files OK")

UNIV = ["ETH","BNB","XRP","ADA","DOGE","LTC","LINK","BCH","TRX","XLM","EOS","ATOM","XTZ",
        "ETC","NEO","VET","ZEC","DASH","IOTA","ONT"]
LAST = pd.Timestamp("2026-10-06")
START = pd.Timestamp("2020-01-01")
PERIODS = {"IS": (START, pd.Timestamp("2022-12-31")),
           "OOS": (pd.Timestamp("2023-01-01"), LAST),
           "FULL": (START, LAST)}
COST = 0.0020

def load(sym):
    raw = json.load(open(os.path.join(DATA, f"{sym}USDT_1d.json")))
    df = pd.DataFrame(raw).iloc[:, :7]
    df.columns = ["ot","o","h","l","c","v","ct"]
    df["date"] = pd.to_datetime(df["ot"], unit="ms", utc=True).dt.tz_localize(None)
    # sanity: daily bars start at 00:00 UTC, close at 23:59:59.999
    assert (df["date"].dt.hour == 0).all()
    badct = df[(df["ct"] - df["ot"]) != 86400000 - 1]
    if len(badct):
        print("partial bar(s) in", sym, list(badct["date"].dt.date), "close_time", list(pd.to_datetime(badct["ct"], unit="ms")))
        assert sym == "EOS" and len(badct) == 1 and badct.index[0] == len(df) - 1
    df = df.set_index("date")[["o","h","l","c"]].astype(float)
    df = df[df.index <= LAST]   # only bars closed by 2026-10-06 23:59:59 UTC
    return df

btc = load("BTC")
idx = pd.date_range(btc.index[0], LAST, freq="D")
assert len(btc) == len(idx), "BTC gaps"
O = {}; C = {}; MISSING = {}
for s in UNIV:
    if s == "EOS":
        e = load("EOS"); a = load("A")
        print("EOS last", e.index[-1].date(), e["c"].iloc[-1], " A first", a.index[0].date(), a["o"].iloc[0])
        df = pd.concat([e, a])
    else:
        df = load(s)
    assert df.index[0] <= pd.Timestamp("2020-01-01"), s
    df = df.reindex(idx)
    MISSING[s] = [d.date().isoformat() for d in df.index[df["c"].isna()]]
    O[s] = df["o"]; C[s] = df["c"]
O = pd.DataFrame(O); C = pd.DataFrame(C)
print("missing bars:", {k: v for k, v in MISSING.items() if v})
O_f = O.copy(); C_f = C.ffill()
# for a missing day, open := previous close (for marks only)
for s in UNIV:
    m = O_f[s].isna()
    O_f.loc[m, s] = C_f[s].shift(1)[m]

bo = btc["o"].reindex(idx); bc = btc["c"].reindex(idx)
btc_r7 = bc / bc.shift(7) - 1
coin_r7 = C_f / C_f.shift(7) - 1   # uses only closes <= t

def run(start, end, cost, which="top", trunc_check=False):
    """event loop over signal days in [start, end]; entry t+1 open, exit t+15 open; both must be within [start,end]."""
    trades = []
    days = idx[(idx >= start) & (idx <= end)]
    busy_until = None  # exit date (open) of current trade
    for t in days:
        if busy_until is not None and t < busy_until:
            continue  # trade open at close t
        r = btc_r7.loc[t]
        if not (r <= -0.10):
            continue
        ent = t + pd.Timedelta(days=1); ex = t + pd.Timedelta(days=15)
        if ex > end:
            trades.append(dict(signal=t, skipped="exit beyond period end", entry=ent, exit=ex))
            # treat as forced? report it; do not open
            continue
        rel = (coin_r7.loc[t] - r).dropna()
        if trunc_check:
            # recompute using only data up to t
            Ct = C_f.loc[:t]; bt = bc.loc[:t]
            rel2 = (Ct.iloc[-1] / Ct.iloc[-8] - 1) - (bt.iloc[-1] / bt.iloc[-8] - 1)
            assert np.allclose(rel.sort_index().values, rel2.dropna().sort_index().values)
        df = pd.DataFrame({"sym": rel.index, "rel": rel.values})
        if which == "top":
            df = df.sort_values(["rel","sym"], ascending=[False, True]).head(3)
            syms = list(df["sym"])
        elif which == "bottom":
            df = df.sort_values(["rel","sym"], ascending=[True, True]).head(3)
            syms = list(df["sym"])
        elif which == "btc":
            syms = ["BTC"]
        trades.append(dict(signal=t, entry=ent, exit=ex, syms=syms, btc_r7=r))
        busy_until = ex
    return trades

def price(sym, d, kind):
    if sym == "BTC":
        return (bo if kind == "o" else bc).loc[d]
    v = (O if kind == "o" else C).loc[d, sym]
    assert not np.isnan(v), (sym, d, kind)
    return v

def equity(trades, start, end, cost):
    days = idx[(idx >= start) & (idx <= end)]
    eq = pd.Series(np.nan, index=days)
    E = 1.0; rets = []; inpos = pd.Series(False, index=days)
    tmap = {tr["entry"]: tr for tr in trades if "syms" in tr}
    cur = None
    for d in days:
        if cur is not None and d == cur["exit"]:
            legs = [(1 - cost) * price(s, d, "o") / cur["px"][s] * (1 - cost) for s in cur["syms"]]
            newE = cur["E0"] * np.mean(legs)
            rets.append(newE / cur["E0"] - 1)
            cur["ret"] = newE / cur["E0"] - 1
            cur["legs"] = [x - 1 for x in legs]
            E = newE; cur = None
        if cur is None and d in tmap:
            tr = tmap[d]
            tr["px"] = {s: price(s, d, "o") for s in tr["syms"]}
            tr["E0"] = E
            cur = tr
        if cur is not None:
            inpos[d] = True
            def cl(s):
                if s == "BTC": return bc.loc[d]
                return C_f.loc[d, s]
            E_mark = cur["E0"] * np.mean([(1 - cost) * cl(s) / cur["px"][s] for s in cur["syms"]])
            eq[d] = E_mark
        else:
            eq[d] = E
    assert cur is None, "trade open at period end"
    return eq, rets, inpos

def metrics(eq, rets, inpos, start, end):
    n_days = (end - start).days + 1
    eq0 = pd.concat([pd.Series([1.0], index=[start - pd.Timedelta(days=1)]), eq])
    dd = (eq0 / eq0.cummax() - 1).min()
    net = eq.iloc[-1] - 1
    wins = [r for r in rets if r > 0]; losses = [r for r in rets if r <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
    return dict(trades=len(rets), win_rate_pct=round(100 * len(wins) / len(rets), 2) if rets else None,
                pf=round(pf, 3), net_return_pct=round(100 * net, 2),
                cagr_pct=round(100 * ((1 + net) ** (365.25 / n_days) - 1), 2),
                max_dd_pct=round(100 * dd, 2), exposure_pct=round(100 * inpos.mean(), 2))

def bench(start, end, cost, syms=None):
    syms = syms or UNIV
    days = idx[(idx >= start) & (idx <= end)]
    px0 = O_f.loc[start, syms]
    marks = (C_f.loc[days, syms] / px0).mean(axis=1) * (1 - cost)
    final = marks.iloc[-1] * (1 - cost)
    eq = marks.copy(); eq.iloc[-1] = final
    eq0 = pd.concat([pd.Series([1.0], index=[start - pd.Timedelta(days=1)]), eq])
    dd = (eq0 / eq0.cummax() - 1).min()
    return round(100 * (final - 1), 2), round(100 * dd, 2)

def btc_bh(start, end, cost):
    days = idx[(idx >= start) & (idx <= end)]
    marks = bc.loc[days] / bo.loc[start] * (1 - cost)
    final = marks.iloc[-1] * (1 - cost)
    eq = marks.copy(); eq.iloc[-1] = final
    eq0 = pd.concat([pd.Series([1.0], index=[start - pd.Timedelta(days=1)]), eq])
    return round(100 * (final - 1), 2), round(100 * (eq0 / eq0.cummax() - 1).min(), 2)

# Dec-2019 check: would any signal fire before 2020-01-01 if data start were used?
pre = btc_r7[(btc_r7.index < START)]
print("pre-2020 btc_r7 min:", round(pre.min(), 4), "signals pre-2020:", list(pre[pre <= -0.10].index.date))

results = {}
full_trades = None
for per, (s, e) in PERIODS.items():
    row = {}
    trades = run(s, e, COST, "top", trunc_check=True)
    skipped = [t for t in trades if "skipped" in t]
    trades_ok = [t for t in trades if "skipped" not in t]
    eq, rets, inpos = equity(trades_ok, s, e, COST)
    m = metrics(eq, rets, inpos, s, e)
    eq2, rets2, _ = equity(run(s, e, 2 * COST, "top"), s, e, 2 * COST)
    m["net_return_2x_cost_pct"] = round(100 * (eq2.iloc[-1] - 1), 2)
    bn, bdd = bench(s, e, COST)
    m["bench_net_return_pct"] = bn; m["bench_max_dd_pct"] = bdd
    # controls
    tb = [t for t in run(s, e, COST, "bottom") if "skipped" not in t]
    eqb, rb, ib = equity(tb, s, e, COST); mb = metrics(eqb, rb, ib, s, e)
    tc = [t for t in run(s, e, COST, "btc") if "skipped" not in t]
    eqc, rc, ic = equity(tc, s, e, COST); mc = metrics(eqc, rc, ic, s, e)
    bbh = btc_bh(s, e, COST)
    # leg-level stats
    legs = [x for t in trades_ok for x in t["legs"]]
    lw = [x for x in legs if x > 0]; ll = [x for x in legs if x <= 0]
    m["_legs"] = dict(n=len(legs), win=round(100*len(lw)/len(legs),2), pf=round(sum(lw)/-sum(ll),3))
    m["_bottom3"] = mb; m["_btc_timing"] = mc; m["_btc_bh"] = bbh; m["_skipped"] = [str(t["signal"].date()) for t in skipped]
    m["_ret_dd_ratio"] = round(m["net_return_pct"] / -m["max_dd_pct"], 3)
    m["_bench_ret_dd_ratio"] = round(bn / -bdd, 3)
    results[per] = m
    if per == "FULL":
        full_trades = trades_ok
        tlog = [dict(signal=str(t["signal"].date()), entry=str(t["entry"].date()), exit=str(t["exit"].date()),
                     btc_r7=round(100*t["btc_r7"],2), syms=t["syms"], ret_pct=round(100*t["ret"],2),
                     legs=[round(100*x,2) for x in t["legs"]]) for t in trades_ok]

# Overlap / look-ahead checks
for a, b in zip(full_trades, full_trades[1:]):
    assert b["entry"] > a["exit"] or b["signal"] >= a["exit"], ("overlap", a["signal"], b["signal"])
for t in full_trades:
    assert t["signal"] < t["entry"] < t["exit"]

# future-poisoning test: multiply all prices after signal date by random noise; selection must not change
rng = np.random.default_rng(0)
ok = True
for t in full_trades:
    s = t["signal"]
    Cp = C_f.copy(); Cp.loc[Cp.index > s] *= rng.uniform(0.2, 5.0, size=Cp.loc[Cp.index > s].shape)
    bp = bc.copy(); bp.loc[bp.index > s] *= 3.0
    rel = (Cp.loc[s] / Cp.shift(7).loc[s] - 1) - (bp.loc[s] / bp.shift(7).loc[s] - 1)
    top = list(pd.DataFrame({"sym": rel.index, "rel": rel.values}).sort_values(["rel","sym"], ascending=[False, True]).head(3)["sym"])
    ok &= (top == t["syms"])
print("future-poisoning selection unchanged:", ok)

# ties check
nties = 0
for t in full_trades:
    rel = (coin_r7.loc[t["signal"]] - t["btc_r7"])
    srt = rel.sort_values(ascending=False)
    if abs(srt.iloc[2] - srt.iloc[3]) < 1e-12: nties += 1
print("ties at 3rd/4th rank:", nties)

# Is/OOS boundary crossing in FULL
cross = [t for t in full_trades if t["entry"] <= pd.Timestamp("2022-12-31") < t["exit"]]
print("FULL trades crossing IS/OOS:", len(cross), [str(t["signal"].date()) for t in cross])
# FULL-run trades split by entry vs independent runs
n_is = sum(1 for t in full_trades if t["exit"] <= pd.Timestamp("2022-12-31"))
print("FULL trades fully in IS:", n_is, " in OOS:", sum(1 for t in full_trades if t["entry"] >= pd.Timestamp("2023-01-01")))

# $100 feasibility
ei = json.load(open(os.path.join(DATA, "exchangeInfo_spot.json")))
feas = {}
for sy in ei["symbols"]:
    nm = sy["symbol"]
    base = nm[:-4] if nm.endswith("USDT") else None
    if base in UNIV + ["A", "BTC"] and nm == base + "USDT":
        f = {x["filterType"]: x for x in sy["filters"]}
        mn = f.get("NOTIONAL", f.get("MIN_NOTIONAL", {})).get("minNotional")
        feas[nm] = dict(status=sy["status"], minNotional=mn, stepSize=f["LOT_SIZE"]["stepSize"])
print("exchangeInfo:", json.dumps(feas))

json.dump(dict(results=results, trades=tlog, missing=MISSING), open(os.path.join(OUT, "verify_result.json"), "w"),
          indent=1, default=str)
for per, m in results.items():
    print(per, json.dumps(m, default=str))
print("trades:")
for t in tlog:
    print(t)

# PF definition check: currency (compounded-equity $) PF vs sum-of-% PF
print("\nPF ($ P&L on compounded equity) vs PF (sum of trade %):")
for per, (s, e) in PERIODS.items():
    out = []
    for which in ["top", "bottom", "btc"]:
        tr = [t for t in run(s, e, COST, which) if "skipped" not in t]
        eq_, r_, _ = equity(tr, s, e, COST)
        pnl = [t["E0"] * t["ret"] for t in tr]
        gw = sum(p for p in pnl if p > 0); gl = -sum(p for p in pnl if p < 0)
        pw = sum(t["ret"] for t in tr if t["ret"] > 0); pl = -sum(t["ret"] for t in tr if t["ret"] < 0)
        out.append(f"{which}: $PF={gw/gl:.3f} %PF={pw/pl:.3f}")
    print(per, " | ".join(out))
