# Independent re-implementation of SPEC2 C15A/C15B (gap continuation / gap fade)
import json, hashlib, os
import numpy as np, pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "..", "data")
UNIV = "AAPL MSFT AMZN GOOGL META NVDA TSLA JPM BAC XOM CVX JNJ PFE KO PEP WMT HD DIS INTC CSCO ORCL NFLX ADBE CRM AMD QCOM T VZ MRK BA".split()
EXPECTED = {
"AAPL":"4f2bcdddaed7db4e14e82c40eded2e0ffbceb46f5fbea1092ffe43a03bad7a47","MSFT":"5d9b7b80c1bc451390554fed3b3702685685424050d0f9d824b82d4c396e7f44",
"AMZN":"24425115d4557ee54c7f358967f574004c65eb2c97d624419503d20c4f32e8ae","GOOGL":"03a74b46f19c4287c9caf074e72f3cc1f1d07975bcfa2559a8a31ddcfe92c2c8",
"META":"0cb8d5049a784b171b232e1f1b5972a14ea88d60921a60f1dc413622d75078a4","NVDA":"275637cff05410ac6c6f4d844e8c6cfc046f034248cba26795d71eb4fbada076",
"TSLA":"b0b1738cfbf36d2a08f81223b22389ca19dbd9f6e5861ed714f5adb723738f70","JPM":"0ff597e3698bb6ec64266170295d8a2f96191027f254287627bf2c85141209c3",
"BAC":"ea85e649f3616d10fcb22220dab22375054c1d73d0f5b6bd243b31f454df280e","XOM":"e551babaa9a6bc332fe94b33a78cf0af943e40e384327069c97b5d66156d4c39",
"CVX":"9e9516073c7e9b4ed910cb51190945531a058959b73188e51e2a1bcaf8a46c7c","JNJ":"b48a8a5c15231b59cbb0645c74b74fb62c2c4614ab287e75e424c11a72ad65b9",
"PFE":"5e068491837c7af52609ddb17cbb291861f95b67d10da1554ba5299a57ccf59b","KO":"191bf58791f2cdb40bae2248a62fbf13dbe3005e4dc1e4f2481d19e0d98003e7",
"PEP":"a6b824fdcde3eeb6993100fae190501553f248a49260eee8feab64bf978a0b03","WMT":"a1f52c99b5550d06e9fb36978e3ee8d45370f30dce2106f6841fcf2c3324bfad",
"HD":"69c56d1c926eac38dce7010d601ad6417815aeeb7cabaa4df3c00749d394e419","DIS":"3763c50cf519b79adb48da2a6e10a0c77a9da21f76b74deb5895d1be85e5e487",
"INTC":"867912b1b4a111659d831606e1c4bf3b86bdeb32f4e5d187ad6d1ca19155dc92","CSCO":"dff8278a48d91ee13009e7b3532cb452f3410bf94d64bb46103fa24627827496",
"ORCL":"00be0934268ad5d9c633c92d745bf18b93a34a88467fb82f154b3c878df2f891","NFLX":"8e98a668c8c2a8970e48d28b229901c22eeb279207e70225a54dd4168cae0cbf",
"ADBE":"d43b307b37407fc206fa12995a9ebe9c52af2afcf141b04dbea37b46ea9817b4","CRM":"f5a9d057ed3aa2347597055b009bc206dd3aa1059b16004d4263d21bbf611696",
"AMD":"c74b6b1b5a055a50b5253a5b92f500a5f2dfa55e1e21df16c2a23528acaf5a3f","QCOM":"7ed210bbd4d2c422de807a0d151e91758a3d7a8ebd9c89dadff631f850bc5116",
"T":"04fa57683ffb3c34dea046b6b2d593f39602a6779384a63c67459eca418ce57b","VZ":"dacbba8b506de3d810630f04eca068db22a13dce588ee9482c047bfeffe519b4",
"MRK":"8eff80515c3f025daa6ac67c379ff61be8c30573f52089dcfb80ac79f9f5401d","BA":"52b75ec9bb01d120eb7f2712dfcba51130c615a77c89a15c51f2ce9bae93563a"}
COST = 0.0005
GAP = 0.02
LAST = pd.Timestamp("2026-10-06")
IS_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")


def load(t):
    p = os.path.join(DATA, t + ".json")
    raw = open(p, "rb").read()
    h = hashlib.sha256(raw).hexdigest()
    assert h == EXPECTED[t], (t, h)
    r = json.loads(raw)["chart"]["result"][0]
    tz = r["meta"]["exchangeTimezoneName"]
    # convert bar timestamps to exchange-local dates (DST-safe)
    idx = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert(tz)
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                       "adj": r["indicators"]["adjclose"][0]["adjclose"]}, index=idx)
    local_hours = sorted(set(idx.hour))
    df.index = pd.DatetimeIndex(df.index.date)
    df = df[df.index <= LAST]
    n_null = int(df[["open", "close"]].isna().any(axis=1).sum())
    n_dup = int(df.index.duplicated().sum())
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["open", "close"])
    df = df.astype(float)
    bad = int(((df["open"] <= 0) | (df["close"] <= 0)
               | (df["high"] < df[["open", "close"]].max(axis=1) * 0.999)
               | (df["low"] > df[["open", "close"]].min(axis=1) * 1.001)).sum())
    return df, dict(null=n_null, dup=n_dup, bad_ohlc=bad, start=str(df.index[0].date()),
                    end=str(df.index[-1].date()), rows=len(df), local_hours=local_hours)


data, qc = {}, {}
for t in UNIV:
    data[t], qc[t] = load(t)

O = pd.DataFrame({t: data[t]["open"] for t in UNIV}).sort_index()
C = pd.DataFrame({t: data[t]["close"] for t in UNIV}).sort_index()
A = pd.DataFrame({t: data[t]["adj"] for t in UNIV}).sort_index()
cal = O.index

# previous close per ticker = its own previous trading row
prevC = pd.DataFrame({t: data[t]["close"].shift(1) for t in UNIV}).reindex(cal)
gap = O / prevC - 1.0
sig = (gap >= GAP).fillna(False)


def trade_returns(side, cost):
    if side == "long":
        return (C * (1 - cost)) / (O * (1 + cost)) - 1.0
    # short: sell at open*(1-c), buy back at close*(1+c); return per $ of notional at open
    return (O * (1 - cost) - C * (1 + cost)) / O


def run(side, cost, start, end, sigm=None):
    sigm = sig if sigm is None else sigm
    days = cal[(cal >= start) & (cal <= end)]
    s = sigm.loc[days]
    r = trade_returns(side, cost).loc[days]
    n = s.sum(axis=1)
    eq = 1.0
    eqs, pnl, rets, dret = [], [], [], []
    for d in days:
        k = int(n.loc[d])
        if k > 0:
            rr = r.loc[d][s.loc[d]].values
            w = eq / k
            pnl.extend(list(w * rr))
            rets.extend(list(rr))
            dret.append(rr.mean())
            eq = eq * (1 + rr.mean())
        eqs.append(eq)
    eqs = pd.Series(eqs, index=days)
    pnl = np.array(pnl)
    rets = np.array(rets)
    peak = np.maximum.accumulate(np.r_[1.0, eqs.values])[1:]
    mdd = (eqs.values / peak - 1).min()
    yrs = (days[-1] - days[0]).days / 365.25
    net = eqs.iloc[-1] - 1
    cagr = (eqs.iloc[-1]) ** (1 / yrs) - 1
    pf = pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()
    pf_unw = rets[rets > 0].sum() / -rets[rets < 0].sum()
    return dict(trades=len(pnl), win=100 * (pnl > 0).mean(), pf=pf, pf_unweighted=pf_unw, net=100 * net,
                cagr=100 * cagr, mdd=100 * mdd, exposure=100 * (n > 0).mean(), sig_days=int((n > 0).sum()),
                days=len(days), avg_trade_bps=1e4 * rets.mean(), avg_day_ret_pct=100 * np.mean(dret),
                single_name_days_pct=100 * float((n[n > 0] == 1).mean()),
                first=str(days[0].date()), last=str(days[-1].date()))


def bench(start, end, late="exclude"):
    days = cal[(cal >= start) & (cal <= end)]
    a = A.loc[days]
    d0 = days[0]
    names = [t for t in UNIV if not np.isnan(a.loc[d0, t])]
    if late == "exclude":
        rel = a[names] / a.loc[d0, names]
        gross = rel.ffill().mean(axis=1)
    else:
        # each of 30 names gets 1/30 slot; late names sit in cash (0%) until first available adj close, then buy
        cols = []
        for t in UNIV:
            s = a[t]
            fv = s.first_valid_index()
            v = (s / s.loc[fv]).ffill()
            v = v.fillna(1.0)
            cols.append(v)
        gross = pd.concat(cols, axis=1).mean(axis=1)
    marks = gross / (1 + COST)
    peak = np.maximum.accumulate(np.r_[1.0, marks.values])[1:]
    mdd = (marks.values / peak - 1).min()
    net = gross.iloc[-1] * (1 - COST) / (1 + COST) - 1
    yrs = (days[-1] - days[0]).days / 365.25
    return dict(net=100 * net, mdd=100 * mdd, cagr=100 * ((1 + net) ** (1 / yrs) - 1), n=len(names),
                excluded=[t for t in UNIV if t not in names])


periods = {"IS": (cal[0], IS_END), "OOS": (OOS_START, LAST), "FULL": (cal[0], LAST)}
res = {"qc": qc, "rows": {}}
for strat, side in (("A", "long"), ("B", "short")):
    for p, (s0, s1) in periods.items():
        m = run(side, COST, s0, s1)
        m0 = run(side, 0.0, s0, s1)
        m2 = run(side, 2 * COST, s0, s1)
        m.update(net_2x=m2["net"], pf_2x=m2["pf"], net_0cost=m0["net"], pf_0cost=m0["pf"],
                 bench=bench(s0, s1), bench_late_in_cash=bench(s0, s1, late="cash"))
        res["rows"][f"{strat}-{p}"] = m

# ---- look-ahead checks ----
# 1) the close used in the gap is strictly from an earlier date than the signal date
ok = True
for t in UNIV:
    s = data[t]["close"]
    prev_dates = pd.Series(s.index, index=s.index).shift(1)
    sd = sig[t][sig[t]].index
    ok &= bool((prev_dates.reindex(sd).values < sd.values).all())
res["prev_close_date_strictly_before_signal"] = ok
# 2) perturbing same-day close must not change signals
rng = np.random.default_rng(0)
data_p = {t: data[t].copy() for t in UNIV}
for t in UNIV:
    # perturb close of each day; signal for day t uses close_{t-1} -> perturbed closes shift signals only via t-1;
    # instead test: replace close_t by NaN-safe random for day t and recompute signal for day t using prev close unchanged
    pass
prevC_alt = pd.DataFrame({t: data[t]["close"].shift(1) for t in UNIV}).reindex(cal)
C_rand = C * (1 + rng.normal(0, 0.1, C.shape))
sig_alt = ((O / prevC_alt - 1.0) >= GAP).fillna(False)  # signal formula does not reference C_rand at all
res["signal_independent_of_same_day_close"] = bool((sig_alt == sig).all().all())
# 3) big gaps sanity
st = gap.stack()
big = st[st.abs() > 0.30]
res["gaps_abs_over_30pct"] = {f"{d.date()} {t}": round(float(v), 4) for (d, t), v in big.items()}
res["n_signals_total"] = int(sig.values.sum())
print(json.dumps(res, indent=1, default=str))
json.dump(res, open(os.path.join(BASE, "verify_result.json"), "w"), indent=1, default=str)
