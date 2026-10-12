# -*- coding: utf-8 -*-
"""
SPEC3 / T2 -- OOS-start sensitivity on rolling 3-year windows (frozen 2026-10-09).

Strategies: S1 (DCA, only vs B&H), S2 (BTC 40W SMA), S6 (BTC/ETH 50/50 40W)  -- rules from data/SPEC.md
            C2 (funding overheat filter), C5 (Fear&Greed), C9 (4h 55/20 breakout) -- rules from data/SPEC2.md
Benchmarks (as in the original specs): S1,S2 -> BH_BTC (S0); S6 -> BH_50_50 (S0d);
            C2, C5 -> BTC buy&hold; C9 -> equal-weight BTC/ETH/SOL buy&hold (SOL sleeve in cash until listing).

Stage 0: copy prior verified code + data into sandbox dirs (repro/*), run the prior scripts unchanged,
         compare their outputs with prior_code/*_result.json and prior_code/weekly_final_rows.json (tol 0.5%).
Stage 1: import the SAME prior modules (no strategy re-implementation, no parameter changes) and run
         21 quarterly-start windows 2018-07-01 .. 2023-07-01:
           weekly strategies: 156 weeks from the first Monday on/after the quarter start (engine trades only on Mondays)
           C2 / C5: 1095 calendar days from the quarter start (daily engine)
           C9: 1095 days (4h bars with open >= start and close <= start+1095d)
         Each window starts with $100 (cash), indicators/state warmed up on prior data exactly as in the
         original code (S2/S6: weekly SMA from full history; C2/C9: continuous signal state from full history;
         C5: frozen rule "start in USDT", i.e. fresh start each window = original primary convention;
         continuous-state C5 reported as info).
Verdict per window: SPEC2 rule (FAIL / INCONCLUSIVE / PASS_CANDIDATE); trade-count (<30) rule only for C9.
"""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(CTRL, "data")
PRIOR = os.path.join(CTRL, "prior_code")
REPRO = os.path.join(HERE, "repro")

TOL_REL = 0.005       # 0.5% reproduction tolerance (relative)
TOL_ABS = 0.011       # absolute slack for values that were rounded to 2 decimals in prior outputs
TIE_PP = 0.01         # percentage-point tolerance for "worse than benchmark on max DD" ties
QSTARTS = pd.date_range("2018-07-01", "2023-07-01", freq="QS")
WIN_WEEKS = 156
WIN_DAYS = 1095


# ============================================================================ stage 0: reproduction
def setup_sandbox():
    os.makedirs(REPRO, exist_ok=True)
    # weekly implA: DATA = parent of script dir
    wdir = os.path.join(REPRO, "weekly")
    os.makedirs(os.path.join(wdir, "impl"), exist_ok=True)
    for f in ("BTCUSDT_1d.csv", "ETHUSDT_1d.csv", "SOLUSDT_1d.csv"):
        shutil.copy2(os.path.join(DATA, f), os.path.join(wdir, f))
    shutil.copy2(os.path.join(PRIOR, "weekly_implA.py"), os.path.join(wdir, "impl", "weekly_implA.py"))
    # C-strategies: BASE/data
    for c in ("C2", "C5", "C9"):
        d = os.path.join(REPRO, c)
        os.makedirs(os.path.join(d, "data"), exist_ok=True)
        for f in os.listdir(os.path.join(DATA, c)):
            shutil.copy2(os.path.join(DATA, c, f), os.path.join(d, "data", f))
        shutil.copy2(os.path.join(PRIOR, f"{c}_run.py"), os.path.join(d, f"{c}_run.py"))


def run_script(path):
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.basename(path)], cwd=os.path.dirname(path),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"{path} failed:\n{p.stderr[-3000:]}")
    return round(time.time() - t0, 1)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def compare(a, b, path="", out=None, skip=("file", "self_checks", "data_sources", "independent_verification",
                                           "notes", "url")):
    """Compare numeric leaves of b (reproduced) vs a (prior). Returns stats dict."""
    if out is None:
        out = dict(n_num=0, n_num_bad=0, max_rel=0.0, bad=[], n_str=0, n_str_bad=0, str_bad=[], missing=[])
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in skip:
                continue
            if k not in b:
                out["missing"].append(path + "/" + str(k))
                continue
            compare(a[k], b[k], path + "/" + str(k), out, skip)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out["bad"].append(f"{path}: list len {len(a)} vs {len(b)}")
            out["n_num_bad"] += 1
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, f"{path}[{i}]", out, skip)
    elif is_num(a) and is_num(b):
        out["n_num"] += 1
        d = abs(a - b)
        rel = d / max(abs(a), abs(b)) if max(abs(a), abs(b)) > 0 else 0.0
        if not (d <= TOL_ABS or rel <= TOL_REL):
            out["n_num_bad"] += 1
            out["bad"].append(f"{path}: prior={a} repro={b}")
        if d > TOL_ABS:
            out["max_rel"] = max(out["max_rel"], rel)
    elif a is None or b is None:
        if (a is None) != (b is None):
            out["n_num_bad"] += 1
            out["bad"].append(f"{path}: prior={a} repro={b}")
    else:
        out["n_str"] += 1
        if str(a) != str(b):
            out["n_str_bad"] += 1
            out["str_bad"].append(f"{path}: prior={a} repro={b}")
    return out


def reproduce():
    setup_sandbox()
    rep = {}
    # weekly
    t = run_script(os.path.join(REPRO, "weekly", "impl", "weekly_implA.py"))
    new = json.load(open(os.path.join(REPRO, "weekly", "impl", "results.json"), encoding="utf-8"))
    old = json.load(open(os.path.join(PRIOR, "weekly_final_rows.json"), encoding="utf-8"))
    old_p = [r for r in old if r["variant"] == "primary"]
    key = lambda r: (r["strategy"], r["period"])
    nmap = {key(r): r for r in new["rows"]}
    cmp_ = None
    for r in old_p:
        cmp_ = compare(r, nmap.get(key(r), {}), f"{r['strategy']}/{r['period']}", cmp_)
    rep["weekly_implA (S0..S6 primary, 30 rows)"] = dict(runtime_s=t, rows_compared=len(old_p),
                                                         **{k: v for k, v in cmp_.items() if k not in ("bad", "str_bad")},
                                                         bad=cmp_["bad"][:20], str_bad=cmp_["str_bad"][:20],
                                                         common_start=new["common_start"])
    for c in ("C2", "C5", "C9"):
        t = run_script(os.path.join(REPRO, c, f"{c}_run.py"))
        new = json.load(open(os.path.join(REPRO, c, "result.json"), encoding="utf-8"))
        old = json.load(open(os.path.join(PRIOR, f"{c}_result.json"), encoding="utf-8"))
        cm = compare(old, new, c)
        rep[c] = dict(runtime_s=t, **{k: v for k, v in cm.items() if k not in ("bad", "str_bad")},
                      bad=cm["bad"][:20], str_bad=cm["str_bad"][:20],
                      verdict_prior=old.get("verdict") if c != "C9" else old["verdict"]["verdict"],
                      verdict_repro=new.get("verdict") if c != "C9" else new["verdict"]["verdict"])
    ok = all(v["n_num_bad"] == 0 and v["n_str_bad"] == 0 for v in rep.values())
    return ok, rep


# ============================================================================ helpers
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    cwd = os.getcwd()
    os.chdir(os.path.dirname(path))
    try:
        spec.loader.exec_module(m)
    finally:
        os.chdir(cwd)
    return m


def ratio(net, mdd):
    if mdd is None or mdd == 0:
        return math.inf if net > 0 else (0.0 if net == 0 else -math.inf)
    return net / abs(mdd)


def verdict(r, trade_rule):
    """SPEC2 pre-registered rule, applied mechanically to one window.
    pf: float, math.inf (no losing trades) or None (not applicable: S1 DCA never sells)."""
    reasons = []
    pf = r["pf"]
    if r["net"] <= 0:
        reasons.append("net<=0")
    if pf is not None and pf < 1.0:
        reasons.append("PF<1")
    if r["net"] < r["b_net"] - TIE_PP and r["mdd"] < r["b_mdd"] - TIE_PP:
        reasons.append("worse_both")
    if reasons:
        return "FAIL", reasons
    if trade_rule and r["trades"] < 30:
        return "INCONCLUSIVE", ["trades<30"]
    crit = dict(net_pos=r["net"] > 0, pf_ok=(pf is None or pf >= 1.2), ratio_beats=r["ratio"] > r["b_ratio"],
                net2x_pos=r["net2x"] > 0)
    if all(crit.values()):
        return "PASS_CANDIDATE", []
    return "INCONCLUSIVE", [k for k, v in crit.items() if not v]


def finish_row(r):
    r["ratio"] = ratio(r["net"], r["mdd"])
    r["b_ratio"] = ratio(r["b_net"], r["b_mdd"])
    r["cagr_dd"] = ratio(r["cagr"], r["mdd"])
    r["b_cagr_dd"] = ratio(r["b_cagr"], r["b_mdd"])
    return r


# ============================================================================ weekly strategies (SPEC)
def weekly_pf(W, mkt, res):
    """Round-trip $ P&L per book/asset; open position at window end valued at last close net of exit cost."""
    pnl, open_ = [], {}
    for t in res["log"]:
        k = (t["book"], t["asset"])
        if t["side"] == "BUY":
            open_.setdefault(k, [0.0, 0.0])
            open_[k][0] += t["notional"]
            open_[k][1] += t["qty"]
        else:
            spent, q = open_.pop(k)
            pnl.append(t["notional"] - t["cost"] - spent)
    for (book, a), (spent, q) in open_.items():
        pnl.append(q * mkt["close"][a][res["p1"]] * (1 - W.COST_RATE) - spent)
    pnl = np.array(pnl)
    gw, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    if gl > 0:
        return float(gw / gl), len(pnl)
    return (math.inf if gw > 0 else 0.0), len(pnl)


def weekly_window(W, mkt, name, bench, p0, p1, pf_applicable=True):
    fac = W.STRATS[name][0]
    bfac = W.STRATS[bench][0]
    base_cost = W.COST_RATE
    res = W.run(mkt, fac, p0, p1)
    m = W.metrics(mkt, res)
    pf, n_rt = weekly_pf(W, mkt, res)
    W.COST_RATE = 2 * base_cost
    try:
        res2 = W.run(mkt, fac, p0, p1)
    finally:
        W.COST_RATE = base_cost
    bres = W.run(mkt, bfac, p0, p1)
    bm = W.metrics(mkt, bres)
    r = dict(start=m["start"], end=m["end"], days=m["days"],
             net=m["final_value"] - 100.0, mdd=m["max_dd_pct"], cagr=m["cagr_pct"],
             net2x=res2["eq"][-1] - 100.0, trades=m["trades"], round_trips=n_rt,
             pf=(pf if pf_applicable else None), exposure=m["time_in_market_pct"],
             b_net=bm["final_value"] - 100.0, b_mdd=bm["max_dd_pct"], b_cagr=bm["cagr_pct"])
    return finish_row(r)


def run_weekly(W):
    mkt = W.build_market()
    dates = mkt["dates"]
    pos = mkt["pos"]
    p_end = pos[W.LAST_DAY]
    need = ["BTC_wclose", "BTC_sma40", "BTC_rsi14", "BTC_ret12", "ETH_wclose", "ETH_sma40", "ETH_ret12"]
    ok = np.ones(len(dates), bool)
    for k in need:
        ok &= np.isfinite(mkt["sig"][k])
    p_common = int(np.argmax(ok)) + 1
    out = {}
    specs = [("S1_DCA_BTC_52W", "S0_BH_BTC", False), ("S2_TREND_BTC_40W", "S0_BH_BTC", True),
             ("S6_TREND_50_50_40W", "S0d_BH_50_50", True)]
    for name, bench, pfa in specs:
        rows, skipped = [], []
        for q in QSTARTS:
            p0 = pos[q] + ((7 - q.weekday()) % 7)        # first Monday on/after quarter start
            p1 = p0 + 7 * WIN_WEEKS - 1
            if p0 < p_common:
                skipped.append((str(q.date()), "before common warm-up start"))
                continue
            if p1 > p_end:
                skipped.append((str(q.date()), "window beyond last usable day"))
                continue
            r = weekly_window(W, mkt, name, bench, p0, p1, pfa)
            r["q"] = str(q.date())
            rows.append(r)
        # reference: original SPEC OOS (2022-01-03 .. 2026-10-06), same rule
        ref = weekly_window(W, mkt, name, bench, pos[W.OOS_START], p_end, pfa)
        out[name] = dict(bench=bench, rows=rows, skipped=skipped, ref_oos=ref,
                         common_start=str(dates[p_common].date()))
    return out


# ============================================================================ C2
def run_c2(C2):
    fund, kl = C2.load()
    first_full = (fund["t"].min() + C2.WIN).ceil("D")
    dates = kl.index[kl.index >= first_full]
    sig = C2.compute_signal(fund, dates)
    pos = C2.state_machine(sig)
    end_all = kl.index[-1]

    def one(s, e):
        m = C2.run_period(kl, pos, s, e, "W")
        pf = m["pf"]
        if pf is None:
            pf = math.inf if m["trades"] > 0 and all(t["ret_pct"] > 0 for t in m["trade_list"]) else 0.0
        r = dict(start=m["start"], end=m["end"], days=m["n_days"], net=m["net_return_pct"], mdd=m["max_dd_pct"],
                 cagr=m["cagr_pct"], net2x=m["net_return_2x_cost_pct"], trades=m["trades"], pf=pf,
                 exposure=m["exposure_pct"], b_net=m["bench_net_return_pct"], b_mdd=m["bench_max_dd_pct"],
                 b_cagr=m["bench_cagr_pct"])
        return finish_row(r)

    rows, skipped = [], []
    for q in QSTARTS:
        s = pd.Timestamp(q, tz="UTC")
        e = s + pd.Timedelta(days=WIN_DAYS - 1)
        if s < dates[0]:
            skipped.append((str(q.date()), f"before first full 7-day funding window {dates[0].date()}"))
            continue
        if e > end_all:
            skipped.append((str(q.date()), "beyond data"))
            continue
        r = one(s, e)
        r["q"] = str(q.date())
        rows.append(r)
    ref = one(C2.OOS_START, min(C2.OOS_END, end_all))
    return dict(bench="BTC buy&hold (buy first open, sell last close, 20 bps/side)", rows=rows, skipped=skipped,
                ref_oos=ref, eval_start=str(dates[0].date()))


# ============================================================================ C5
def c5_sim_init(C5, start, end, cost, init_long):
    """Continuous-state variant (INFO ONLY): identical to C5.simulate except that on the first day of the window the
    position is set to the continuous FULL-history state for that day (state after that day's open signal);
    if long, BTC is bought with the $100 at the first open (cost applied). Later days follow the frozen rule."""
    days = C5.k.loc[start:end].index
    cash, units, long_ = 1.0, 0.0, False
    eq = []
    pnl = []
    cash_in = None
    for i, t in enumerate(days):
        o = C5.k.at[t, "open"]
        if i == 0:
            if init_long:
                units = cash * (1 - cost) / o; cash_in = cash; cash = 0.0; long_ = True
        else:
            sig_date = t - pd.Timedelta(days=1)
            if sig_date in C5.fgi.index:
                v = C5.fgi[sig_date]
                if (not long_) and v <= C5.BUY_LVL:
                    units = cash * (1 - cost) / o; cash_in = cash; cash = 0.0; long_ = True
                elif long_ and v >= C5.SELL_LVL:
                    cash = units * o * (1 - cost); pnl.append(cash - cash_in); units = 0.0; long_ = False
        eq.append(cash + units * C5.k.at[t, "close"])
    eq = pd.Series(eq, index=days)
    if long_:
        cash = units * C5.k.at[days[-1], "close"] * (1 - cost); pnl.append(cash - cash_in); eq.iloc[-1] = cash
    return eq, pnl


def run_c5(C5):
    eqF, heldF, _ = C5.simulate(C5.FIRST_FGI, C5.CUTOFF, C5.COST)   # continuous state (info)

    def one(s, e):
        eq, held, tr = C5.simulate(s, e, C5.COST)
        eq2, _, _ = C5.simulate(s, e, 2 * C5.COST)
        b = C5.bench(s, e, C5.COST)
        m = C5.metrics(eq, held, tr)
        bm = C5.metrics(b)
        pf = m["pf"]
        if pf is None:
            pf = 0.0       # no trades / no P&L -> treated as no edge (net=0 -> FAIL anyway)
        r = dict(start=str(s.date()), end=str(e.date()), days=m["days"], net=m["net_return_pct"],
                 mdd=m["max_dd_pct"], cagr=m["cagr_pct"], net2x=(eq2.iloc[-1] - 1) * 100, trades=m["trades"],
                 pf=float(pf), exposure=m["exposure_pct"], b_net=bm["net_return_pct"], b_mdd=bm["max_dd_pct"],
                 b_cagr=bm["cagr_pct"], start_state_continuous=("BTC" if bool(heldF.loc[s]) else "USDT"))
        r = finish_row(r)
        # info: continuous-state variant
        init_long = r["start_state_continuous"] == "BTC"
        eqc, pnlc = c5_sim_init(C5, s, e, C5.COST, init_long)
        mc = C5.metrics(eqc)
        r["cont_net"] = mc["net_return_pct"]
        r["cont_mdd"] = mc["max_dd_pct"]
        r["cont_ratio"] = ratio(mc["net_return_pct"], mc["max_dd_pct"])
        return r

    rows, skipped = [], []
    for q in QSTARTS:
        s = pd.Timestamp(q)
        e = s + pd.Timedelta(days=WIN_DAYS - 1)
        if s < C5.FIRST_FGI:
            skipped.append((str(q.date()), "before first FGI"))
            continue
        if e > C5.CUTOFF:
            skipped.append((str(q.date()), "beyond data"))
            continue
        r = one(s, e)
        r["q"] = str(q.date())
        rows.append(r)
    ref = one(C5.OOS_START, C5.CUTOFF)
    return dict(bench="BTC buy&hold (buy first open, sell last close, 20 bps/side)", rows=rows, skipped=skipped,
                ref_oos=ref)


# ============================================================================ C9
def run_c9(C9):
    cwd = os.getcwd()
    os.chdir(os.path.dirname(C9.__file__))
    try:
        data = {}
        for sym in C9.SYMS:
            df, _ = C9.load(sym)
            tgt, _, _ = C9.signals(df)
            data[sym] = (df, tgt)
    finally:
        os.chdir(cwd)

    def one(p0, p1):
        r1 = C9.run_period(data, p0, p1, C9.COST)
        r2 = C9.run_period(data, p0, p1, 2 * C9.COST)
        pf = r1["pf"]
        if pf is None or (isinstance(pf, float) and np.isnan(pf)):
            pf = math.inf if r1["trades"] > 0 else 0.0
        r = dict(start=str(p0.date()), end=str(p1.date()), days=round(r1["yrs"] * 365.25, 1), net=r1["ret"],
                 mdd=r1["mdd"], cagr=r1["cagr"], net2x=r2["ret"], trades=r1["trades"], pf=float(pf),
                 exposure=r1["expo"], b_net=r1["bret"], b_mdd=r1["bmdd"], b_cagr=r1["bcagr"],
                 sol_listed_at_start=bool(p0 >= data["SOLUSDT"][0]["t_open"].iat[0]))
        return finish_row(r)

    last_close = max(d[0]["t_close"].iat[-1] for d in data.values())
    rows, skipped = [], []
    for q in QSTARTS:
        p0 = pd.Timestamp(q, tz="UTC")
        p1 = p0 + pd.Timedelta(days=WIN_DAYS) - pd.Timedelta(milliseconds=1)
        if p1 > last_close + pd.Timedelta(milliseconds=1):
            skipped.append((str(q.date()), "beyond data"))
            continue
        r = one(p0, p1)
        r["q"] = str(q.date())
        rows.append(r)
    ref = one(C9.OOS_START, C9.OOS_END)
    return dict(bench="EW buy&hold BTC/ETH/SOL (1/3 sleeves, SOL in cash until listing 2020-08-11)", rows=rows,
                skipped=skipped, ref_oos=ref)


# ============================================================================ summaries
def summarize(name, block, trade_rule, orig_verdict):
    rows = block["rows"]
    n = len(rows)
    for r in rows:
        r["verdict"], r["verdict_reasons"] = verdict(r, trade_rule)
    ref = block["ref_oos"]
    ref["verdict"], ref["verdict_reasons"] = verdict(ref, trade_rule)
    share = lambda f: round(100.0 * sum(1 for r in rows if f(r)) / n, 1) if n else None
    vc = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("FAIL", "INCONCLUSIVE", "PASS_CANDIDATE")}
    worst = min(rows, key=lambda r: r["net"])
    s = dict(
        n_windows=n, skipped=block["skipped"],
        beats_bh_net_pct=share(lambda r: r["net"] > r["b_net"]),
        beats_bh_maxdd_pct=share(lambda r: r["mdd"] > r["b_mdd"] + TIE_PP),
        ties_maxdd=sum(1 for r in rows if abs(r["mdd"] - r["b_mdd"]) <= TIE_PP),
        beats_bh_ret_over_dd_pct=share(lambda r: r["ratio"] > r["b_ratio"]),
        beats_bh_cagr_over_dd_pct=share(lambda r: r["cagr_dd"] > r["b_cagr_dd"]),
        worst_window_net_pct=round(worst["net"], 2), worst_window_start=worst["q"],
        bh_worst_window_net_pct=round(min(r["b_net"] for r in rows), 2),
        median_net_pct=round(float(np.median([r["net"] for r in rows])), 2),
        bh_median_net_pct=round(float(np.median([r["b_net"] for r in rows])), 2),
        median_maxdd_pct=round(float(np.median([r["mdd"] for r in rows])), 2),
        bh_median_maxdd_pct=round(float(np.median([r["b_mdd"] for r in rows])), 2),
        windows_net_le_0=sum(1 for r in rows if r["net"] <= 0),
        verdict_counts=vc,
        verdict_by_start={r["q"]: r["verdict"] for r in rows},
        ref_oos_verdict_same_rule=ref["verdict"], original_reported_verdict=orig_verdict,
        verdict_flips_with_start=len({r["verdict"] for r in rows}) > 1,
    )
    # sensitivity of the FAIL clause to maxDD ties (identical drawdown while fully invested): windows that would
    # become FAIL if a tie counted as "worse"
    s["extra_fail_if_dd_ties_count_as_worse"] = sum(
        1 for r in rows if r["verdict"] != "FAIL" and r["net"] < r["b_net"] and abs(r["mdd"] - r["b_mdd"]) <= TIE_PP)
    if rows and "cont_net" in rows[0]:
        s["info_continuous_state"] = dict(
            beats_bh_net_pct=share(lambda r: r["cont_net"] > r["b_net"]),
            beats_bh_ret_over_dd_pct=share(lambda r: r["cont_ratio"] > r["b_ratio"]),
            median_net_pct=round(float(np.median([r["cont_net"] for r in rows])), 2),
            worst_net_pct=round(float(min(r["cont_net"] for r in rows)), 2))
    # survivor bar (stated before results were inspected): PASS_CANDIDATE in >50% windows AND zero FAIL windows
    s["survivor"] = bool(n > 0 and vc["PASS_CANDIDATE"] > n / 2 and vc["FAIL"] == 0)
    return s


def jclean(o):
    if isinstance(o, dict):
        return {str(k): jclean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jclean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        o = float(o)
        if o == math.inf:
            return "inf"
        if o == -math.inf:
            return "-inf"
        if o != o:
            return None
        return round(o, 4)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main():
    t0 = time.time()
    repro_ok, repro = reproduce()
    print("REPRO OK:", repro_ok)
    for k, v in repro.items():
        print(" ", k, {x: y for x, y in v.items() if x not in ("missing",)})
    if not repro_ok:
        print("WARNING: reproduction outside tolerance -- see result.json")

    W = load_module("weekly_implA_repro", os.path.join(REPRO, "weekly", "impl", "weekly_implA.py"))
    W.DATA = os.path.join(REPRO, "weekly")
    C2 = load_module("C2_repro", os.path.join(REPRO, "C2", "C2_run.py"))
    C5 = load_module("C5_repro", os.path.join(REPRO, "C5", "C5_run.py"))   # module executes its own run on import
    C9 = load_module("C9_repro", os.path.join(REPRO, "C9", "C9_run.py"))

    blocks = {}
    blocks.update(run_weekly(W))
    blocks["C2_FUNDING_OVERHEAT_FILTER"] = run_c2(C2)
    blocks["C5_FEAR_GREED_CONTRARIAN"] = run_c5(C5)
    blocks["C9_BREAKOUT_TREND_4H"] = run_c9(C9)

    orig = {"S1_DCA_BTC_52W": "n/a (SPEC had no verdict rule)", "S2_TREND_BTC_40W": "n/a (SPEC had no verdict rule)",
            "S6_TREND_50_50_40W": "n/a (SPEC had no verdict rule)",
            "C2_FUNDING_OVERHEAT_FILTER": json.load(open(os.path.join(PRIOR, "C2_result.json")))["verdict"],
            "C5_FEAR_GREED_CONTRARIAN": json.load(open(os.path.join(PRIOR, "C5_result.json")))["verdict"],
            "C9_BREAKOUT_TREND_4H": json.load(open(os.path.join(PRIOR, "C9_result.json")))["verdict"]["verdict"]}
    summaries = {}
    for name, b in blocks.items():
        summaries[name] = summarize(name, b, trade_rule=(name.startswith("C9")), orig_verdict=orig[name])

    survivors = [k for k, v in summaries.items() if v["survivor"]]
    out = dict(
        test="SPEC3 T2 OOS-start sensitivity (rolling 3-year windows)",
        reproduction=dict(all_within_tolerance=repro_ok, tolerance=f"rel {TOL_REL*100}% or abs {TOL_ABS}",
                          detail=repro),
        method=dict(
            starts="first day of each calendar quarter 2018-07-01..2023-07-01 (21 starts)",
            weekly_window="156 weeks from first Monday on/after quarter start (SPEC weekly engine trades only Mondays)",
            daily_4h_window="1095 days from quarter start 00:00 UTC (C2, C5 daily; C9 4h bars fully inside window)",
            capital="$100 cash at window start; indicators from prior data; C2/C9 continuous signal state from full "
                    "history (as in original code); C5 fresh start in USDT (frozen rule 'Start in USDT', original "
                    "primary convention); continuous-state C5 reported as info only",
            costs="original: 20 bps/side; 2x = 40 bps/side",
            bench_conventions="weekly: buy at first Monday open, mark at close, no exit cost (as SPEC engine); "
                              "C2/C5/C9: buy first open, sell at last close with cost (as original SPEC2 code)",
            verdict_rule="SPEC2: FAIL if net<=0 or PF<1 or worse than B&H on BOTH net and maxDD (tie tol 0.01 pp); "
                         "INCONCLUSIVE if <30 trades (C9 only); PASS_CANDIDATE if net>0, PF>=1.2, net/|maxDD| > B&H, "
                         "net>0 at 2x costs; otherwise INCONCLUSIVE. PF for S2/S6 from round trips (open position at "
                         "window end valued at last close net of exit cost); PF not applicable for S1 (never sells); "
                         "PF=inf when no losing trades.",
            survivor_bar="PASS_CANDIDATE in >50% of windows AND no FAIL window",
        ),
        summaries=summaries, survivors=survivors, windows=blocks,
        runtime_s=round(time.time() - t0, 1),
    )
    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(jclean(out), f, indent=1, ensure_ascii=False)

    for name, s in summaries.items():
        print("\n==", name, {k: v for k, v in s.items() if k not in ("verdict_by_start", "skipped")})
        print("   skipped:", s["skipped"])
        for r in blocks[name]["rows"]:
            print(f"  {r['q']} S net {r['net']:8.1f} dd {r['mdd']:6.1f} r {r['ratio']:6.2f} | BH net {r['b_net']:8.1f} "
                  f"dd {r['b_mdd']:6.1f} r {r['b_ratio']:6.2f} | 2x {r['net2x']:8.1f} tr {r['trades']:4d} "
                  f"pf {r['pf'] if r['pf'] is None else round(r['pf'], 2)} -> {r['verdict']} {r['verdict_reasons']}")
        rr = blocks[name]["ref_oos"]
        print(f"  REF OOS {rr['start']}..{rr['end']} net {rr['net']:.1f} dd {rr['mdd']:.1f} BH {rr['b_net']:.1f} "
              f"{rr['b_mdd']:.1f} -> {rr['verdict']} {rr['verdict_reasons']}")
    print("SURVIVORS:", survivors, "runtime", out["runtime_s"])


if __name__ == "__main__":
    main()
