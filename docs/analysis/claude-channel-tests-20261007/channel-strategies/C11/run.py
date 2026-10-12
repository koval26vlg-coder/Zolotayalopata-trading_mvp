# C11 CASH_SECURED_PUT_BTC — backtest per SPEC2.md (frozen 2026-10-07). No tuning, no variants.
# PROXY (label): option prices are NOT real Deribit quotes. Implied vol = Deribit DVOL (BTC, daily, 30d index)
# x 1.10 (put-skew assumption), Black-76 r=0, then 85% of model premium (bid haircut). Underlying = Binance BTCUSDT.
import json, os, hashlib, math
import numpy as np
import pandas as pd
from scipy.stats import norm as _sn

class norm:
    @staticmethod
    def cdf(x):
        return 0.5 * math.erfc(-x / math.sqrt(2.0))

W = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(W, "data")
F_DVOL = os.path.join(D, "deribit_dvol_btc_1D.json")
F_KL = os.path.join(D, "binance_btcusdt_1h.json")

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

H = pd.Timedelta(hours=1)
DAY = pd.Timedelta(days=1)
LAST_USABLE = pd.Timestamp("2026-10-06 23:59:59", tz="UTC")

# ---------------- data ----------------
dv = pd.DataFrame(json.load(open(F_DVOL)), columns=["ts", "o", "h", "l", "c"])
dv["open_time"] = pd.to_datetime(dv["ts"], unit="ms", utc=True)
dv["close_time"] = dv["open_time"] + DAY          # daily candle closes at next 00:00 UTC (verified vs 1h data)
dv = dv[dv["close_time"] <= LAST_USABLE + pd.Timedelta(seconds=1)]
dvol_close = pd.Series(dv["c"].values, index=dv["close_time"]).sort_index()

kl = pd.DataFrame(json.load(open(F_KL))).iloc[:, :6]
kl.columns = ["ts", "o", "h", "l", "c", "v"]
kl["t"] = pd.to_datetime(kl["ts"], unit="ms", utc=True)
kl = kl.set_index("t")[["o", "h", "l", "c"]].astype(float)
kl = kl[kl.index + H <= LAST_USABLE + pd.Timedelta(seconds=1)]   # only bars closed by 2026-10-06 23:59 UTC

fallback_log = []
def spot_at(t):
    """BTCUSDT price at time t = open of the 1h bar starting at t (fallback: next bar within 3h)."""
    if t in kl.index:
        return kl.at[t, "o"], t
    nxt = kl.index[kl.index > t]
    if len(nxt) and nxt[0] - t <= pd.Timedelta(hours=3):
        if (str(t), str(nxt[0])) not in fallback_log:
            fallback_log.append((str(t), str(nxt[0])))
        return kl.at[nxt[0], "o"], nxt[0]
    raise KeyError(t)

def iv_at(t):
    """Last CLOSED daily DVOL value with close_time <= t (no look-ahead). Returns (iv_decimal_with_skew, close_time)."""
    s = dvol_close[dvol_close.index <= t]
    ct = s.index[-1]
    assert ct <= t, "look-ahead in IV"
    assert t - ct <= pd.Timedelta(days=2), f"stale DVOL at {t}"
    return s.iloc[-1] / 100.0 * 1.10, ct

def b76_put(F, K, T, sig):
    if T <= 0:
        return max(0.0, K - F)
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return K * norm.cdf(-d2) - F * norm.cdf(-d1)

def b76_call(F, K, T, sig):
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    return F * norm.cdf(d1) - K * norm.cdf(d1 - v)

# ---------------- weekly schedule ----------------
first_dvol_close = dvol_close.index[0]
mondays = pd.date_range("2021-03-01 08:00", "2026-10-06 08:00", freq="W-MON", tz="UTC")
weeks = []
for m in mondays:
    exp = m + pd.Timedelta(days=7)
    if m - pd.Timedelta(hours=8) < first_dvol_close:       # need a DVOL daily close at/before Monday 00:00
        continue
    if exp + H > LAST_USABLE + pd.Timedelta(seconds=1):     # expiry bar must be closed within usable data
        continue
    weeks.append(m)

# precompute per-week market data (independent of capital)
WK = []
for m in weeks:
    S0, t0 = spot_at(m)
    iv0, ivt0 = iv_at(m)
    K = 0.95 * S0
    T = 7 / 365.0
    P = b76_put(S0, K, T, iv0)
    marks = []
    for d in range(1, 7):
        td = m + pd.Timedelta(days=d)
        Sd, _ = spot_at(td)
        ivd, ivtd = iv_at(td)
        marks.append((td, Sd, ivd, (7 - d) / 365.0))
    ST, tT = spot_at(m + pd.Timedelta(days=7))
    WK.append(dict(entry=m, entry_bar=t0, S0=S0, iv=iv0, iv_close_time=ivt0, K=K, T=T, P=P,
                   marks=marks, expiry=m + pd.Timedelta(days=7), expiry_bar=tT, ST=ST))

# ---------------- self-checks (look-ahead) ----------------
checks = {}
checks["iv_signal_close_before_entry"] = all(w["iv_close_time"] <= w["entry"] for w in WK)
checks["iv_signal_strictly_prior_daily_bar"] = all(w["iv_close_time"] + pd.Timedelta(hours=8) == w["entry"] for w in WK)
checks["entry_before_expiry"] = all(w["entry"] < w["expiry"] for w in WK)
checks["marks_use_only_past_iv"] = all(iv_at(mk[0])[1] <= mk[0] for w in WK[:50] for mk in w["marks"])
checks["entries_are_monday_0800_utc"] = all(w["entry"].weekday() == 0 and w["entry"].hour == 8 and w["entry_bar"] == w["entry"] for w in WK)
checks["norm_cdf_matches_scipy"] = abs(norm.cdf(0.7) - _sn.cdf(0.7)) < 1e-12
checks["no_trade_overlap"] = all(WK[i]["expiry"] <= WK[i + 1]["entry"] for i in range(len(WK) - 1))
checks["last_expiry_within_usable_data"] = str(WK[-1]["expiry"])
# pricing sanity: put-call parity with r=0, intrinsic at T=0
pp = []
for w in WK[:20]:
    pp.append(abs(b76_call(w["S0"], w["K"], w["T"], w["iv"]) - w["P"] - (w["S0"] - w["K"])))
checks["put_call_parity_max_err"] = float(max(pp))
checks["intrinsic_at_expiry_ok"] = b76_put(90.0, 95.0, 0.0, 0.5) == 5.0
checks["stop_first_intrabar"] = "n/a: European put settled at expiry, no stops/TP"
checks["spot_fallbacks_used"] = fallback_log

# ---------------- simulation ----------------
def simulate(wk, haircut=0.85, fee_mult=1.0, E0=100.0):
    E = E0
    eq_t, eq_v = [], []
    trades = []
    for w in wk:
        prem = haircut * w["P"]
        fee = fee_mult * min(0.0003 * w["S0"], 0.125 * prem)
        q = E / w["K"]                                 # fully cash-secured: q*K = equity
        cash = E + q * (prem - fee)
        if not eq_t:
            eq_t.append(w["entry"]); eq_v.append(E)
        # mark just after sale at model value (liability at model mid, no haircut)
        eq_t.append(w["entry"] + pd.Timedelta(seconds=1)); eq_v.append(cash - q * w["P"])
        for (td, Sd, ivd, Tr) in w["marks"]:
            eq_t.append(td); eq_v.append(cash - q * b76_put(Sd, w["K"], Tr, ivd))
        payoff = q * max(0.0, w["K"] - w["ST"])
        pnl = q * (prem - fee) - payoff
        E = cash - payoff
        eq_t.append(w["expiry"]); eq_v.append(E)
        trades.append(dict(entry=str(w["entry"]), S0=w["S0"], K=w["K"], ST=w["ST"], iv=w["iv"],
                           prem_pct=prem / w["S0"] * 100, fee_pct=fee / w["S0"] * 100,
                           assigned=w["ST"] < w["K"], pnl=pnl, ret_pct=pnl / (q * w["K"]) * 100, E_after=E))
    eq = pd.Series(eq_v, index=pd.DatetimeIndex(eq_t))
    eq = eq[~eq.index.duplicated(keep="last")]
    return eq, pd.DataFrame(trades)

def maxdd(eq):
    return float(((eq / eq.cummax()) - 1).min() * 100)

def metrics(eq, tr, wk):
    t0, t1 = wk[0]["entry"], wk[-1]["expiry"]
    yrs = (t1 - t0) / pd.Timedelta(days=365.25)
    net = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    wins = tr.loc[tr.pnl > 0, "pnl"].sum(); losses = -tr.loc[tr.pnl < 0, "pnl"].sum()
    in_pos = sum(((w["expiry"] - w["entry"]) for w in wk), pd.Timedelta(0)) / (t1 - t0) * 100
    weekly_only = eq[eq.index.isin([w["expiry"] for w in wk]) | (eq.index == t0)]
    return dict(trades=int(len(tr)), win_rate_pct=round(float((tr.pnl > 0).mean() * 100), 2),
                pf=round(float(wins / losses), 3) if losses > 0 else None,
                net_return_pct=round(float(net), 2),
                cagr_pct=round(float(((1 + net / 100) ** (1 / yrs) - 1) * 100), 2),
                max_dd_pct=round(maxdd(eq), 2), max_dd_weekly_settle_pct=round(maxdd(weekly_only), 2),
                exposure_pct=round(float(in_pos), 2), years=round(float(yrs), 3),
                assigned_weeks=int(tr.assigned.sum()), worst_week_pct=round(float(tr.ret_pct.min()), 2),
                best_week_pct=round(float(tr.ret_pct.max()), 2),
                avg_prem_pct_spot=round(float(tr.prem_pct.mean()), 3),
                start=str(t0), end=str(t1))

def bench_btc(wk, cost=0.002):
    t0, t1 = wk[0]["entry"], wk[-1]["expiry"]
    idx = [t0] + [mk[0] for w in wk for mk in w["marks"]] + [w["expiry"] for w in wk]
    idx = sorted(set(idx))
    px = pd.Series([spot_at(t)[0] for t in idx], index=pd.DatetimeIndex(idx))
    units = 100 * (1 - cost) / px.iloc[0]
    eq = units * px
    eq.iloc[-1] = eq.iloc[-1] * (1 - cost)
    eq = pd.concat([pd.Series([100.0], index=[t0 - pd.Timedelta(seconds=1)]), eq])
    yrs = (t1 - t0) / pd.Timedelta(days=365.25)
    net = (eq.iloc[-1] / 100 - 1) * 100
    eq2 = 100 * (1 - 2 * cost) / px.iloc[0] * px; eq2.iloc[-1] *= (1 - 2 * cost)
    return dict(net_return_pct=round(float(net), 2), cagr_pct=round(float(((1 + net / 100) ** (1 / yrs) - 1) * 100), 2),
                max_dd_pct=round(maxdd(eq), 2), net_return_2x_cost_pct=round(float((eq2.iloc[-1] / 100 - 1) * 100), 2),
                trades=1, exposure_pct=100.0)

periods = {
    "IS": [w for w in WK if w["entry"] <= pd.Timestamp("2022-12-31 23:59", tz="UTC")],
    "OOS": [w for w in WK if w["entry"] >= pd.Timestamp("2023-01-01", tz="UTC")],
    "FULL": WK,
}

res = {"strategy": "C11 CASH_SECURED_PUT_BTC", "proxy": True, "checks": checks, "periods": {}}
for name, wk in periods.items():
    eq, tr = simulate(wk)
    m = metrics(eq, tr, wk)
    eq2, tr2 = simulate(wk, haircut=1 - 2 * 0.15, fee_mult=2.0)
    m["net_return_2x_cost_pct"] = round(float((eq2.iloc[-1] / eq2.iloc[0] - 1) * 100), 2)
    eq2f, _ = simulate(wk, haircut=0.85, fee_mult=2.0)
    m["net_return_2x_fee_only_pct"] = round(float((eq2f.iloc[-1] / eq2f.iloc[0] - 1) * 100), 2)
    pf2 = tr2.loc[tr2.pnl > 0, "pnl"].sum() / -tr2.loc[tr2.pnl < 0, "pnl"].sum()
    m["pf_2x_cost"] = round(float(pf2), 3)
    # diagnostic only (not a variant): premium multiplier at which net return = 0
    lo, hi = 0.0, 2.0
    for _ in range(50):
        mid = (lo + hi) / 2
        e, _t = simulate(wk, haircut=mid)
        if e.iloc[-1] > 100: hi = mid
        else: lo = mid
    m["diag_breakeven_premium_fraction_of_model"] = round(hi, 3)
    b = bench_btc(wk)
    m["bench_btc"] = b
    m["bench_cash"] = dict(net_return_pct=0.0, max_dd_pct=0.0)
    m["ann_net_pct"] = m["cagr_pct"]
    m["ret_dd_ratio"] = round(m["net_return_pct"] / abs(m["max_dd_pct"]), 3) if m["max_dd_pct"] else None
    m["bench_ret_dd_ratio"] = round(b["net_return_pct"] / abs(b["max_dd_pct"]), 3) if b["max_dd_pct"] else None
    # info only: Calmar-style alternative (CAGR/|maxDD|); verdict uses net return/|maxDD| as pre-registered in code before the run
    m["info_cagr_dd_ratio"] = round(m["cagr_pct"] / abs(m["max_dd_pct"]), 3)
    m["info_bench_cagr_dd_ratio"] = round(b["cagr_pct"] / abs(b["max_dd_pct"]), 3)
    m["by_year_net_pct"] = {}
    for y in sorted(set(pd.to_datetime(tr.entry).dt.year)):
        sub = tr[pd.to_datetime(tr.entry).dt.year == y]
        m["by_year_net_pct"][int(y)] = round(float((np.prod(1 + sub.ret_pct / 100) - 1) * 100), 2)
    res["periods"][name] = m
    tr.to_csv(os.path.join(W, f"trades_{name}.csv"), index=False)
    eq.to_csv(os.path.join(W, f"equity_{name}.csv"), header=["equity"])

# ---------------- pre-registered verdict (mechanical, on OOS) ----------------
o = res["periods"]["OOS"]; b = o["bench_btc"]
fail_reasons = []
if o["net_return_pct"] <= 0: fail_reasons.append("OOS net <= 0")
if o["pf"] is not None and o["pf"] < 1.0: fail_reasons.append("PF < 1.0")
if o["net_return_pct"] < b["net_return_pct"] and abs(o["max_dd_pct"]) > abs(b["max_dd_pct"]):
    fail_reasons.append("worse than BTC B&H on both return and maxDD")
pass_checks = {
    "net_positive": o["net_return_pct"] > 0,
    "pf_ge_1.2": (o["pf"] or 0) >= 1.2,
    "beats_btc_bh_on_ret_dd_ratio": (o["ret_dd_ratio"] or -1e9) > (o["bench_ret_dd_ratio"] if o["bench_ret_dd_ratio"] is not None else -1e9),
    "net_positive_at_2x_costs": o["net_return_2x_cost_pct"] > 0,
}
carry_flag = {"ann_net_gt_4": o["ann_net_pct"] > 4, "max_dd_lt_10": abs(o["max_dd_pct"]) < 10}
if fail_reasons:
    verdict = "FAIL"
elif o["trades"] < 30:
    verdict = "INCONCLUSIVE"
elif all(pass_checks.values()):
    verdict = "PASS_CANDIDATE"
else:
    verdict = "INCONCLUSIVE"
res["verdict"] = dict(verdict=verdict, fail_reasons=fail_reasons, pass_checks=pass_checks, carry_criterion_info=carry_flag)
res["data_sources"] = [
    dict(name="Deribit DVOL BTC 1D (public/get_volatility_index_data)", file=F_DVOL, sha256=sha(F_DVOL),
         rows=int(len(dv)), start=str(dv.open_time.iloc[0]), end=str(dv.close_time.iloc[-1]),
         url="https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=1D"),
    dict(name="Binance BTCUSDT 1h klines (api/v3/klines)", file=F_KL, sha256=sha(F_KL),
         rows=int(len(kl)), start=str(kl.index[0]), end=str(kl.index[-1] + H),
         url="https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h"),
]
res["n_weeks"] = len(WK)
json.dump(res, open(os.path.join(W, "result.json"), "w"), indent=1, default=str, ensure_ascii=False)
print(json.dumps(res, indent=1, default=str, ensure_ascii=False))
