# T3 (SPEC3, frozen 2026-10-09): carry/yield strategies C1, C11, C16 vs 3-month T-bill (FRED DTB3) and $100 retail frictions.
# Strategy rules/costs are NOT re-implemented: the prior verified scripts (prior_code/C1_run.py, C11_run.py, C16_run.py)
# are executed verbatim except for their data/output paths (string substitution, asserted), and their functions are
# reused to obtain equity series. Step 0 checks that the reproduced result.json match prior_code/*_result.json (<=0.5%).
#
# T-bill method (fixed before looking at any T3 result):
#   DTB3 = discount-basis annualised %, business days; '.' (holidays) forward-filled; calendar day d uses the rate
#   published for the latest business day <= d-1 (causal). Discount d -> bond-equivalent (investment) yield
#   y = 365*d / (360 - 91*d); calendar-day growth g = 1 + y/365, compounded daily; intraday timestamps get the
#   fraction of the day (log-linear). T-bill CAGR is annualised on the SAME year basis the prior script uses for the
#   strategy (C1, C11: 365.25-day years; C16: 365-day years), so excess CAGR = strategy CAGR - T-bill CAGR is like-for-like.
#   Sensitivity (info only, verdict uses primary): raw discount rate compounded daily (d/365), and the SPEC3 fallback
#   path of annual averages.
# Sharpe-like: simple returns of the strategy equity at its prior-code daily marks (C1: last 8h close of each UTC day;
#   C11: 08:00 UTC daily marks; C16: DefiLlama daily snapshots, liquidation value), minus the T-bill simple return over
#   exactly the same interval; annualised = mean/std(ddof=1) * sqrt(n_obs / years_span).
# Verdict vs T-bill (carry/yield rule, SPEC3): FAIL if annualised excess net <= 0; PASS_CANDIDATE if excess > 0 AND
#   |maxDD| < 10% AND excess at 2x costs > 0 (strict reading: "positive at 2x costs" refers to the excess); otherwise
#   INCONCLUSIVE. Lenient reading (net at 2x costs > 0) reported as info. Applied mechanically on OOS (FULL for C16).
# $100 frictions: RUB->USDT leg costs c/2, USDT->RUB leg costs c/2 (round trip ~c), c in {2%, 3.5% (primary), 5%};
#   plus $1 network fee each way where funds are moved (C1 none: stays on one exchange; C11 Deribit $1 in/$1 out;
#   C16 $1 in/$1 out + $5 gas per round trip as in SPEC2, split $2.5/$2.5 exactly as the prior C16 script).
#   Holding period = whole OOS (C1, C11) / FULL (C16); strategy run at 1x costs.
import os, sys, io, json, math, contextlib, hashlib
import numpy as np
import pandas as pd

T3 = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.dirname(T3)
PRIOR = os.path.join(CTRL, "prior_code")
DATA = os.path.join(CTRL, "data")
REPRO = os.path.join(T3, "repro")
FRED = os.path.join(T3, "data_fred", "DTB3.csv")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3"
TOL = 0.005


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ------------------------------------------------------------------ step 0: reproduce prior code
def exec_prior(name, subs):
    src = open(os.path.join(PRIOR, f"{name}_run.py"), encoding="utf-8").read()
    for old, new in subs:
        assert src.count(old) == 1, (name, old)
        src = src.replace(old, new)
    d = os.path.join(REPRO, name)
    os.makedirs(d, exist_ok=True)
    ns = {"__name__": f"{name}_repro", "__file__": os.path.join(d, "run.py")}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(src, os.path.join(PRIOR, f"{name}_run.py"), "exec"), ns)
        if "main" in ns and name == "C1":
            ns["main"]()
    return ns, d


def compare(a, b, path="", out=None):
    """numeric leaves: rel diff <= TOL (or abs <= 1e-6); strings/bools: equality (paths skipped)."""
    if out is None:
        out = {"n_num": 0, "max_rel": 0.0, "max_rel_at": None, "bad": [], "n_other": 0}
    if isinstance(b, dict):
        for k in b:
            if k in ("file",):           # absolute paths of the original run
                continue
            if k not in a:
                out["bad"].append(f"missing {path}/{k}")
                continue
            compare(a[k], b[k], f"{path}/{k}", out)
    elif isinstance(b, list):
        if len(a) != len(b):
            out["bad"].append(f"len {path}: {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, f"{path}[{i}]", out)
    elif isinstance(b, bool) or isinstance(a, bool):
        out["n_other"] += 1
        if str(a) != str(b):
            out["bad"].append(f"{path}: {a} vs {b}")
    elif isinstance(b, (int, float)) and isinstance(a, (int, float)):
        out["n_num"] += 1
        if math.isinf(b) or math.isinf(a):
            if a != b:
                out["bad"].append(f"{path}: {a} vs {b}")
            return out
        ad = abs(a - b)
        rel = ad / abs(b) if b != 0 else (0.0 if ad <= 1e-12 else float("inf"))
        if ad > 1e-6 and rel > out["max_rel"]:
            out["max_rel"], out["max_rel_at"] = rel, path
        if ad > 1e-6 and rel > TOL:
            out["bad"].append(f"{path}: {a} vs {b} (rel {rel:.4g})")
    else:
        out["n_other"] += 1
        if a != b and b is not None:
            out["bad"].append(f"{path}: {a!r} vs {b!r}")
        elif a != b:
            out["bad"].append(f"{path}: {a!r} vs {b!r}")
    return out


c1, c1_dir = exec_prior("C1", [('DATA = os.path.join(HERE, "data")', f'DATA = r"{os.path.join(DATA, "C1")}"')])
c11, c11_dir = exec_prior("C11", [('D = os.path.join(W, "data")', f'D = r"{os.path.join(DATA, "C11")}"')])
c16, c16_dir = exec_prior("C16", [('DATA = os.path.join(BASE, "data")', f'DATA = r"{os.path.join(DATA, "C16")}"')])

repro = {}
for name, d in [("C1", c1_dir), ("C11", c11_dir), ("C16", c16_dir)]:
    new = json.load(open(os.path.join(d, "result.json"), encoding="utf-8"))
    old = json.load(open(os.path.join(PRIOR, f"{name}_result.json"), encoding="utf-8"))
    r = compare(new, old)
    repro[name] = {"numeric_leaves_compared": r["n_num"], "other_leaves_compared": r["n_other"],
                   "max_rel_diff": r["max_rel"], "max_rel_diff_at": r["max_rel_at"],
                   "mismatches": r["bad"][:20], "n_mismatches": len(r["bad"]),
                   "match_within_0.5pct": len(r["bad"]) == 0}
assert all(v["match_within_0.5pct"] for v in repro.values()), repro

# ------------------------------------------------------------------ T-bill index
fr = pd.read_csv(FRED, na_values=["."])
fr["observation_date"] = pd.to_datetime(fr["observation_date"])
dtb3 = fr.set_index("observation_date")["DTB3"].astype(float)
CAL = pd.date_range("2019-01-01", "2026-10-10", freq="D")
rate_pub = dtb3.reindex(pd.date_range(dtb3.index.min(), CAL[-1], freq="D")).ffill()
rate_day = rate_pub.shift(1).reindex(CAL)          # day d uses latest published rate <= d-1
assert rate_day.notna().all()


def bey(dpct):
    d = dpct / 100.0
    return 365.0 * d / (360.0 - 91.0 * d)


FALLBACK = {2019: 2.1, 2020: 0.4, 2021: 0.05, 2022: 2.0, 2023: 5.0, 2024: 5.0, 2025: 4.2, 2026: 3.8}


def make_index(daily_growth):
    lg = np.log(daily_growth.values)
    L = np.concatenate([[0.0], np.cumsum(lg)])     # L[i] = log index at midnight starting CAL[i]
    days_ns = CAL.values.astype("datetime64[ns]").astype(np.int64)

    def L_at(ts):
        ts = pd.DatetimeIndex(pd.to_datetime(ts, utc=True)).tz_convert(None)
        x = ts.values.astype("datetime64[ns]").astype(np.int64)
        i = np.searchsorted(days_ns, x, side="right") - 1
        assert (i >= 0).all() and (i < len(CAL) - 1).all()
        frac = (x - days_ns[i]) / 86400e9
        return L[i] + frac * lg[i]
    return L_at


TB = {
    "primary_BEY_daily": make_index(1 + bey(rate_day) / 365.0),
    "info_discount_rate_daily": make_index(1 + rate_day / 100.0 / 365.0),
    "info_fallback_annual_path": make_index(pd.Series([(1 + FALLBACK[y] / 100.0) ** (1 / 365.0) for y in CAL.year], index=CAL)),
    # added AFTER seeing the primary result (post-hoc, info only): rolling 91-day bill = BEY compounded per 91 days
    "info_posthoc_quarterly_roll": make_index((1 + bey(rate_day) * 91 / 365.0) ** (1 / 91.0)),
}


def tb_cagr(t0, t1, years, which="primary_BEY_daily"):
    L = TB[which]
    g = float(np.exp(L([t1])[0] - L([t0])[0]))
    return (g ** (1 / years) - 1) * 100, (g - 1) * 100


def sharpe_excess(times, eq):
    times = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    eq = np.asarray(eq, dtype=float)
    rs = eq[1:] / eq[:-1] - 1
    Lt = TB["primary_BEY_daily"](times)
    rtb = np.exp(np.diff(Lt)) - 1
    ex = rs - rtb
    span = (times[-1] - times[0]) / pd.Timedelta(days=365.25)
    k = len(ex) / span
    sd = ex.std(ddof=1)
    return {"sharpe_excess_ann": float(ex.mean() / sd * math.sqrt(k)) if sd > 0 else None,
            "mean_daily_excess_bp": float(ex.mean() * 1e4), "vol_excess_ann_pct": float(sd * math.sqrt(k) * 100),
            "n_obs": int(len(ex)), "obs_per_year": float(k)}


def maxdd_pct(eq):
    eq = np.asarray(eq, dtype=float)
    return float((eq / np.maximum.accumulate(eq) - 1).min() * 100)


def verdict(exc, exc2, dd, net2):
    strict = "FAIL" if exc <= 0 else ("PASS_CANDIDATE" if (abs(dd) < 10 and exc2 > 0) else "INCONCLUSIVE")
    lenient = "FAIL" if exc <= 0 else ("PASS_CANDIDATE" if (abs(dd) < 10 and net2 > 0) else "INCONCLUSIVE")
    return strict, lenient


rows = {}

# ------------------------------------------------------------------ C1
data1 = {s: c1["load_asset"](s) for s in c1["ASSETS"]}
start1 = max(d[0].index[0] for d in data1.values())
last1 = min(d[0].index[-1] for d in data1.values())
H8 = c1["H8"]
win1 = {"IS": (start1, c1["IS_END"] - H8), "OOS": (c1["IS_END"], last1), "FULL": (start1, last1)}
c1_mult = {}
for lab, (a, b) in win1.items():
    m, _, eq_total, trs = c1["run_window"](data1, a, b, 1.0)
    m2, _, _, _ = c1["run_window"](data1, a, b, 2.0)
    daily = eq_total.groupby((eq_total.index - pd.Timedelta(milliseconds=1)).floor("D")).last()
    times = [a] + list(daily.index + pd.Timedelta(days=1))
    eq = [100.0] + list(daily.values)
    dd = maxdd_pct(eq)
    assert abs(dd - m["max_dd_pct"]) < 1e-9
    end = b + H8
    yrs = m["years"]
    tbc, tbtot = tb_cagr(a, end, yrs)
    exc, exc2 = m["cagr_pct"] - tbc, m2["cagr_pct"] - tbc
    s, l = verdict(exc, exc2, dd, m2["net_return_pct"])
    rows[("C1", lab)] = dict(start=str(a), end=str(end), years=yrs, net_pct=m["net_return_pct"], cagr_pct=m["cagr_pct"],
                             max_dd_pct=dd, pf=m["pf"], trades=m["trades"], exposure_pct=m["exposure_pct"],
                             net_2x_pct=m2["net_return_pct"], cagr_2x_pct=m2["cagr_pct"],
                             tbill_cagr_pct=tbc, tbill_total_pct=tbtot, excess_cagr_pct=exc, excess_cagr_2x_pct=exc2,
                             **sharpe_excess(times, eq), verdict_vs_tbill=s, verdict_vs_tbill_lenient=l,
                             info_excess_cagr_discount_basis=m["cagr_pct"] - tb_cagr(a, end, yrs, "info_discount_rate_daily")[0],
                             info_excess_cagr_fallback_path=m["cagr_pct"] - tb_cagr(a, end, yrs, "info_fallback_annual_path")[0])
    c1_mult[lab] = 1 + m["net_return_pct"] / 100

# ------------------------------------------------------------------ C11
c11_mult = {}
for lab, wk in c11["periods"].items():
    eq, tr = c11["simulate"](wk)
    eq2, tr2 = c11["simulate"](wk, haircut=1 - 2 * 0.15, fee_mult=2.0)
    t0, t1 = wk[0]["entry"], wk[-1]["expiry"]
    yrs = (t1 - t0) / pd.Timedelta(days=365.25)
    net = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    net2 = (eq2.iloc[-1] / eq2.iloc[0] - 1) * 100
    cagr = ((1 + net / 100) ** (1 / yrs) - 1) * 100
    cagr2 = ((1 + net2 / 100) ** (1 / yrs) - 1) * 100
    dd = maxdd_pct(eq.values)                        # same as prior (includes the post-sale model-mid mark)
    pm = c11["res"]["periods"][lab]
    assert abs(round(net, 2) - pm["net_return_pct"]) < 0.011 and abs(round(dd, 2) - pm["max_dd_pct"]) < 0.011
    d08 = eq[(eq.index.hour == 8) & (eq.index.minute == 0) & (eq.index.second == 0)]
    assert d08.index[0] == t0 and d08.index[-1] == t1
    wins = tr.loc[tr.pnl > 0, "pnl"].sum(); los = -tr.loc[tr.pnl < 0, "pnl"].sum()
    tbc, tbtot = tb_cagr(t0, t1, yrs)
    exc, exc2 = cagr - tbc, cagr2 - tbc
    s, l = verdict(exc, exc2, dd, net2)
    rows[("C11", lab)] = dict(start=str(t0), end=str(t1), years=float(yrs), net_pct=float(net), cagr_pct=float(cagr),
                              max_dd_pct=dd, pf=float(wins / los), trades=int(len(tr)), exposure_pct=100.0,
                              net_2x_pct=float(net2), cagr_2x_pct=float(cagr2),
                              tbill_cagr_pct=tbc, tbill_total_pct=tbtot, excess_cagr_pct=float(exc), excess_cagr_2x_pct=float(exc2),
                              **sharpe_excess(d08.index, d08.values), verdict_vs_tbill=s, verdict_vs_tbill_lenient=l,
                              info_excess_cagr_discount_basis=float(cagr - tb_cagr(t0, t1, yrs, "info_discount_rate_daily")[0]),
                              info_excess_cagr_fallback_path=float(cagr - tb_cagr(t0, t1, yrs, "info_fallback_annual_path")[0]),
                              info_bench_btc_bh=pm["bench_btc"], proxy_note="PROXY: DVOL-based option prices, not real quotes")
    c11_mult[lab] = float(eq.iloc[-1] / eq.iloc[0])

# ------------------------------------------------------------------ C16 (FULL only)
t16 = pd.DatetimeIndex(pd.to_datetime(c16["t"], utc=True))
yrs16 = float(c16["years"])                          # prior basis: days/365
G16 = float(c16["gross_mult"])
for cap in (10000.0, 100.0):
    r1 = c16["run"](cap, c16["GAS_1X"])
    r2 = c16["run"](cap, 2 * c16["GAS_1X"])
    eq_full = r1["eq"]                               # [capital before deposit] + liquidation value at each snapshot
    times = list(t16)
    eq_s = [cap] + list(eq_full[2:])                 # deposit gas attached to the first interval
    tbc, tbtot = tb_cagr(t16[0], t16[-1], yrs16)
    exc, exc2 = r1["cagr_pct"] - tbc, r2["cagr_pct"] - tbc
    s, l = verdict(exc, exc2, r1["maxdd_pct"], r2["net_pct"])
    usdt = c16["usd_diag"][str(int(cap))]
    rows[("C16", f"FULL_${int(cap)}")] = dict(start=str(t16[0]), end=str(t16[-1]), years=yrs16, net_pct=r1["net_pct"],
                                             cagr_pct=r1["cagr_pct"], max_dd_pct=r1["maxdd_pct"], pf=r1["pf"], trades=1,
                                             exposure_pct=100.0, net_2x_pct=r2["net_pct"], cagr_2x_pct=r2["cagr_pct"],
                                             tbill_cagr_pct=tbc, tbill_total_pct=tbtot, excess_cagr_pct=exc,
                                             excess_cagr_2x_pct=exc2, **sharpe_excess(times, eq_s),
                                             verdict_vs_tbill=s, verdict_vs_tbill_lenient=l,
                                             info_excess_cagr_discount_basis=r1["cagr_pct"] - tb_cagr(t16[0], t16[-1], yrs16, "info_discount_rate_daily")[0],
                                             info_excess_cagr_fallback_path=r1["cagr_pct"] - tb_cagr(t16[0], t16[-1], yrs16, "info_fallback_annual_path")[0],
                                             info_gross_cagr_pct=float(c16["gross_cagr"] * 100),
                                             info_maxdd_usdt_marked_pct=usdt["maxdd_pct_usdt_marked_daily_close"])

for key, v in rows.items():
    a_, b_ = pd.Timestamp(v["start"]), pd.Timestamp(v["end"])
    v["info_posthoc_excess_cagr_quarterly_roll"] = float(v["cagr_pct"] - tb_cagr(a_, b_, v["years"], "info_posthoc_quarterly_roll")[0])
    alts = [v["info_excess_cagr_discount_basis"], v["info_excess_cagr_fallback_path"], v["info_posthoc_excess_cagr_quarterly_roll"]]
    v["info_excess_range_all_tbill_conventions_pp"] = [float(min(alts + [v["excess_cagr_pct"]])), float(max(alts + [v["excess_cagr_pct"]]))]
    v["info_verdict_flips_under_alt_tbill"] = bool(any((x > 0) != (v["excess_cagr_pct"] > 0) for x in alts))

# ------------------------------------------------------------------ $100 retail frictions
def frictions(mult_fn, c, fee_in, fee_out):
    x = 100.0 * (1 - c / 2) - fee_in                 # USDT arriving at the venue
    y = mult_fn(x) - fee_out                         # USDT back at the exchange
    return y * (1 - c / 2)


fric = {}
FR = [0.02, 0.035, 0.05]
specs = {
    "C1": dict(period="OOS", years=rows[("C1", "OOS")]["years"], start=rows[("C1", "OOS")]["start"], end=rows[("C1", "OOS")]["end"],
               fn=lambda x: x * c1_mult["OOS"], fee_in=0.0, fee_out=0.0,
               moves="нет on-chain переводов (P2P-покупка USDT и стратегия на одной бирже)"),
    "C11": dict(period="OOS", years=rows[("C11", "OOS")]["years"], start=rows[("C11", "OOS")]["start"], end=rows[("C11", "OOS")]["end"],
                fn=lambda x: x * c11_mult["OOS"], fee_in=1.0, fee_out=1.0, moves="перевод на Deribit $1 туда / $1 обратно"),
    "C16": dict(period="FULL", years=yrs16, start=str(t16[0]), end=str(t16[-1]),
                fn=lambda x: (x - c16["GAS_1X"] / 2) * G16 - c16["GAS_1X"] / 2, fee_in=1.0, fee_out=1.0,
                moves="сеть $1 туда / $1 обратно + газ $5 за круг (2.5+2.5, как в SPEC2)"),
}
for k, sp in specs.items():
    if k == "C16":
        tbc = tb_cagr(t16[0], t16[-1], yrs16)[0]
        no_fric = sp["fn"](100.0)
    else:
        rr = rows[(k, sp["period"])]
        tbc = rr["tbill_cagr_pct"]
        no_fric = sp["fn"](100.0)
    out = {"period": sp["period"], "start": sp["start"], "end": sp["end"], "years": sp["years"], "moves": sp["moves"],
           "tbill_cagr_pct": tbc, "final_no_frictions_usd": no_fric,
           "ann_no_frictions_pct": ((no_fric / 100) ** (1 / sp["years"]) - 1) * 100, "scenarios": {}}
    for c in FR:
        f = frictions(sp["fn"], c, sp["fee_in"], sp["fee_out"])
        ann = ((f / 100) ** (1 / sp["years"]) - 1) * 100
        out["scenarios"][f"{c*100:.1f}%"] = {"final_usd": f, "ann_net_pct": ann, "excess_vs_tbill_pp": ann - tbc,
                                             "beats_tbill": bool(ann > tbc), "net_positive": bool(f > 100)}
    # break-even round-trip cost vs T-bill (bisection), info
    def gap(c):
        f = frictions(sp["fn"], c, sp["fee_in"], sp["fee_out"])
        return ((f / 100) ** (1 / sp["years"]) - 1) * 100 - tbc
    if gap(0.0) <= 0:
        out["breakeven_roundtrip_cost_vs_tbill_pct"] = None
        out["breakeven_note"] = "даже при 0% конвертации и только сетевых комиссиях не обгоняет T-bill"
    else:
        lo, hi = 0.0, 0.99
        for _ in range(60):
            mid = (lo + hi) / 2
            if gap(mid) > 0: lo = mid
            else: hi = mid
        out["breakeven_roundtrip_cost_vs_tbill_pct"] = lo * 100
    fric[k] = out

# ------------------------------------------------------------------ $100 feasibility (as already established + trivial filter read)
fx = json.load(open(os.path.join(DATA, "C1", "fapi_exchangeInfo.json")))
filt = {s["symbol"]: {f["filterType"]: f for f in s["filters"]} for s in fx}
last_btc = float(data1["BTCUSDT"][0]["s_close"].iloc[-1]); last_eth = float(data1["ETHUSDT"][0]["s_close"].iloc[-1])
feas = {
    "C1": {"feasible_at_100": False,
           "why": (f"на $100: рукав $50 на актив, шорт-перп = 50% рукава = $25. BTCUSDT-перп: MIN_NOTIONAL "
                   f"{filt['BTCUSDT']['MIN_NOTIONAL']['notional']} USDT и minQty {filt['BTCUSDT']['LOT_SIZE']['minQty']} BTC "
                   f"(~${0.001*last_btc:.0f} по последнему close) -> BTC-нога невыполнима; ETHUSDT-перп: MIN_NOTIONAL "
                   f"{filt['ETHUSDT']['MIN_NOTIONAL']['notional']} USDT, minQty 0.001 ETH (~${0.001*last_eth:.1f}) -> ETH-нога выполнима. "
                   f"Правило 50/50 BTC/ETH целиком на $100 не исполнимо; минимум для BTC-ноги ~${2*2*max(50, 0.001*last_btc):.0f} капитала.")},
    "C11": {"feasible_at_100": False,
            "why": (f"Deribit: минимальный контракт 0.1 BTC (SPEC2) -> обеспечение 0.1*0.95*спот ~ ${0.1*0.95*last_btc:,.0f} "
                    f"по последнему close; с $100 невозможно (доля контракта не продаётся).")},
    "C16": {"feasible_at_100": True,
            "why": ("Aave v3 без минимума депозита -> технически да, но газ $5 за круг = 5% капитала; "
                    f"прежний расчёт: безубыток $100 за {c16['breakeven_years_100']:.2f} г. при ставке последних 365 дней.")},
}

# ------------------------------------------------------------------ survivors
primary = {"C1": ("C1", "OOS"), "C11": ("C11", "OOS"), "C16_10000": ("C16", "FULL_$10000"), "C16_100": ("C16", "FULL_$100")}
survivors = [k for k, key in primary.items() if rows[key]["verdict_vs_tbill"] == "PASS_CANDIDATE"]
retail_survivors = [k for k in fric if fric[k]["scenarios"]["3.5%"]["beats_tbill"] and feas[k]["feasible_at_100"]]

result = {
    "test": "T3 carry/yield vs 3M T-bill (FRED DTB3) and $100 retail frictions",
    "reproduction_check": repro,
    "tbill_source": {"url": FRED_URL, "file": "data_fred/DTB3.csv", "sha256": sha(FRED), "fallback_used": False,
                     "last_obs": str(dtb3.dropna().index[-1].date()),
                     "annual_mean_dtb3_pct": {int(y): round(float(v), 3) for y, v in dtb3["2019":"2026-10-06"].groupby(dtb3["2019":"2026-10-06"].index.year).mean().items()},
                     "method": "discount->BEY y=365d/(360-91d), calendar-day growth 1+y/365 compounded; day d uses rate of last business day <= d-1"},
    "rows": {f"{k[0]}|{k[1]}": v for k, v in rows.items()},
    "frictions_100usd": fric,
    "feasibility_100usd": feas,
    "primary_period": {k: f"{v[0]}|{v[1]}" for k, v in primary.items()},
    "survivors_vs_tbill": survivors,
    "survivors_retail_100usd_3.5pct": retail_survivors,
}
def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


json.dump(clean(result), open(os.path.join(T3, "result.json"), "w", encoding="utf-8"), indent=1, default=str,
          ensure_ascii=False, allow_nan=False)

# ------------------------------------------------------------------ print summary
print("REPRO", {k: (v["match_within_0.5pct"], v["numeric_leaves_compared"], f"{v['max_rel_diff']:.2e}") for k, v in repro.items()})
cols = ["net_pct", "cagr_pct", "tbill_cagr_pct", "excess_cagr_pct", "excess_cagr_2x_pct", "max_dd_pct", "sharpe_excess_ann",
        "net_2x_pct", "verdict_vs_tbill", "verdict_vs_tbill_lenient", "info_excess_cagr_discount_basis", "info_excess_cagr_fallback_path",
        "info_posthoc_excess_cagr_quarterly_roll", "info_verdict_flips_under_alt_tbill", "vol_excess_ann_pct", "n_obs"]
for k, v in rows.items():
    print(k, {c: (round(v[c], 3) if isinstance(v[c], float) else v[c]) for c in cols})
for k, v in fric.items():
    print("FRIC", k, round(v["final_no_frictions_usd"], 2), round(v["ann_no_frictions_pct"], 2), "tb", round(v["tbill_cagr_pct"], 3),
          {s: (round(x["final_usd"], 2), round(x["ann_net_pct"], 2), round(x["excess_vs_tbill_pp"], 2)) for s, x in v["scenarios"].items()},
          "BE", v.get("breakeven_roundtrip_cost_vs_tbill_pct"))
print("SURVIVORS", survivors, "RETAIL", retail_survivors)
