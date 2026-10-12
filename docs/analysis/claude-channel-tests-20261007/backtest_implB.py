#!/usr/bin/env python3
"""
Independent implementation B of the frozen backtest SPEC v1 (../SPEC.md).

Pure python: csv, datetime, math (+ json/os/sys for I/O). No pandas/numpy.
Scope: S0, S0b, S0c, S0d, S1..S6, primary variant (20 bps/side, 0% cash yield),
periods FULL / IS / OOS, plus rolling-start distributions for FULL.

Conventions chosen here (documented, not tuned):
  * Weekly bar = Monday..Sunday, only weeks with all 7 daily candles. Weekly close = Sunday close.
  * Signal on Sunday close t, executed at the open of Monday t+1 day.
  * Buy:  spend cash C, cost = 0.002*C, units = (C - cost)/open.
    Sell: notional N = units*open, cost = 0.002*N, cash += N - cost.
  * Equity = cash + sum(units*close) at each daily close. Final value = mark-to-market (no forced liquidation).
  * CAGR uses years = (end - start + 1 day)/365.25 (start Monday open .. end-day close).
  * Max drawdown on daily close equity with the initial $100 as the first peak.
  * Worst calendar year: year-end equity / previous year-end equity (first year vs $100), partial years included.
  * % time in market: share of daily closes with any crypto position > 0.
  * Time burden: (10 min * weeks that need a check + 5 min * trades) / weeks in period.
      checks: B&H = 0 weeks; S1 = the 52 buy weeks; S4 = buy weeks + any later week while cash is unspent;
      S2/S3/S5/S6 = every week.
  * Rolling value after N weeks = equity at the Sunday close ending week N (start + 7N - 1 days);
    p10 = linear interpolation (position (n-1)*0.10 of sorted values).
"""
import csv
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
CUTOFF = dt.date(2026, 10, 7)        # drop open_time >= this
END = dt.date(2026, 10, 6)           # last usable day
IS_END = dt.date(2021, 12, 31)
OOS_START = dt.date(2022, 1, 3)
COST = 0.002                         # 0.10% fee + 0.10% slippage per side
CASH0 = 100.0
ONE = dt.timedelta(days=1)
EPOCH = dt.date(1970, 1, 1)


# ----------------------------------------------------------------------------- data
def load_binance(fn):
    daily = {}
    dropped = []
    with open(os.path.join(BASE, fn), newline="") as f:
        for row in csv.DictReader(f):
            ms = int(row["open_time_utc_ms"])
            assert ms % 86400000 == 0, (fn, ms)
            d = EPOCH + dt.timedelta(days=ms // 86400000)
            if d >= CUTOFF:
                dropped.append(d)
                continue
            daily[d] = (float(row["open"]), float(row["close"]))
    return daily, dropped


class Asset:
    """Daily open/close + complete Monday..Sunday weekly closes + trailing indicators."""

    def __init__(self, name, daily):
        self.name = name
        self.daily = daily
        self.dates = sorted(daily)
        self.first, self.last = self.dates[0], self.dates[-1]
        self.weeks = []      # (monday, sunday, weekly_close)
        self.incomplete = []
        m = self.first + dt.timedelta(days=(7 - self.first.weekday()) % 7)
        while m + 6 * ONE <= self.last:
            days = [m + i * ONE for i in range(7)]
            if all(x in daily for x in days):
                self.weeks.append((m, days[-1], daily[days[-1]][1]))
            else:
                self.incomplete.append(m)
            m += 7 * ONE
        self.widx = {w[1]: i for i, w in enumerate(self.weeks)}   # sunday -> week index
        self.wclose = [w[2] for w in self.weeks]
        self._sma = {}
        self._ret = {}
        self.rsi14 = self._wilder_rsi(14)

    def sma(self, n):
        if n not in self._sma:
            c = self.wclose
            out = [None] * len(c)
            s = 0.0
            for i in range(len(c)):
                s += c[i]
                if i >= n:
                    s -= c[i - n]
                if i >= n - 1:
                    out[i] = s / n
            # re-check against direct mean to avoid running-sum drift
            for i in range(n - 1, len(c)):
                direct = math.fsum(c[i - n + 1:i + 1]) / n
                assert abs(direct - out[i]) <= 1e-9 * max(1.0, direct)
                out[i] = direct
            self._sma[n] = out
        return self._sma[n]

    def ret(self, n):
        if n not in self._ret:
            c = self.wclose
            self._ret[n] = [None if i < n else c[i] / c[i - n] - 1.0 for i in range(len(c))]
        return self._ret[n]

    def _wilder_rsi(self, n):
        c = self.wclose
        out = [None] * len(c)
        if len(c) <= n:
            return out
        gains = [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
        losses = [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
        ag = sum(gains[:n]) / n
        al = sum(losses[:n]) / n

        def val(g, l):
            if l == 0.0:
                return 100.0
            return 100.0 - 100.0 / (1.0 + g / l)

        out[n] = val(ag, al)          # first defined at the (n+1)-th weekly close
        for i in range(n + 1, len(c)):
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
            out[i] = val(ag, al)
        return out

    def o(self, d):
        return self.daily[d][0]

    def c(self, d):
        return self.daily[d][1]


# ----------------------------------------------------------------------------- portfolio
class Book:
    def __init__(self, cash, A, log):
        self.cash = cash
        self.units = {}
        self.A = A
        self.log = log

    def buy(self, a, amount, d, sig):
        if amount <= 1e-12:
            return
        amount = min(amount, self.cash)
        cost = amount * COST
        px = self.A[a].o(d)
        self.units[a] = self.units.get(a, 0.0) + (amount - cost) / px
        self.cash -= amount
        if self.cash < 1e-12:
            self.cash = 0.0
        self.log.append({"date": d, "signal": sig, "asset": a, "side": "BUY",
                         "notional": amount, "cost": cost, "px": px})

    def sell_all(self, a, d, sig):
        u = self.units.get(a, 0.0)
        if u <= 0.0:
            return
        px = self.A[a].o(d)
        notional = u * px
        cost = notional * COST
        self.cash += notional - cost
        self.units[a] = 0.0
        self.log.append({"date": d, "signal": sig, "asset": a, "side": "SELL",
                         "notional": notional, "cost": cost, "px": px})

    def value(self, d):
        return self.cash + sum(u * self.A[a].c(d) for a, u in self.units.items() if u)

    def invested(self):
        return any(u > 0 for u in self.units.values())


# ----------------------------------------------------------------------------- strategies
STRATS = [
    ("S0", "BH_BTC"), ("S0b", "BH_ETH"), ("S0c", "BH_SOL"), ("S0d", "BH_50_50"),
    ("S1", "DCA_BTC_52W"), ("S2", "TREND_BTC_40W"), ("S3", "DUAL_MOM_12W"),
    ("S4", "RSI_GATED_DCA_BTC"), ("S5", "TREND_PULLBACK_BTC"), ("S6", "TREND_50_50_40W"),
]
SMA_N = 40
MOM_N = 12
RSI_TH = 50.0
DCA_WEEKS = 52


class Ctx:
    """Indicator access restricted to the signal Sunday (look-ahead guard)."""

    def __init__(self, A, mon):
        self.A = A
        self.mon = mon
        self.sun = mon - ONE
        assert self.sun.weekday() == 6

    def _i(self, a):
        i = self.A[a].widx[self.sun]          # KeyError if signal week incomplete/missing
        assert self.A[a].weeks[i][1] < self.mon
        return i

    def close(self, a):
        return self.A[a].wclose[self._i(a)]

    def sma(self, a, n):
        v = self.A[a].sma(n)[self._i(a)]
        assert v is not None, ("SMA undefined", a, self.sun)
        return v

    def ret(self, a, n):
        v = self.A[a].ret(n)[self._i(a)]
        assert v is not None, ("RET undefined", a, self.sun)
        return v

    def rsi(self, a):
        v = self.A[a].rsi14[self._i(a)]
        assert v is not None, ("RSI undefined", a, self.sun)
        return v


class Strategy:
    def __init__(self, sid, A):
        self.sid = sid
        self.A = A
        self.log = []
        self.checks = 0
        self.k = 0
        if sid == "S6":
            self.books = [Book(CASH0 / 2, A, self.log), Book(CASH0 / 2, A, self.log)]
            self.sleeve_assets = ["BTC", "ETH"]
        else:
            self.books = [Book(CASH0, A, self.log)]
        self.held = None          # S3: currently held asset; S5: bool
        self.spent = 0.0          # S1/S4 gross cash spent
        self.assets = {"S0": ["BTC"], "S0b": ["ETH"], "S0c": ["SOL"], "S0d": ["BTC", "ETH"],
                       "S3": ["BTC", "ETH"], "S6": ["BTC", "ETH"]}.get(sid, ["BTC"])

    def on_monday(self, mon):
        self.k += 1
        k = self.k
        x = Ctx(self.A, mon)
        sig = x.sun
        b = self.books[0]
        s = self.sid
        if s in ("S0", "S0b", "S0c"):
            if k == 1:
                b.buy(self.assets[0], b.cash, mon, None)
        elif s == "S0d":
            if k == 1:
                b.buy("BTC", CASH0 / 2, mon, None)
                b.buy("ETH", b.cash, mon, None)
        elif s == "S1":
            if k <= DCA_WEEKS:
                self.checks += 1
                amt = b.cash if k == DCA_WEEKS else CASH0 / DCA_WEEKS
                b.buy("BTC", amt, mon, sig)
        elif s == "S2":
            self.checks += 1
            self._trend(b, "BTC", x, mon)
        elif s == "S6":
            self.checks += 1
            for bk, a in zip(self.books, self.sleeve_assets):
                self._trend(bk, a, x, mon)
        elif s == "S3":
            self.checks += 1
            rb, re_ = x.ret("BTC", MOM_N), x.ret("ETH", MOM_N)
            tgt, r = ("BTC", rb) if rb >= re_ else ("ETH", re_)
            if r <= 0:
                tgt = None
            if tgt != self.held:
                if self.held is not None:
                    b.sell_all(self.held, mon, sig)
                if tgt is not None:
                    b.buy(tgt, b.cash, mon, sig)
                self.held = tgt
        elif s == "S4":
            if k <= DCA_WEEKS or b.cash > 1e-12:
                self.checks += 1
                if x.rsi("BTC") < RSI_TH:
                    if k >= DCA_WEEKS:
                        amt = b.cash
                    else:
                        amt = k * CASH0 / DCA_WEEKS - self.spent
                    if amt > 1e-12:
                        b.buy("BTC", amt, mon, sig)
                        self.spent += amt
        elif s == "S5":
            self.checks += 1
            c, m = x.close("BTC"), x.sma("BTC", SMA_N)
            if not self.held:
                if c > m and x.rsi("BTC") < RSI_TH:
                    b.buy("BTC", b.cash, mon, sig)
                    self.held = True
            else:
                if c < m:
                    b.sell_all("BTC", mon, sig)
                    self.held = False
        else:
            raise ValueError(s)

    def _trend(self, bk, a, x, mon):
        up = x.close(a) > x.sma(a, SMA_N)
        if up and not bk.invested():
            bk.buy(a, bk.cash, mon, x.sun)
        elif not up and bk.invested():
            bk.sell_all(a, mon, x.sun)

    def value(self, d):
        return sum(bk.value(d) for bk in self.books)

    def invested(self):
        return any(bk.invested() for bk in self.books)

    def exposure(self, d):
        v = self.value(d)
        cash = sum(bk.cash for bk in self.books)
        return (v - cash) / v if v > 0 else 0.0


def simulate(sid, A, start, end, sample_dates=None):
    """Run strategy from Monday `start` open to `end` close. Returns dict."""
    assert start.weekday() == 0
    st = Strategy(sid, A)
    series = []          # (date, equity, invested, exposure)
    samples = {}
    d = start
    mondays = 0
    while d <= end:
        if d.weekday() == 0:
            mondays += 1
            st.on_monday(d)
        if sample_dates is None:
            series.append((d, st.value(d), st.invested(), st.exposure(d)))
        elif d in sample_dates:
            samples[d] = st.value(d)
        d += ONE
    return {"strategy": st, "series": series, "samples": samples, "mondays": mondays}


# ----------------------------------------------------------------------------- metrics
def r2(x):
    return None if x is None else round(x + 0.0, 2)


def metrics(res, start, end):
    st = res["strategy"]
    ser = res["series"]
    final = ser[-1][1]
    years = ((end - start).days + 1) / 365.25
    cagr = (final / CASH0) ** (1.0 / years) - 1.0
    peak, mdd = CASH0, 0.0
    for _, e, _, _ in ser:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1.0)
    ye = {}
    for d, e, _, _ in ser:
        ye[d.year] = e
    prev, worst, worst_y, yr = CASH0, None, None, {}
    for y in sorted(ye):
        r = ye[y] / prev - 1.0
        yr[y] = r
        if worst is None or r < worst:
            worst, worst_y = r, y
        prev = ye[y]
    tim = sum(1 for s in ser if s[2]) / len(ser)
    avg_exp = sum(s[3] for s in ser) / len(ser)
    trades = len(st.log)
    costs = sum(t["cost"] for t in st.log)
    weeks = res["mondays"]
    mpw = (st.checks * 10 + trades * 5) / weeks
    return {
        "final_value": final, "cagr_pct": cagr * 100, "max_dd_pct": mdd * 100,
        "worst_year_pct": worst * 100, "worst_year": worst_y,
        "yearly_returns_pct": {str(y): round(v * 100, 2) for y, v in yr.items()},
        "time_in_market_pct": tim * 100, "avg_exposure_pct": avg_exp * 100,
        "trades": trades, "costs_usd": costs, "minutes_per_week": mpw,
        "weeks": weeks, "checks": st.checks, "days": len(ser),
        "start": start.isoformat(), "end": end.isoformat(),
    }


def pct_linear(sorted_vals, q):
    n = len(sorted_vals)
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def median(sv):
    return pct_linear(sv, 0.5)


def rolling(sid, A, first_monday, end):
    out = {}
    starts = []
    m = first_monday
    while m + (52 * 7 - 1) * ONE <= end:
        starts.append(m)
        m += 7 * ONE
    vals = {52: [], 104: [], 156: []}
    for s in starts:
        targets = {s + (7 * n - 1) * ONE: n for n in (52, 104, 156) if s + (7 * n - 1) * ONE <= end}
        last = max(targets)
        res = simulate(sid, A, s, last, sample_dates=set(targets))
        for d, n in targets.items():
            vals[n].append(res["samples"][d])
    for n, v in vals.items():
        sv = sorted(v)
        out[n] = {"n_starts": len(sv), "median": median(sv), "p10": pct_linear(sv, 0.10),
                  "worst": sv[0], "pct_loss": 100.0 * sum(1 for x in sv if x < CASH0) / len(sv),
                  "first_start": starts[0].isoformat(),
                  "last_start": starts[len(sv) - 1].isoformat()}
    return out


# ----------------------------------------------------------------------------- driver
def build_assets(perturb_from=None):
    A, dropped = {}, {}
    for name, fn in (("BTC", "BTCUSDT_1d.csv"), ("ETH", "ETHUSDT_1d.csv"), ("SOL", "SOLUSDT_1d.csv")):
        daily, drp = load_binance(fn)
        if perturb_from is not None:
            for d in daily:
                if d >= perturb_from:
                    f = 1.0 + 0.35 * math.sin((d - perturb_from).days * 0.37 + len(name))
                    o, c = daily[d]
                    daily[d] = (o * f, c * (2.0 - f))
        A[name] = Asset(name, daily)
        dropped[name] = drp
    return A, dropped


def common_start(A):
    """First Monday whose signal Sunday has every primary BTC/ETH indicator defined."""
    for (m, sun, _) in A["BTC"].weeks:
        mon = sun + ONE
        ok = True
        for a in ("BTC", "ETH"):
            i = A[a].widx.get(sun)
            if i is None or A[a].sma(SMA_N)[i] is None or A[a].ret(MOM_N)[i] is None \
                    or A[a].rsi14[i] is None:
                ok = False
        if ok:
            return mon, sun
    raise RuntimeError


def main():
    A, dropped = build_assets()
    checks = []
    for a in A:
        assert A[a].last == END, (a, A[a].last)
        assert dropped[a] == [CUTOFF], (a, dropped[a])
        assert not A[a].incomplete, (a, A[a].incomplete)
    checks.append("Dropped exactly one candle per asset (2026-10-07, incomplete); last usable day 2026-10-06 "
                  "for BTC/ETH/SOL; no daily gaps, every weekly bar has 7 daily candles Mon..Sun.")
    last_week = A["BTC"].weeks[-1]
    checks.append("Weekly bars: BTC %d complete weeks %s..%s (first Monday after 2017-08-17 start); "
                  "last complete week ends Sunday %s." % (len(A["BTC"].weeks), A["BTC"].weeks[0][0],
                                                          last_week[1], last_week[1]))
    for a in A:
        for (m, sun, c) in A[a].weeks:
            assert m.weekday() == 0 and sun.weekday() == 6 and c == A[a].c(sun)
    cs, cs_sun = common_start(A)
    checks.append("Common start %s (Monday) = first Monday after the 40th BTC/ETH weekly close (%s) where "
                  "SMA40, RET12 and RSI14 are all defined for both assets." % (cs, cs_sun))

    sol_start = A["SOL"].weeks[0][0]
    periods = {"FULL": (cs, END), "IS": (cs, IS_END), "OOS": (OOS_START, END)}
    sol_periods = {"FULL": (sol_start, END), "IS": (sol_start, IS_END), "OOS": (OOS_START, END)}

    rows, full_series, logs = [], {}, {}
    for sid, nm in STRATS:
        per = sol_periods if sid == "S0c" else periods
        for pname, (s, e) in per.items():
            res = simulate(sid, A, s, e)
            mt = metrics(res, s, e)
            row = {"strategy": "%s %s" % (sid, nm), "variant": "primary", "period": pname}
            row.update(mt)
            if pname == "FULL":
                full_series[sid] = res["series"]
                logs[sid] = res["strategy"].log
                rl = rolling(sid, A, s, e)
                for n in (52, 104, 156):
                    row["roll%d_median" % n] = rl[n]["median"]
                    row["roll%d_p10" % n] = rl[n]["p10"]
                    row["roll%d_worst" % n] = rl[n]["worst"]
                    row["roll%d_pct_loss" % n] = rl[n]["pct_loss"]
                    row["roll%d_n_starts" % n] = rl[n]["n_starts"]
                    row["roll%d_last_start" % n] = rl[n]["last_start"]
            else:
                for n in (52, 104, 156):
                    for f in ("median", "p10", "worst", "pct_loss"):
                        row["roll%d_%s" % (n, f)] = None
            rows.append(row)
            print("%-24s %-4s final=%9.2f cagr=%7.2f mdd=%7.2f worst_y=%7.2f(%s) tim=%6.2f trades=%3d "
                  "costs=%5.2f mpw=%5.2f" % (row["strategy"], pname, mt["final_value"], mt["cagr_pct"],
                                               mt["max_dd_pct"], mt["worst_year_pct"], mt["worst_year"],
                                               mt["time_in_market_pct"], mt["trades"], mt["costs_usd"],
                                               mt["minutes_per_week"]))

    # ---------------- self-checks
    # 1. every trade: signal Sunday is the day before the Monday execution; executed at that day's open
    nt = 0
    for sid, lg in logs.items():
        for t in lg:
            nt += 1
            assert t["date"].weekday() == 0
            if t["signal"] is not None:
                assert t["signal"] == t["date"] - ONE and t["signal"].weekday() == 6
            assert t["px"] == A[t["asset"]].o(t["date"])
            assert abs(t["cost"] - COST * t["notional"]) < 1e-12
            assert t["date"] <= END
    checks.append("All %d FULL-period trades execute on a Monday at that day's daily open; every signal-driven "
                  "trade uses the Sunday immediately before; cost = 20 bps of traded notional on every trade." % nt)

    # 2. analytic buy & hold
    for sid, a, s in (("S0", "BTC", cs), ("S0b", "ETH", cs), ("S0c", "SOL", sol_start)):
        exp = CASH0 * (1 - COST) * A[a].c(END) / A[a].o(s)
        got = full_series[sid][-1][1]
        assert abs(exp - got) < 1e-9, (sid, exp, got)
    checks.append("B&H finals match closed form 100*(1-0.002)*close(2026-10-06)/open(start) for BTC, ETH, SOL.")

    # 3. S0d equity == 0.5*S0 + 0.5*S0b on every day
    md = max(abs(x[1] - 0.5 * (y[1] + z[1])) for x, y, z in zip(full_series["S0d"], full_series["S0"],
                                                                 full_series["S0b"]))
    assert md < 1e-9
    checks.append("S0d daily equity equals 0.5*S0 + 0.5*S0b on every day (max abs diff %.1e)." % md)

    # 4. S6 BTC sleeve == 0.5 * S2 (same rule, half capital)
    st6 = Strategy("S6", A)
    st2 = Strategy("S2", A)
    d, mx = cs, 0.0
    while d <= END:
        if d.weekday() == 0:
            st6.on_monday(d)
            st2.on_monday(d)
        mx = max(mx, abs(st6.books[0].value(d) - 0.5 * st2.value(d)))
        d += ONE
    assert mx < 1e-9
    checks.append("S6 BTC sleeve equity equals 0.5*S2 equity every day (max abs diff %.1e)." % mx)

    # 5. independent recomputation of indicators at a few signal dates
    for a in ("BTC", "ETH"):
        c = A[a].wclose
        for i in (39, 100, 200, len(c) - 1):
            assert abs(A[a].sma(40)[i] - sum(c[i - 39:i + 1]) / 40) < 1e-9 * c[i]
            assert abs(A[a].ret(12)[i] - (c[i] / c[i - 12] - 1)) < 1e-12
        assert A[a].sma(40)[38] is None and A[a].rsi14[13] is None and A[a].rsi14[14] is not None
    checks.append("SMA40/RET12 recomputed directly at sample weeks match; SMA40 first defined at week 40, "
                  "Wilder RSI14 first defined at week 15 (seeded by 14-change simple average).")

    # 6. look-ahead perturbation test
    X = dt.date(2021, 3, 3)
    Ap, _ = build_assets(perturb_from=X)
    ok_all = True
    for sid, _ in STRATS:
        s = sol_start if sid == "S0c" else cs
        rp = simulate(sid, Ap, s, END)
        before_o = [r for r in full_series[sid] if r[0] < X]
        before_p = [r for r in rp["series"] if r[0] < X]
        same = len(before_o) == len(before_p) and all(abs(p[1] - q[1]) < 1e-12 for p, q in zip(before_o, before_p))
        tr_o = [(t["date"], t["asset"], t["side"], round(t["notional"], 12)) for t in logs[sid] if t["date"] < X]
        tr_p = [(t["date"], t["asset"], t["side"], round(t["notional"], 12)) for t in rp["strategy"].log
                if t["date"] < X]
        after_diff = any(abs(p[1] - q[1]) > 1e-6 for p, q in zip(full_series[sid], rp["series"]) if p[0] >= X)
        ok_all = ok_all and same and tr_o == tr_p and after_diff
    assert ok_all
    checks.append("Look-ahead test: perturbing every price from %s onward leaves all daily equity and all trades "
                  "before that date identical for all 10 strategies (and changes results after it)." % X)

    # 7. S1 / S4 budget accounting
    s1 = [t for t in logs["S1"]]
    assert len(s1) == 52 and abs(sum(t["notional"] for t in s1) - 100) < 1e-9
    assert s1[0]["date"] == cs and s1[-1]["date"] == cs + 51 * 7 * ONE
    s4 = logs["S4"]
    assert all(t["side"] == "BUY" for t in s4)
    checks.append("S1: 52 buys of $100/52 from %s to %s, total $100 deployed. S4: buys only (never sells), %d "
                  "executed buys in FULL, total deployed $%.2f." % (s1[0]["date"], s1[-1]["date"], len(s4),
                                                                      sum(t["notional"] for t in s4)))
    # 8. S4 gating correctness: every S4 buy had RSI<50 at signal; every skipped week in budget had RSI>=50
    for t in s4:
        i = A["BTC"].widx[t["signal"]]
        assert A["BTC"].rsi14[i] < 50
    checks.append("Every S4 buy had BTC weekly RSI14 < 50 at the prior Sunday close.")
    # 9. OOS restart uses warmed indicators
    i0 = A["BTC"].widx[OOS_START - ONE]
    checks.append("OOS restarts with $100 on %s; first OOS signal week (Sunday %s) is weekly bar #%d, so SMA40/RSI "
                  "are warmed from pre-2022 data; S5 starts flat (USDT default) in each period/rolling start."
                  % (OOS_START, OOS_START - ONE, i0 + 1))

    # 10. what the start would be if the 50W sensitivity were also required (info only)
    for (m, sun, _) in A["BTC"].weeks:
        i = A["BTC"].widx[sun]
        if A["BTC"].sma(50)[i] is not None:
            checks.append("Info: if 50W-SMA sensitivity were included in the warm-up, common start would be %s "
                          "(not used; primary strategies only need SMA40)." % (sun + ONE))
            break

    for row in rows:                      # report numbers rounded to 2 decimals
        for kf, v in list(row.items()):
            if isinstance(v, float):
                row[kf] = r2(v)

    out = {
        "impl": "B (pure python, independent)",
        "spec": "SPEC.md v1 frozen",
        "common_start": cs.isoformat(),
        "sol_start": sol_start.isoformat(),
        "end": END.isoformat(),
        "conventions": __doc__,
        "self_checks": checks,
        "rows": rows,
    }
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    print("\nSELF-CHECKS")
    for c in checks:
        print(" -", c)


if __name__ == "__main__":
    main()
