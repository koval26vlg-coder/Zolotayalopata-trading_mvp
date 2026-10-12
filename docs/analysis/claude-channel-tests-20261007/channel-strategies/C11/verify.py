# Independent re-implementation of C11 CASH_SECURED_PUT_BTC from SPEC2.md (verifier).
# PROXY: IV = Deribit DVOL daily close x 1.10, Black-76 r=0; underlying = Binance BTCUSDT 1h.
import json, os, hashlib, math
import numpy as np, pandas as pd

W = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(W, "..", "data")
EXPECT = {"deribit_dvol_btc_1D.json": "e93693c49dd4fe2e238f454bedac0d2bc1d734ea2aca4597453573d90c446d9f",
          "binance_btcusdt_1h.json": "80eedd6c74afb1fa0fc70e16016214e736608437e9d4cd0f10779af823587bbc"}
for f, h in EXPECT.items():
    got = hashlib.sha256(open(os.path.join(D, f), "rb").read()).hexdigest()
    assert got == h, (f, got)

LAST_CLOSE = pd.Timestamp("2026-10-07 00:00", tz="UTC")  # bars closed on/before 2026-10-06 23:59:59

# ---- data
k = json.load(open(os.path.join(D, "binance_btcusdt_1h.json")))
kl = pd.DataFrame({"t": pd.to_datetime([r[0] for r in k], unit="ms", utc=True),
                   "o": [float(r[1]) for r in k], "c": [float(r[4]) for r in k]}).set_index("t")
kl = kl[kl.index + pd.Timedelta(hours=1) <= LAST_CLOSE]
dv = json.load(open(os.path.join(D, "deribit_dvol_btc_1D.json")))
dvol = pd.Series([float(r[4]) for r in dv], index=pd.to_datetime([r[0] for r in dv], unit="ms", utc=True))
# a daily candle stamped d closes at d+1 00:00 -> index by close time
dvol_close_time = dvol.copy(); dvol_close_time.index = dvol.index + pd.Timedelta(days=1)
dvol_close_time = dvol_close_time[dvol_close_time.index <= LAST_CLOSE]

def spot_at(ts):
    """Price at instant ts = close of the hourly bar that closed at ts (bar stamped ts-1h).
    Fallback: open of bar stamped ts. Fallback: last close before ts."""
    b = ts - pd.Timedelta(hours=1)
    if b in kl.index:
        return kl.at[b, "c"], "close_prev"
    if ts in kl.index:
        return kl.at[ts, "o"], "open"
    prev = kl[kl.index + pd.Timedelta(hours=1) <= ts]
    return prev["c"].iloc[-1], "ffill"

def iv_at(ts):
    """Latest DVOL daily close with candle close time <= ts (strictly known at ts)."""
    s = dvol_close_time[dvol_close_time.index <= ts]
    return s.iloc[-1] / 100.0, s.index[-1]

def N(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def put_b76(F, K, T, sig):
    if T <= 0:
        return max(0.0, K - F)
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return K * N(-d2) - F * N(-d1)

def call_b76(F, K, T, sig):
    v = sig * math.sqrt(T); d1 = (math.log(F / K) + 0.5 * v * v) / v; d2 = d1 - v
    return F * N(d1) - K * N(d2)

# parity sanity
assert abs(call_b76(100, 95, 7/365, .6) - put_b76(100, 95, 7/365, .6) - (100 - 95)) < 1e-9

SKEW, HAIRCUT, T_DAYS = 1.10, 0.85, 7

# ---- trade schedule: every Monday 08:00 UTC; need DVOL closed before entry and expiry within data
first_dvol_known = dvol_close_time.index[0]
mondays = pd.date_range("2021-03-01 08:00", "2026-10-12 08:00", freq="W-MON", tz="UTC")
entries = [m for m in mondays if m > first_dvol_known and m + pd.Timedelta(days=T_DAYS) <= LAST_CLOSE]

def run(entries, cost_mult=1.0, fee_mult=None, prem_mult=None):
    """Sequential non-overlapping weekly puts. Returns trades df and equity series (daily marks 00:00 + entry/expiry)."""
    fm = cost_mult if fee_mult is None else fee_mult
    hair_disc = (1 - HAIRCUT) * (cost_mult if prem_mult is None else prem_mult)
    eq = 1.0
    marks = []
    trades = []
    for e in entries:
        x = e + pd.Timedelta(days=T_DAYS)
        S0, src0 = spot_at(e)
        sig_raw, ivt = iv_at(e)
        assert ivt <= e
        sig = sig_raw * SKEW
        K = 0.95 * S0
        P = put_b76(S0, K, T_DAYS / 365.0, sig)
        prem = (1 - hair_disc) * P
        fee = fm * min(0.0003 * S0, 0.125 * prem)
        n = eq / K  # BTC notional fully cash-secured
        cash = eq + n * (prem - fee)
        marks.append((e, eq))  # pre-trade equity
        marks.append((e + pd.Timedelta(seconds=1), cash - n * P))  # mark at model mid right after sale
        for d in pd.date_range(e.normalize() + pd.Timedelta(days=1), x - pd.Timedelta(seconds=1), freq="D"):
            Sd, _ = spot_at(d)
            sd, ivd = iv_at(d)
            Trem = (x - d).total_seconds() / (365 * 86400)
            marks.append((d, cash - n * put_b76(Sd, K, Trem, sd * SKEW)))
        ST, srcT = spot_at(x)
        pay = max(0.0, K - ST)
        pnl = n * (prem - fee - pay)
        trades.append(dict(entry=e, expiry=x, S0=S0, ST=ST, K=K, dvol=sig_raw, iv=sig, model=P, prem=prem, fee=fee,
                           payoff=pay, n=n, eq0=eq, pnl=pnl, ret=pnl / eq, src0=src0, srcT=srcT, ivtime=ivt))
        eq = cash - n * pay
    marks.append((entries[-1] + pd.Timedelta(days=T_DAYS), eq))
    s = pd.Series([m[1] for m in marks], index=[m[0] for m in marks])
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return pd.DataFrame(trades), s

def maxdd(s):
    return float((s / s.cummax() - 1).min() * 100)

def stats(tr, eqs):
    w = tr.pnl[tr.pnl > 0].sum(); l = -tr.pnl[tr.pnl < 0].sum()
    wr_ = tr.ret[tr.ret > 0].sum(); lr_ = -tr.ret[tr.ret < 0].sum()
    yrs = (eqs.index[-1] - eqs.index[0]).total_seconds() / (365.25 * 86400)
    net = eqs.iloc[-1] / eqs.iloc[0] - 1
    return dict(trades=len(tr), win_rate_pct=round(100 * (tr.pnl > 0).mean(), 2), pf=round(w / l, 3) if l > 0 else None,
                pf_ret=round(wr_ / lr_, 3) if lr_ > 0 else None,
                net_return_pct=round(100 * net, 2), cagr_pct=round(100 * ((1 + net) ** (1 / yrs) - 1), 2),
                max_dd_pct=round(maxdd(eqs), 2), years=round(yrs, 3), start=str(eqs.index[0]), end=str(eqs.index[-1]))

def bench_btc(start, end, cost=0.002):
    """BTC B&H: buy at start (spot_at), sell at end, 20 bps per side; daily marks at 00:00."""
    S0, _ = spot_at(start)
    pts = [(start, 1.0 * (1 - cost))]
    units = (1 - cost) / S0
    for d in pd.date_range(start.normalize() + pd.Timedelta(days=1), end, freq="D"):
        if d < end:
            pts.append((d, units * spot_at(d)[0]))
    pts.append((end, units * spot_at(end)[0] * (1 - cost)))
    s = pd.Series([p[1] for p in pts], index=[p[0] for p in pts])
    s0 = pd.concat([pd.Series([1.0], index=[start - pd.Timedelta(seconds=1)]), s])
    yrs = (end - start).total_seconds() / (365.25 * 86400)
    net = s.iloc[-1] - 1
    return dict(net_return_pct=round(100 * net, 2), cagr_pct=round(100 * ((1 + net) ** (1 / yrs) - 1), 2),
                max_dd_pct=round(maxdd(s0), 2))

OOS0 = pd.Timestamp("2023-01-01", tz="UTC")
periods = {"IS": [e for e in entries if e < OOS0], "OOS": [e for e in entries if e >= OOS0], "FULL": entries}
out = {}
for p, ents in periods.items():
    tr, eqs = run(ents)
    st = stats(tr, eqs)
    tr2, eqs2 = run(ents, cost_mult=2.0)
    st2 = stats(tr2, eqs2)
    trf, eqf = run(ents, fee_mult=2.0, prem_mult=1.0)
    stf = stats(trf, eqf)
    # weekly-only marks (entry/expiry) maxDD as sensitivity
    wk = eqs[[i for i in eqs.index if i.hour == 8 and i.second == 0]]
    b = bench_btc(ents[0], ents[-1] + pd.Timedelta(days=T_DAYS))
    # break-even premium fraction
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        global_h = HAIRCUT
        trb, eqb = run(ents, prem_mult=(1 - mid) / (1 - HAIRCUT), fee_mult=1.0)
        if eqb.iloc[-1] > 1.0: hi = mid
        else: lo = mid
    years_tbl = {}
    for y, g in tr.groupby(tr.entry.dt.year):
        years_tbl[int(y)] = round(100 * ((1 + g.ret).prod() - 1), 2)
    out[p] = dict(stats=st, x2=st2, fee_only_x2=stf, bench=b, maxdd_weekly_marks=round(maxdd(wk), 2),
                  breakeven_prem_frac=round(hi, 3), by_year=years_tbl,
                  worst_week_pct=round(100 * tr.ret.min(), 2), itm_weeks=int((tr.payoff > 0).sum()),
                  avg_prem_pct_spot=round(100 * (tr.prem / tr.S0).mean(), 3),
                  fee_is_spot_cap=int((0.0003 * tr.S0 <= 0.125 * tr.prem).sum()),
                  spot_src=tr.src0.value_counts().to_dict(), exp_src=tr.srcT.value_counts().to_dict())
    if p == "FULL":
        tr.to_csv(os.path.join(W, "verify_trades_FULL.csv"), index=False)
        eqs.to_csv(os.path.join(W, "verify_equity_FULL.csv"))
# ratios
for p in out:
    s, b = out[p]["stats"], out[p]["bench"]
    out[p]["ratio_net_dd"] = round(s["net_return_pct"] / abs(s["max_dd_pct"]), 3)
    out[p]["bench_ratio_net_dd"] = round(b["net_return_pct"] / abs(b["max_dd_pct"]), 3)
    out[p]["ratio_cagr_dd"] = round(s["cagr_pct"] / abs(s["max_dd_pct"]), 3)
    out[p]["bench_ratio_cagr_dd"] = round(b["cagr_pct"] / abs(b["max_dd_pct"]), 3)
json.dump(out, open(os.path.join(W, "verify_result.json"), "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
print("entries", len(entries), entries[0], entries[-1])
