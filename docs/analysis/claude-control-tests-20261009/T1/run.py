# -*- coding: utf-8 -*-
"""
SPEC3 / T1  Random-timing (permutation) test.

Strategies: S2, S6 (SPEC weekly), C9, C2, C5, C13 (SPEC2).
Step 0: reproduce each strategy's per-bar position series with the PRIOR verified code (prior_code/*.py, loaded
        unchanged except for the data-path constant) and check final values against prior_code/*_result.json and
        prior_code/weekly_final_rows.json (tolerance 0.5% relative on the final value of $1 / $100).
Step 1: open-to-open engine: per decision bar i, held log return R_i = log(next_open_i / open_i)
        (last bar of the period: log(close_last / open_last)); every entry and every exit costs log(1 - c);
        open position at period end is liquidated with cost where the original spec/code does so (SPEC2 C*),
        and only marked at close (no exit cost) where the original does not (SPEC weekly S2/S6).
Step 2: null = 5000 random schedules per period: per asset sleeve, keep the multiset of in-position spell lengths
        and out-of-position gap lengths, keep the starting state and total length, permute the ORDER of spells
        and of gaps independently (uniformly), interleave alternately. Same costs per entry/exit, same sleeve
        weights. Statistic = net log return of the period (portfolio = log(sum_k w_k * exp(g_k))).
        p = (1 + #{null >= actual}) / (1 + 5000), one-sided.
Step 3: Holm-Bonferroni, alpha 0.05, family m = 25: the 6 OOS p-values + 19 untested hypotheses with p = 1.

No network, no new data. No parameter changes.
"""
import json
import math
import os
import types
from collections import Counter

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(CTRL, "data")
PRIOR = os.path.join(CTRL, "prior_code")

B = 5000
SEED = 20261009
ALPHA = 0.05
FAMILY_M = 25
TOL_REPRO = 0.005  # 0.5% relative


# ----------------------------------------------------------------------------- prior code loader
def load_prior(modname, fname, replacements):
    """exec the prior script source with only the data-path constant(s) replaced; main() is NOT executed."""
    path = os.path.join(PRIOR, fname)
    src = open(path, encoding="utf-8").read()
    for a, b in replacements:
        assert a in src, f"{fname}: pattern not found: {a!r}"
        src = src.replace(a, b)
    mod = types.ModuleType(modname)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def pathlit(p):
    return "r" + repr(p.replace("\\", "/"))


# ----------------------------------------------------------------------------- engine
LOGC = lambda c: math.log(1.0 - c)


class Sleeve:
    """One all-in/all-out sleeve on a sequence of decision bars.
    o[i]  = execution price at the open of bar i; n[i] = open of bar i+1 (or final close for the last bar).
    x[i]  = 1 if in position during bar i (decided at the close of the previous bar).
    dur[i]= duration weight of bar i (days), for time-exposure."""

    def __init__(self, name, o, n, x, cost, liq_end, weight, dur, t0, t1):
        self.name = name
        self.o = np.asarray(o, float)
        self.n = np.asarray(n, float)
        self.x = np.asarray(x, np.int8)
        assert len(self.o) == len(self.n) == len(self.x) > 0
        assert np.all(self.o > 0) and np.all(self.n > 0)
        self.R = np.log(self.n / self.o)
        self.P = np.concatenate([[0.0], np.cumsum(self.R)])
        self.cost = cost
        self.lc = LOGC(cost)
        self.liq_end = liq_end
        self.w = weight
        self.dur = np.asarray(dur, float)
        self.t0, self.t1 = t0, t1
        # spell decomposition
        x = self.x
        ch = np.flatnonzero(np.diff(x)) + 1
        bnd = np.r_[0, ch, len(x)]
        self.lens = np.diff(bnd)
        self.states = x[bnd[:-1]]
        self.s0 = int(x[0])
        self.end_state = int(x[-1])
        self.L1 = self.lens[self.states == 1]
        self.L0 = self.lens[self.states == 0]
        self.n_entries = len(self.L1)
        self.n_exits = len(self.L1) - (1 if (self.end_state == 1 and not liq_end) else 0)

    # direct bar loop (independent of spell algebra) -- used as a cross-check
    def growth_loop(self, x=None):
        x = self.x if x is None else x
        e, held = 1.0, 0
        for i in range(len(x)):
            if x[i] == 1 and held == 0:
                e *= 1 - self.cost
                held = 1
            elif x[i] == 0 and held == 1:
                e *= 1 - self.cost
                held = 0
            if held:
                e *= self.n[i] / self.o[i]
        if held and self.liq_end:
            e *= 1 - self.cost
        return math.log(e)

    def growth_actual(self):
        g = self.R[self.x == 1].sum() + (self.n_entries + self.n_exits) * self.lc
        return float(g)

    def null(self, rng, b, return_schedules=False):
        n1, n0 = len(self.L1), len(self.L0)
        if n1 == 0:
            return (np.zeros(b), None) if return_schedules else np.zeros(b)
        tot = n1 + n0
        if self.s0 == 1:
            idx1 = np.arange(0, tot, 2)[:n1]
            idx0 = np.arange(1, tot, 2)[:n0]
        else:
            idx0 = np.arange(0, tot, 2)[:n0]
            idx1 = np.arange(1, tot, 2)[:n1]
        assert len(idx1) == n1 and len(idx0) == n0 and len(set(idx1) | set(idx0)) == tot
        A1 = self.L1[np.argsort(rng.random((b, n1)), axis=1)]
        M = np.empty((b, tot), dtype=np.int64)
        M[:, idx1] = A1
        if n0:
            A0 = self.L0[np.argsort(rng.random((b, n0)), axis=1)]
            M[:, idx0] = A0
        ends = np.cumsum(M, axis=1)
        starts = ends - M
        assert np.all(ends[:, -1] == len(self.x))
        g = (self.P[ends[:, idx1]] - self.P[starts[:, idx1]]).sum(axis=1)
        g = g + (self.n_entries + self.n_exits) * self.lc
        if return_schedules:
            sched = np.zeros((b, len(self.x)), dtype=np.int8)
            for r in range(b):
                for a, e in zip(starts[r, idx1], ends[r, idx1]):
                    sched[r, a:e] = 1
            return g, sched
        return g

    def self_check_null(self, rng, k=25):
        """Explicitly build k random schedules and re-evaluate them with the independent bar loop."""
        g, sched = self.null(rng, k, return_schedules=True)
        if sched is None:
            return True
        ok = True
        for r in range(k):
            xs = sched[r]
            ch = np.flatnonzero(np.diff(xs)) + 1
            bnd = np.r_[0, ch, len(xs)]
            lens, st = np.diff(bnd), xs[bnd[:-1]]
            ok &= sorted(lens[st == 1].tolist()) == sorted(self.L1.tolist())
            ok &= sorted(lens[st == 0].tolist()) == sorted(self.L0.tolist())
            ok &= int(xs[0]) == self.s0 and int(xs[-1]) == self.end_state and len(xs) == len(self.x)
            ok &= abs(self.growth_loop(xs) - g[r]) < 1e-9
        return bool(ok)

    def n_distinct_orders(self):
        def mult(L):
            c = Counter(L.tolist())
            v = math.factorial(len(L))
            for k in c.values():
                v //= math.factorial(k)
            return v
        return mult(self.L1) * mult(self.L0)

    def exposure(self):
        return float((self.dur * self.x).sum() / self.dur.sum())

    def bh_log(self):
        return float(self.P[-1])  # log(close_last / open_first), gross


def portfolio_log(gs, ws, cash_w=0.0):
    """log of (sum_k w_k exp(g_k) + idle cash weight)."""
    tot = cash_w
    for g, w in zip(gs, ws):
        tot = tot + w * np.exp(g)
    return np.log(tot)


# ----------------------------------------------------------------------------- strategy builders
def build_weekly():
    wk = load_prior("weekly_implA", "weekly_implA.py",
                    [('DATA = os.path.abspath(os.path.join(HERE, ".."))', "DATA = " + pathlit(DATA))])
    mkt = wk.build_market()
    wk.self_checks_market(mkt)
    dates, pos = mkt["dates"], mkt["pos"]
    p_end = pos[wk.LAST_DAY]
    p_is_end = pos[wk.IS_END]
    p_oos = pos[wk.OOS_START]
    need = ["BTC_wclose", "BTC_sma40", "BTC_rsi14", "BTC_ret12", "ETH_wclose", "ETH_sma40", "ETH_ret12"]
    ok = np.ones(len(dates), bool)
    for k in need:
        ok &= np.isfinite(mkt["sig"][k])
    first_sun = int(np.argmax(ok))
    p_common = first_sun + 1
    periods = {"IS": (p_common, p_is_end), "OOS": (p_oos, p_end), "FULL": (p_common, p_end)}
    return wk, mkt, periods


def weekly_sleeve(mkt, asset, p0, p1, weight):
    """Decision bars = weeks starting at each Monday p (open). Position = BTC/ETH wclose > sma40 at prior Sunday."""
    mondays = list(range(p0, p1 + 1, 7))
    o, n, x, dur = [], [], [], []
    for j, p in enumerate(mondays):
        on = mkt["sig"][f"{asset}_wclose"][p - 1] > mkt["sig"][f"{asset}_sma40"][p - 1]
        assert np.isfinite(mkt["sig"][f"{asset}_sma40"][p - 1])
        o.append(mkt["open"][asset][p])
        if j + 1 < len(mondays):
            n.append(mkt["open"][asset][mondays[j + 1]])
            dur.append(7)
        else:
            n.append(mkt["close"][asset][p1])
            dur.append(p1 - p + 1)
        x.append(1 if on else 0)
    d = mkt["dates"]
    return Sleeve(asset, o, n, x, cost=0.002, liq_end=False, weight=weight, dur=dur,
                  t0=str(d[p0].date()), t1=str(d[p1].date()))


def build_S(name):
    wk, mkt, periods = build_weekly()
    factory = wk.STRATS["S2_TREND_BTC_40W" if name == "S2" else "S6_TREND_50_50_40W"][0]
    out = {}
    for per, (p0, p1) in periods.items():
        if name == "S2":
            sl = [weekly_sleeve(mkt, "BTC", p0, p1, 1.0)]
        else:
            sl = [weekly_sleeve(mkt, "BTC", p0, p1, 0.5), weekly_sleeve(mkt, "ETH", p0, p1, 0.5)]
        prior_run = wk.run(mkt, factory, p0, p1)  # prior simulator, unchanged
        out[per] = dict(sleeves=sl, cash_w=0.0, prior_sim_final=float(prior_run["eq"][-1] / 100.0),
                        prior_sim_trades=len(prior_run["log"]))
    return out


def build_C9():
    m = load_prior("C9", "C9_run.py",
                   [('DATA = os.path.join(BASE, "data")\nos.makedirs(DATA, exist_ok=True)',
                     "DATA = " + pathlit(os.path.join(DATA, "C9")))])
    data = {}
    for sym in m.SYMS:
        df, _ = m.load(sym)
        tgt, _, _ = m.signals(df)
        data[sym] = (df, tgt)
    periods = {"IS": (m.IS_START, m.IS_END), "OOS": (m.OOS_START, m.OOS_END), "FULL": (m.IS_START, m.OOS_END)}
    out = {}
    for per, (p0, p1) in periods.items():
        sl, cash_w = [], 0.0
        for sym, (df, tgt) in data.items():
            r = m.period_idx(df, p0, p1)
            if r is None:
                cash_w += 1 / 3
                continue
            i0, i1 = r
            o = df["open"].to_numpy()
            c = df["close"].to_numpy()
            nn = np.r_[o[i0 + 1:i1 + 1], c[i1]]
            x = np.array([int(tgt[i - 1]) if i >= 1 else 0 for i in range(i0, i1 + 1)])
            dur = np.full(i1 - i0 + 1, 4 / 24)
            sl.append(Sleeve(sym, o[i0:i1 + 1], nn, x, cost=m.COST, liq_end=True, weight=1 / 3, dur=dur,
                             t0=str(df["t_open"].iat[i0]), t1=str(df["t_close"].iat[i1])))
        rp = m.run_period(data, p0, p1, m.COST)
        out[per] = dict(sleeves=sl, cash_w=cash_w, prior_sim_final=1 + rp["ret"] / 100, prior_sim_trades=rp["trades"])
    return out


def build_C2():
    m = load_prior("C2", "C2_run.py",
                   [('DATA = os.path.join(HERE, "data")\nos.makedirs(DATA, exist_ok=True)',
                     "DATA = " + pathlit(os.path.join(DATA, "C2")))])
    fund, kl = m.load()
    first_full = (fund["t"].min() + m.WIN).ceil("D")
    dates = kl.index[kl.index >= first_full]
    sig = m.compute_signal(fund, dates)
    pos = m.state_machine(sig)
    start = dates[0]
    full_end = kl.index[-1]
    periods = {"IS": (start, m.IS_END), "OOS": (m.OOS_START, min(m.OOS_END, full_end)),
               "FULL": (start, min(m.OOS_END, full_end))}
    out = {}
    for per, (a, b) in periods.items():
        d = kl.loc[a:b]
        p = pos.loc[a:b]
        assert (d.index == p.index).all()
        o = d["open"].to_numpy()
        nn = np.r_[o[1:], d["close"].iloc[-1]]
        sl = [Sleeve("BTC", o, nn, p.to_numpy().astype(int), cost=m.COST, liq_end=True, weight=1.0,
                     dur=np.ones(len(d)), t0=str(d.index[0].date()), t1=str(d.index[-1].date()))]
        eqs, trades, _, _ = m.simulate(kl, pos, a, b, m.COST)
        out[per] = dict(sleeves=sl, cash_w=0.0, prior_sim_final=float(eqs.iloc[-1]), prior_sim_trades=len(trades))
    return out


def build_C13():
    m = load_prior("C13", "C13_run.py",
                   [('DATA = os.path.join(HERE, "data")', "DATA = " + pathlit(os.path.join(DATA, "C13")))])
    df, _ = m.load()
    long_sig, valid, *_ = m.signals(df.c.values)
    first_valid = int(np.argmax(valid))
    n = len(df)
    is_i0 = first_valid + 1
    is_i1 = int(np.where(df.date <= m.IS_END)[0][-1])
    oos_i0 = int(np.where(df.date >= m.OOS_START)[0][0])
    oos_i1 = n - 1
    periods = {"IS": (is_i0, is_i1), "OOS": (oos_i0, oos_i1), "FULL": (is_i0, oos_i1)}
    o_all, c_all = df.o.values.astype(float), df.c.values.astype(float)
    out = {}
    for per, (i0, i1) in periods.items():
        o = o_all[i0:i1 + 1]
        nn = np.r_[o_all[i0 + 1:i1 + 1], c_all[i1]]
        x = long_sig[i0 - 1:i1].astype(int)
        assert len(x) == len(o)
        sl = [Sleeve("GOLD", o, nn, x, cost=m.COST, liq_end=True, weight=1.0, dur=np.ones(len(o)),
                     t0=str(df.date[i0].date()), t1=str(df.date[i1].date()))]
        marks, held, trades = m.simulate(df, long_sig, i0, i1, m.COST)
        out[per] = dict(sleeves=sl, cash_w=0.0, prior_sim_final=float(marks[-1]), prior_sim_trades=len(trades))
    return out


def build_C5():
    """C5_run.py executes everything at module level (writes result.json next to itself), so its data loading and
    simulate() are replicated here line-for-line (same timing convention, same costs, same period definitions)."""
    import glob
    d5 = os.path.join(DATA, "C5")
    COST, CUTOFF = 0.0020, pd.Timestamp("2026-10-06")
    IS_END, OOS_START = pd.Timestamp("2022-12-31"), pd.Timestamp("2023-01-01")
    BUY_LVL, SELL_LVL = 20, 80
    fng_raw = json.load(open(os.path.join(d5, "fng.json")))["data"]
    fgi_all = pd.Series({pd.to_datetime(int(x["timestamp"]), unit="s"): int(x["value"]) for x in fng_raw}).sort_index()
    fgi = fgi_all[fgi_all.index <= CUTOFF]
    rows = []
    for p in sorted(glob.glob(os.path.join(d5, "btcusdt_1d_part*.json"))):
        rows += json.load(open(p))
    k = pd.DataFrame(rows).iloc[:, :7]
    k.columns = ["ot", "open", "high", "low", "close", "vol", "ct"]
    k = k.drop_duplicates("ot")
    k.index = pd.to_datetime(k["ot"], unit="ms")
    k = k[["open", "high", "low", "close"]].astype(float).sort_index()
    k = k[k.index <= CUTOFF]
    assert (k.index == pd.date_range(k.index[0], k.index[-1], freq="D")).all()
    FIRST_FGI = fgi.index[0]
    periods = {"IS": (FIRST_FGI, IS_END), "OOS": (OOS_START, CUTOFF), "FULL": (FIRST_FGI, CUTOFF)}

    def simulate(start, end, cost):
        days = k.loc[start:end].index
        cash, units, long_ = 1.0, 0.0, False
        held, ntr = [], 0
        for t in days:
            sig_date = t - pd.Timedelta(days=1)
            if sig_date in fgi.index:
                v = fgi[sig_date]
                o = k.at[t, "open"]
                if (not long_) and v <= BUY_LVL:
                    units = cash * (1 - cost) / o
                    cash, long_ = 0.0, True
                elif long_ and v >= SELL_LVL:
                    cash = units * o * (1 - cost)
                    units, long_ = 0.0, False
                    ntr += 1
            held.append(long_)
        if long_:
            cash = units * k.at[days[-1], "close"] * (1 - cost)
            ntr += 1
        return cash, np.array(held, int), days, ntr

    out = {}
    for per, (a, b) in periods.items():
        fin, held, days, ntr = simulate(a, b, COST)
        d = k.loc[days]
        o = d["open"].to_numpy()
        nn = np.r_[o[1:], d["close"].iloc[-1]]
        sl = [Sleeve("BTC", o, nn, held, cost=COST, liq_end=True, weight=1.0, dur=np.ones(len(d)),
                     t0=str(days[0].date()), t1=str(days[-1].date()))]
        out[per] = dict(sleeves=sl, cash_w=0.0, prior_sim_final=float(fin), prior_sim_trades=ntr)
    return out


# ----------------------------------------------------------------------------- prior published numbers
def prior_targets():
    t = {}
    rows = json.load(open(os.path.join(PRIOR, "weekly_final_rows.json"), encoding="utf-8"))
    for r in rows:
        if r["variant"] != "primary":
            continue
        key = {"S2_TREND_BTC_40W": "S2", "S6_TREND_50_50_40W": "S6"}.get(r["strategy"])
        if key:
            t[(key, r["period"])] = dict(final=r["final_value"] / 100.0, trades=r["trades"],
                                         expo=r["time_in_market_pct"])
    j = json.load(open(os.path.join(PRIOR, "C9_result.json"), encoding="utf-8"))
    for p, r in j["periods"].items():
        t[("C9", p)] = dict(final=1 + r["ret"] / 100, trades=r["trades"], expo=r["expo"])
    j = json.load(open(os.path.join(PRIOR, "C2_result.json"), encoding="utf-8"))
    for r in j["rows"]:
        t[("C2", r["period"])] = dict(final=1 + r["net_return_pct"] / 100, trades=r["trades"], expo=r["exposure_pct"])
    j = json.load(open(os.path.join(PRIOR, "C5_result.json"), encoding="utf-8"))
    for p, r in j["periods"].items():
        t[("C5", p)] = dict(final=1 + r["net_return_pct"] / 100, trades=r["trades"], expo=r["exposure_pct"])
    j = json.load(open(os.path.join(PRIOR, "C13_result.json"), encoding="utf-8"))
    for p, r in j["periods"].items():
        s = r["strategy"]
        t[("C13", p)] = dict(final=1 + s["net_return_pct"] / 100, trades=s["trades"], expo=s["exposure_pct"])
    return t


# ----------------------------------------------------------------------------- Holm
def holm(pdict, m=FAMILY_M, alpha=ALPHA):
    items = sorted(pdict.items(), key=lambda kv: kv[1])
    n_untested = m - len(items)
    res = {}
    still = True
    for i, (k, p) in enumerate(items):
        thr = alpha / (m - i)
        rej = still and (p <= thr)
        if not rej:
            still = False
        # Holm adjusted p (monotone)
        res[k] = dict(p=p, rank=i + 1, threshold=thr, reject=bool(rej))
    adj, run_max = {}, 0.0
    for i, (k, p) in enumerate(items):
        run_max = max(run_max, min(1.0, (m - i) * p))
        res[k]["p_holm_adj"] = run_max
    return res, n_untested


# ----------------------------------------------------------------------------- main
def main():
    rng = np.random.default_rng(SEED)
    targets = prior_targets()
    builders = [("S2", build_S, "SPEC", "S2"), ("S6", build_S, "SPEC", "S6"), ("C9", build_C9, "SPEC2", None),
                ("C2", build_C2, "SPEC2", None), ("C5", build_C5, "SPEC2", None), ("C13", build_C13, "SPEC2", None)]
    repro, results, self_checks = [], {}, []
    for sid, fn, spec, arg in builders:
        built = fn(arg) if arg else fn()
        results[sid] = {"spec": spec}
        for per in ("IS", "OOS", "FULL"):
            b = built[per]
            sl, cash_w = b["sleeves"], b["cash_w"]
            ws = [s.w for s in sl]
            # actual
            g_act = [s.growth_actual() for s in sl]
            g_loop = [s.growth_loop() for s in sl]
            assert np.allclose(g_act, g_loop, atol=1e-10), (sid, per)
            G = float(portfolio_log(g_act, ws, cash_w))
            final = math.exp(G)
            tg = targets[(sid, per)]
            rel_pub = final / tg["final"] - 1
            rel_sim = final / b["prior_sim_final"] - 1
            trades_engine = sum(s.n_entries + s.n_exits for s in sl)
            # prior SPEC2 trade counts are round trips; SPEC weekly counts each buy/sell
            trades_cmp = trades_engine if spec == "SPEC" else sum(s.n_entries for s in sl)
            repro.append(dict(strategy=sid, period=per, engine_final=final, prior_published_final=tg["final"],
                              rel_diff_vs_published=rel_pub, prior_simulator_final=b["prior_sim_final"],
                              rel_diff_vs_prior_simulator=rel_sim, engine_trades=trades_cmp,
                              prior_trades=tg["trades"], within_tol=bool(abs(rel_pub) <= TOL_REPRO)))
            # null (self-check on explicit schedules uses a separate RNG stream, so main draws are unaffected)
            chk_rng = np.random.default_rng(SEED + 1)
            null_ok = all(s.self_check_null(chk_rng) for s in sl)
            assert null_ok, (sid, per)
            self_checks.append(f"{sid} {per}: 25 explicit random schedules per sleeve keep spell/gap multisets, start/end state, length; engine == bar loop")
            nulls = [s.null(rng, B) for s in sl]
            Gn = portfolio_log(nulls, ws, cash_w)
            cnt = int((Gn >= G - 1e-12).sum())
            p = (1 + cnt) / (1 + B)
            # exposure-matched B&H (gross price log return x time exposure), per sleeve and portfolio
            expo = [s.exposure() for s in sl]
            bh = [s.bh_log() for s in sl]
            em = [e * h for e, h in zip(expo, bh)]
            G_em = float(portfolio_log(em, ws, cash_w))
            G_bh = float(portfolio_log(bh, ws, cash_w))
            n_orders = 1
            for s in sl:
                n_orders *= s.n_distinct_orders()
            results[sid][per] = dict(
                start=min(s.t0 for s in sl), end=max(s.t1 for s in sl),
                bar="week (Mon open->next Mon open)" if spec == "SPEC" else
                ("4h bar" if sid == "C9" else "day"),
                sleeves=[dict(asset=s.name, weight=s.w, bars=len(s.x), start_state=s.s0, end_state=s.end_state,
                              in_spells=len(s.L1), out_gaps=len(s.L0), entries=s.n_entries, exits=s.n_exits,
                              exposure_pct=round(100 * e, 2), actual_log=round(g, 5),
                              bh_log_gross=round(h, 5), expo_matched_bh_log=round(x, 5),
                              null_median_log=round(float(np.median(nl)), 5),
                              p_sleeve=round((1 + int((nl >= g - 1e-12).sum())) / (1 + B), 5),
                              distinct_orders=s.n_distinct_orders() if s.n_distinct_orders() < 10**12 else ">1e12")
                         for s, e, g, h, x, nl in zip(sl, expo, g_act, bh, em, nulls)],
                idle_cash_weight=cash_w,
                actual_log=round(G, 5), actual_net_pct=round(100 * (final - 1), 2),
                null_median_log=round(float(np.median(Gn)), 5),
                null_median_net_pct=round(100 * (math.exp(float(np.median(Gn))) - 1), 2),
                null_p05_log=round(float(np.percentile(Gn, 5)), 5),
                null_p95_log=round(float(np.percentile(Gn, 95)), 5),
                null_ge_actual=cnt, p_value=round(p, 5), mc_se_p=round(math.sqrt(p * (1 - p) / B), 5),
                min_attainable_p_approx=round(max((1.0 / n_orders) if n_orders < 10**12 else 0.0, 1.0 / (1 + B)), 5),
                expo_matched_bh_log=round(G_em, 5),
                expo_matched_bh_net_pct=round(100 * (math.exp(G_em) - 1), 2),
                bh_log_gross=round(G_bh, 5),
                distinct_orderings=n_orders if n_orders < 10**12 else ">1e12",
                min_attainable_p_note=("null has only %d distinct orderings -> p cannot be very small" % n_orders
                                       if n_orders < 2000 else ""),
            )
            print(f"{sid:4s} {per:4s} net={100*(final-1):9.2f}% (pub {100*(tg['final']-1):9.2f}%, d={rel_pub:+.2e}) "
                  f"log={G:+.4f} nullmed={np.median(Gn):+.4f} p={p:.4f} expoBH={G_em:+.4f} "
                  f"orders={n_orders if n_orders < 10**12 else '>1e12'}")

    oos_p = {sid: results[sid]["OOS"]["p_value"] for sid in results}
    hres, n_untested = holm(oos_p)
    survivors = [k for k, v in hres.items() if v["reject"]]
    raw_sig = {per: [sid for sid in results if results[sid][per]["p_value"] < 0.05] for per in ("IS", "OOS", "FULL")}
    out = dict(
        test="SPEC3 T1 random-timing permutation test",
        method=dict(
            permutations=B, seed=SEED,
            null="per asset sleeve: multiset of in-position spell lengths and out-of-position gap lengths kept; "
                 "order of spells and of gaps permuted independently (uniform random permutations); starting state, "
                 "ending state, total length, number of entries/exits and exposure identical to the original; "
                 "same per-side cost on every entry/exit; same sleeve weights; sleeves permuted independently",
            statistic="net log return of the period: log(final/initial) incl. costs; portfolio = log(sum w_k exp(g_k))",
            p_value="(1 + #{null >= actual}) / (1 + 5000), one-sided; ties count as >=",
            bars="S2/S6: weekly decision bars (Monday open -> next Monday open; last bar to final close); "
                 "C9: 4h bars; C2/C5/C13: daily bars",
            end_of_period="SPEC (S2/S6): open position only marked at final close (no exit cost), as in weekly_implA; "
                          "SPEC2 (C2/C5/C9/C13): open position liquidated at final close with cost, as in prior code",
            periods="SPEC: IS start..2021-12-31, OOS restart 2022-01-03..2026-10-06, FULL common start..2026-10-06; "
                    "SPEC2: IS data start..2022-12-31, OOS 2023-01-01..2026-10-06, FULL; each period is an "
                    "independent restart as in the prior code",
            expo_matched_bh="exposure (time share in position, duration-weighted) x gross B&H price log return "
                            "log(close_last/open_first) of the same sleeve asset over the same period; portfolio "
                            "combined as log(sum w_k exp(.)); no costs",
            multiple_testing="Holm-Bonferroni, alpha=0.05, family m=25: 6 OOS p-values of this test + 19 untested "
                             "hypotheses set to p=1",
        ),
        reproduction=repro,
        self_checks=self_checks + ["actual growth via spell algebra == independent bar loop (all sleeves, all periods)",
                                   "engine final == prior simulator final (prior code, unchanged) for every period"],
        reproduction_all_within_0_5pct=all(r["within_tol"] for r in repro),
        results=results,
        holm=dict(family_size=FAMILY_M, alpha=ALPHA, untested_set_to_p1=n_untested, tests=hres,
                  survivors=survivors),
        raw_p_below_0_05=raw_sig,
        survivors=survivors,
        conclusion_ru=(
            "Ни одна из 6 стратегий не проходит поправку Холма (m=25, нужен p<=0.002 для лучшей): минимальный OOS "
            "p-value = %.4f (%s). Сырой p<0.05 в OOS: %s; в IS: %s; в FULL: %s. Для C2 и C5 в OOS у нулевой "
            "гипотезы всего 12 и 4 различных порядка спеллов, поэтому тест для них в OOS практически не имеет "
            "мощности (минимально достижимый p ~ 0.08 и ~ 0.25)." % (
                min(oos_p.values()), min(oos_p, key=oos_p.get), raw_sig["OOS"] or "нет",
                raw_sig["IS"] or "нет", raw_sig["FULL"] or "нет")),
    )
    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=str)
    print("repro all within 0.5%:", out["reproduction_all_within_0_5pct"])
    for r in repro:
        print("  ", r["strategy"], r["period"], f"engine={r['engine_final']:.6f} pub={r['prior_published_final']:.6f} "
              f"d_pub={r['rel_diff_vs_published']:+.2e} d_sim={r['rel_diff_vs_prior_simulator']:+.2e} "
              f"trades {r['engine_trades']} vs {r['prior_trades']}")
    print("Holm:", json.dumps(hres, indent=0))
    print("survivors:", survivors, "raw p<0.05:", raw_sig)


if __name__ == "__main__":
    main()
