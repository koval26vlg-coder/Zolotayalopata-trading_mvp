"""
Implementation A of the frozen backtest spec v1 (../SPEC.md), primary variant only.

Primary variant: costs 20 bps per side (0.10% fee + 0.10% slippage) on traded notional,
cash yield 0%, Binance daily data, weekly signals on Sunday close executed at Monday open.

No network access. No parameter tuning. No sensitivity variants here (done elsewhere).

Run:  python backtest.py      -> writes results.json next to this file.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, ".."))

COST_RATE = 0.002            # 0.10% fee + 0.10% slippage, per side, on traded notional
START_CASH = 100.0
CUTOFF = pd.Timestamp("2026-10-07")      # drop rows with open_time >= this (incomplete candle)
LAST_DAY = pd.Timestamp("2026-10-06")
IS_END = pd.Timestamp("2021-12-31")
OOS_START = pd.Timestamp("2022-01-03")   # Monday
SMA_N, RSI_N, MOM_N, DCA_WEEKS = 40, 14, 12, 52
CHECK_MIN, TRADE_MIN = 10.0, 5.0
HORIZONS = (52, 104, 156)
EPS = 1e-9

SELF_CHECKS = []


def check(cond, msg):
    if not cond:
        raise AssertionError("SELF-CHECK FAILED: " + msg)
    SELF_CHECKS.append(msg)


# ----------------------------------------------------------------------------- data
def load_daily(sym, cutoff=CUTOFF):
    df = pd.read_csv(os.path.join(DATA, f"{sym}USDT_1d.csv"))
    df["date"] = pd.to_datetime(df["open_time_utc_ms"], unit="ms")  # UTC, naive
    df = df[df["date"] < cutoff].copy()
    df = df.set_index("date")[["open", "close"]].astype(float)
    return df


def weekly_closes(daily):
    """Complete Monday..Sunday weeks only; weekly close = Sunday daily close; indexed by Sunday date."""
    if len(daily) == 0:
        return pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    wk = daily.index - pd.to_timedelta(daily.index.weekday, unit="D")
    g = daily.groupby(wk)
    n = g.size()
    last_day = g.apply(lambda x: x.index.max())
    complete = (n == 7) & (last_day.dt.weekday == 6)
    wc = g["close"].last()[complete]
    wc.index = wc.index + pd.Timedelta(days=6)  # label by Sunday
    return wc


def sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def rsi_wilder(s, n=RSI_N):
    c = s.values.astype(float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return pd.Series(out, index=s.index)
    d = np.diff(c)
    gains = np.clip(d, 0, None)
    losses = np.clip(-d, 0, None)
    ag, al = gains[:n].mean(), losses[:n].mean()

    def val(ag, al):
        return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

    out[n] = val(ag, al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = val(ag, al)
    return pd.Series(out, index=s.index)


def build_market(cutoff=CUTOFF):
    raw = {a: load_daily(a, cutoff) for a in ("BTC", "ETH", "SOL")}
    cal = raw["BTC"].index
    check(raw["ETH"].index.equals(cal), "ETH daily calendar identical to BTC calendar")
    m = {"dates": cal, "open": {}, "close": {}, "sig": {}}
    for a, df in raw.items():
        r = df.reindex(cal)
        m["open"][a] = r["open"].values
        m["close"][a] = r["close"].values
    m["first_valid"] = {a: int(np.argmax(~np.isnan(m["close"][a]))) for a in raw}
    sig = {}
    wkly = {}
    for a in ("BTC", "ETH", "SOL"):
        wc = weekly_closes(raw[a])
        wkly[a] = wc
        ind = {
            "wclose": wc,
            "sma40": sma(wc, SMA_N),
            "rsi14": rsi_wilder(wc, RSI_N),
            "ret12": wc / wc.shift(MOM_N) - 1.0,
        }
        for k, s in ind.items():
            arr = np.full(len(cal), np.nan)
            pos = cal.get_indexer(s.index)
            check((pos >= 0).all(), f"{a} weekly labels map onto daily calendar")
            arr[pos] = s.values
            sig[f"{a}_{k}"] = arr
    m["sig"] = sig
    m["weekly"] = wkly
    m["pos"] = {d: i for i, d in enumerate(cal)}
    return m


# ----------------------------------------------------------------------------- engine
class Book:
    """One cash+holdings book. Trades only at a Monday open, priced with that open."""

    def __init__(self, cash, mkt, log, tag=""):
        self.cash = cash
        self.units = {}
        self.mkt = mkt
        self.log = log
        self.tag = tag

    def buy(self, asset, amount, p):
        amount = min(amount, self.cash)
        if amount <= EPS:
            return
        px = self.mkt["open"][asset][p]
        assert np.isfinite(px) and px > 0
        cost = amount * COST_RATE
        q = (amount - cost) / px
        self.cash -= amount
        if self.cash < 0 and self.cash > -1e-9:
            self.cash = 0.0
        self.units[asset] = self.units.get(asset, 0.0) + q
        self.log.append(dict(p=p, sig_p=p - 1, asset=asset, side="BUY", px=px,
                             notional=amount, cost=cost, qty=q, book=self.tag))

    def sell_all(self, asset, p):
        q = self.units.get(asset, 0.0)
        if q <= 0:
            return
        px = self.mkt["open"][asset][p]
        assert np.isfinite(px) and px > 0
        notional = q * px
        cost = notional * COST_RATE
        self.cash += notional - cost
        self.units[asset] = 0.0
        self.log.append(dict(p=p, sig_p=p - 1, asset=asset, side="SELL", px=px,
                             notional=notional, cost=cost, qty=q, book=self.tag))

    def holding(self):
        return [a for a, q in self.units.items() if q > 0]

    def value_vec(self, sl):
        v = np.full(sl.stop - sl.start, self.cash)
        for a, q in self.units.items():
            if q > 0:
                v = v + q * self.mkt["close"][a][sl]
        return v

    def invested_vec(self, sl):
        v = np.zeros(sl.stop - sl.start)
        for a, q in self.units.items():
            if q > 0:
                v = v + q * self.mkt["close"][a][sl]
        return v


class SignalView:
    """Gives a strategy access ONLY to indicator values at the prior Sunday close (p-1)."""

    def __init__(self, mkt):
        self.mkt = mkt
        self.p = None

    def __call__(self, name):
        sp = self.p - 1
        v = self.mkt["sig"][name][sp]
        if not np.isfinite(v):
            raise ValueError(f"indicator {name} undefined at {self.mkt['dates'][sp].date()}")
        return v


# --- strategies: each defines books(), on_monday(k, p, view), active(k) for time burden
class BH:
    def __init__(self, weights):
        self.weights = weights  # {asset: fraction}

    def setup(self, mkt, log):
        self.b = Book(START_CASH, mkt, log)
        return [self.b]

    def on_monday(self, k, p, sv):
        if k == 0:
            for a, w in self.weights.items():
                self.b.buy(a, START_CASH * w, p)
        return False  # no weekly check needed


class DCA:
    def setup(self, mkt, log):
        self.b = Book(START_CASH, mkt, log)
        return [self.b]

    def on_monday(self, k, p, sv):
        if k < DCA_WEEKS:
            amt = self.b.cash if k == DCA_WEEKS - 1 else START_CASH / DCA_WEEKS
            self.b.buy("BTC", amt, p)
            return True
        return False


class Trend:
    def __init__(self, asset="BTC", n_label="sma40"):
        self.asset = asset
        self.n_label = n_label

    def setup(self, mkt, log, cash=START_CASH, tag=""):
        self.b = Book(cash, mkt, log, tag)
        return [self.b]

    def on_monday(self, k, p, sv):
        a = self.asset
        on = sv(f"{a}_wclose") > sv(f"{a}_{self.n_label}")
        held = self.b.units.get(a, 0.0) > 0
        if on and not held:
            self.b.buy(a, self.b.cash, p)
        elif not on and held:
            self.b.sell_all(a, p)
        return True


class DualMom:
    def setup(self, mkt, log):
        self.b = Book(START_CASH, mkt, log)
        return [self.b]

    def on_monday(self, k, p, sv):
        rb, re = sv("BTC_ret12"), sv("ETH_ret12")
        best, r = ("BTC", rb) if rb >= re else ("ETH", re)
        target = best if r > 0 else None
        held = self.b.holding()
        cur = held[0] if held else None
        assert len(held) <= 1
        if cur != target:
            if cur is not None:
                self.b.sell_all(cur, p)
            if target is not None:
                self.b.buy(target, self.b.cash, p)
        return True


class RSIGatedDCA:
    def setup(self, mkt, log):
        self.b = Book(START_CASH, mkt, log)
        return [self.b]

    def on_monday(self, k, p, sv):
        active = k < DCA_WEEKS or self.b.cash > EPS
        if not active:
            return False
        released_weeks = min(k + 1, DCA_WEEKS)
        unreleased = START_CASH - released_weeks * START_CASH / DCA_WEEKS
        if released_weeks == DCA_WEEKS:
            unreleased = 0.0
        if sv("BTC_rsi14") < 50:
            amt = self.b.cash - unreleased
            if amt > EPS:
                self.b.buy("BTC", amt, p)
        return True


class TrendPullback:
    def setup(self, mkt, log):
        self.b = Book(START_CASH, mkt, log)
        return [self.b]

    def on_monday(self, k, p, sv):
        c, s, r = sv("BTC_wclose"), sv("BTC_sma40"), sv("BTC_rsi14")
        held = self.b.units.get("BTC", 0.0) > 0
        if not held and c > s and r < 50:
            self.b.buy("BTC", self.b.cash, p)
        elif held and c < s:
            self.b.sell_all("BTC", p)
        return True


class Trend5050:
    def setup(self, mkt, log):
        self.sb = Trend("BTC")
        self.se = Trend("ETH")
        return self.sb.setup(mkt, log, START_CASH / 2, "BTC") + self.se.setup(mkt, log, START_CASH / 2, "ETH")

    def on_monday(self, k, p, sv):
        a = self.sb.on_monday(k, p, sv)
        b = self.se.on_monday(k, p, sv)
        return a or b  # one combined weekly check


STRATS = {
    "S0_BH_BTC": (lambda: BH({"BTC": 1.0}), "BTC"),
    "S0b_BH_ETH": (lambda: BH({"ETH": 1.0}), "BTC"),
    "S0c_BH_SOL": (lambda: BH({"SOL": 1.0}), "SOL"),
    "S0d_BH_50_50": (lambda: BH({"BTC": 0.5, "ETH": 0.5}), "BTC"),
    "S1_DCA_BTC_52W": (lambda: DCA(), "BTC"),
    "S2_TREND_BTC_40W": (lambda: Trend("BTC"), "BTC"),
    "S3_DUAL_MOM_12W": (lambda: DualMom(), "BTC"),
    "S4_RSI_GATED_DCA_BTC": (lambda: RSIGatedDCA(), "BTC"),
    "S5_TREND_PULLBACK_BTC": (lambda: TrendPullback(), "BTC"),
    "S6_TREND_50_50_40W": (lambda: Trend5050(), "BTC"),
}


def run(mkt, factory, p0, p1):
    """Simulate from Monday position p0 (open) through day position p1 (close, inclusive)."""
    dates = mkt["dates"]
    assert dates[p0].weekday() == 0, "start must be a Monday"
    log = []
    strat = factory()
    books = strat.setup(mkt, log)
    sv = SignalView(mkt)
    n = p1 - p0 + 1
    eq = np.empty(n)
    inv = np.empty(n)
    checks = 0
    k = 0
    p = p0
    while p <= p1:
        sv.p = p
        if strat.on_monday(k, p, sv):
            checks += 1
        stop = min(p + 7, p1 + 1)
        sl = slice(p, stop)
        eq[p - p0: stop - p0] = sum(b.value_vec(sl) for b in books)
        inv[p - p0: stop - p0] = sum(b.invested_vec(sl) for b in books)
        for b in books:
            assert b.cash >= -1e-9, "negative cash"
            assert all(q >= 0 for q in b.units.values()), "negative units (short)"
        p += 7
        k += 1
    return dict(eq=eq, inv=inv, log=log, checks=checks, p0=p0, p1=p1, weeks_k=k)


# ----------------------------------------------------------------------------- metrics
def metrics(mkt, res):
    dates = mkt["dates"][res["p0"]: res["p1"] + 1]
    eq, inv = res["eq"], res["inv"]
    n_days = len(eq)
    final = eq[-1]
    years = n_days / 365.25
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0
    path = np.concatenate([[START_CASH], eq])  # include the $100 before the first open
    peak = np.maximum.accumulate(path)
    mdd = (path / peak - 1.0).min()
    s = pd.Series(eq, index=dates)
    ye = s.groupby(s.index.year).last()
    prev = pd.Series([START_CASH] + list(ye.values[:-1]), index=ye.index)
    yr = ye / prev - 1.0
    full_years = [y for y in ye.index
                  if dates[0] <= pd.Timestamp(f"{y}-01-01") and pd.Timestamp(f"{y}-12-31") <= dates[-1]]
    trades = len(res["log"])
    costs = sum(t["cost"] for t in res["log"])
    weeks = n_days / 7.0
    minutes = (CHECK_MIN * res["checks"] + TRADE_MIN * trades) / weeks
    return dict(
        start=str(dates[0].date()), end=str(dates[-1].date()), days=n_days,
        final_value=final, cagr_pct=cagr * 100, max_dd_pct=mdd * 100,
        worst_year_pct=yr.min() * 100, worst_year=int(yr.idxmin()),
        worst_full_year_pct=(yr[full_years].min() * 100) if full_years else None,
        yearly_pct={int(y): round(v * 100, 2) for y, v in yr.items()},
        time_in_market_pct=(inv > 1e-12).mean() * 100,
        avg_exposure_pct=(inv / eq).mean() * 100,
        trades=trades, costs_usd=costs, weekly_checks=res["checks"],
        minutes_per_week=minutes,
    )


def rolling(mkt, factory, first_p, last_p):
    out = {h: [] for h in HORIZONS}
    starts = 0
    p = first_p
    while p + 7 * HORIZONS[0] - 1 <= last_p:
        hmax = max(h for h in HORIZONS if p + 7 * h - 1 <= last_p)
        res = run(mkt, factory, p, p + 7 * hmax - 1)
        for h in HORIZONS:
            if h <= hmax:
                out[h].append(res["eq"][7 * h - 1])
        starts += 1
        p += 7
    stats = {}
    for h, v in out.items():
        v = np.array(v)
        stats[h] = dict(n=len(v), median=float(np.median(v)), p10=float(np.percentile(v, 10)),
                        worst=float(v.min()), pct_loss=float((v < START_CASH).mean() * 100))
    return stats


# ----------------------------------------------------------------------------- self checks
def self_checks_market(mkt):
    d = mkt["dates"]
    check(d.max() == LAST_DAY, "last usable daily row is 2026-10-06; 2026-10-07 candle dropped")
    check((d < CUTOFF).all(), "no daily row with open_time >= 2026-10-07")
    check((pd.Series(d).diff().dropna() == pd.Timedelta(days=1)).all(), "BTC/ETH daily calendar has no gaps")
    for a in ("BTC", "ETH", "SOL"):
        wc = mkt["weekly"][a]
        check((wc.index.weekday == 6).all(), f"{a}: all weekly bars labelled on Sunday")
        pos = d.get_indexer(wc.index)
        check(np.allclose(wc.values, mkt["close"][a][pos]), f"{a}: weekly close == Sunday daily close")
        for sp in pos:
            assert np.isfinite(mkt["close"][a][sp - 6: sp + 1]).all() and d[sp - 6].weekday() == 0
        check(True, f"{a}: every weekly bar has 7 daily rows Mon..Sun (complete weeks only)")
        # independent indicator re-computation
        sm = mkt["sig"][f"{a}_sma40"][pos]
        manual = np.array([wc.values[i - SMA_N + 1: i + 1].mean() if i >= SMA_N - 1 else np.nan
                           for i in range(len(wc))])
        check(np.allclose(sm, manual, equal_nan=True), f"{a}: SMA40 equals mean of last 40 weekly closes incl. signal week")
        dd = wc.diff()
        g, l = dd.clip(lower=0).values[1:], (-dd).clip(lower=0).values[1:]
        sg = pd.Series(np.concatenate([[g[:RSI_N].mean()], g[RSI_N:]])).ewm(alpha=1 / RSI_N, adjust=False).mean().values
        sl = pd.Series(np.concatenate([[l[:RSI_N].mean()], l[RSI_N:]])).ewm(alpha=1 / RSI_N, adjust=False).mean().values
        rsi_alt = 100 - 100 / (1 + sg / sl)
        rs = mkt["sig"][f"{a}_rsi14"][pos][RSI_N:]
        check(np.allclose(rs, rsi_alt), f"{a}: Wilder RSI14 matches independent ewm(alpha=1/14) recomputation")
        check(np.isnan(mkt["sig"][f"{a}_rsi14"][pos][:RSI_N]).all(), f"{a}: RSI undefined for first 14 weeks (no back-fill)")


def self_checks_run(mkt, name, res):
    d = mkt["dates"]
    for t in res["log"]:
        assert t["sig_p"] < t["p"] and d[t["sig_p"]] < d[t["p"]]
        assert d[t["p"]].weekday() == 0 and d[t["sig_p"]].weekday() == 6
        assert d[t["p"]] - d[t["sig_p"]] == pd.Timedelta(days=1)
        assert abs(t["cost"] - COST_RATE * t["notional"]) < 1e-12
        assert t["px"] == mkt["open"][t["asset"]][t["p"]]
        assert res["p0"] <= t["p"] <= res["p1"]
    # rebuild equity from the trade log independently (holdings carried forward, marked at close)
    n = res["p1"] - res["p0"] + 1
    cash = np.full(n, 0.0)
    eq = np.zeros(n)
    books = {}
    for t in res["log"]:
        books.setdefault(t["book"], None)
    cash_delta = np.zeros(n)
    units = {}
    for t in res["log"]:
        i = t["p"] - res["p0"]
        if t["side"] == "BUY":
            cash_delta[i] -= t["notional"]
            units.setdefault(t["asset"], np.zeros(n))[i] += t["qty"]
        else:
            cash_delta[i] += t["notional"] - t["cost"]
            units.setdefault(t["asset"], np.zeros(n))[i] -= t["qty"]
    cash = START_CASH + np.cumsum(cash_delta)
    eq = cash.copy()
    for a, du in units.items():
        eq += np.cumsum(du) * mkt["close"][a][res["p0"]: res["p1"] + 1]
    assert np.allclose(eq, res["eq"], rtol=1e-10, atol=1e-8), name


def truncation_test(name, factory, p0_date, full_mkt, full_res, cut_dates):
    """Equity up to date T must be identical when data after T is physically removed."""
    for T in cut_dates:
        m = build_market(cutoff=T + pd.Timedelta(days=1))
        p0 = m["pos"][p0_date]
        p1 = len(m["dates"]) - 1
        r = run(m, factory, p0, p1)
        a = full_res["eq"][: len(r["eq"])]
        assert len(r["eq"]) == p1 - p0 + 1
        assert np.allclose(a, r["eq"], rtol=1e-12, atol=1e-10), f"{name}: look-ahead detected at cut {T.date()}"


# ----------------------------------------------------------------------------- main
def main():
    mkt = build_market()
    self_checks_market(mkt)
    dates, pos = mkt["dates"], mkt["pos"]
    p_end = pos[LAST_DAY]
    p_is_end = pos[IS_END]
    p_oos = pos[OOS_START]

    # common start: first Monday whose prior Sunday has every BTC/ETH indicator defined
    need = ["BTC_wclose", "BTC_sma40", "BTC_rsi14", "BTC_ret12", "ETH_wclose", "ETH_sma40", "ETH_ret12"]
    ok = np.ones(len(dates), bool)
    for k in need:
        ok &= np.isfinite(mkt["sig"][k])
    first_sun = int(np.argmax(ok))
    p_common = first_sun + 1
    check(dates[first_sun].weekday() == 6 and dates[p_common].weekday() == 0,
          f"common start Monday {dates[p_common].date()} follows first fully-defined signal Sunday {dates[first_sun].date()}")
    check(not ok[:first_sun].any(), "no earlier Sunday has all indicators defined")
    # SOL own window: first Monday of first complete SOL week
    sol_first_sun = int(np.argmax(np.isfinite(mkt["sig"]["SOL_wclose"])))
    p_sol = sol_first_sun - 6
    check(dates[p_sol].weekday() == 0, f"SOL own start Monday {dates[p_sol].date()}")
    check(dates[p_oos].weekday() == 0, "OOS restart 2022-01-03 is a Monday")

    rows = []
    detail = {}
    for name, (factory, cal) in STRATS.items():
        p_start = p_sol if cal == "SOL" else p_common
        full = run(mkt, factory, p_start, p_end)
        is_ = run(mkt, factory, p_start, p_is_end)
        oos = run(mkt, factory, p_oos, p_end)
        for r in (full, is_, oos):
            self_checks_run(mkt, name, r)
        # IS run must equal the FULL run's first part (equity never depends on later data)
        assert np.allclose(full["eq"][: len(is_["eq"])], is_["eq"], rtol=1e-12)
        roll = rolling(mkt, factory, p_start, p_end)
        detail[name] = {}
        for per, r in (("FULL", full), ("IS", is_), ("OOS", oos)):
            mt = metrics(mkt, r)
            row = dict(strategy=name, period=per, variant="primary",
                       final_value=mt["final_value"], cagr_pct=mt["cagr_pct"], max_dd_pct=mt["max_dd_pct"],
                       worst_year_pct=mt["worst_year_pct"], time_in_market_pct=mt["time_in_market_pct"],
                       trades=mt["trades"], costs_usd=mt["costs_usd"], minutes_per_week=mt["minutes_per_week"])
            for h in HORIZONS:
                for f in ("median", "p10", "worst", "pct_loss"):
                    row[f"roll{h}_{f}"] = roll[h][f] if per == "FULL" else None
            row = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()}
            rows.append(row)
            detail[name][per] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in mt.items()}
        detail[name]["rolling_n_starts"] = {h: roll[h]["n"] for h in HORIZONS}
        print(f"{name:24s} FULL {rows[-3]['final_value']:>9.2f}  IS {rows[-2]['final_value']:>9.2f}  OOS {rows[-1]['final_value']:>9.2f}")

    check(True, "every trade: signal date (Sunday) < execution date (next Monday open), exec = signal + 1 day")
    check(True, "every trade: cost == 0.20% of traded notional (buy: cash committed; sell: gross proceeds)")
    check(True, "every trade priced at the Monday daily open; all trades inside their period window")
    check(True, "equity independently rebuilt from trade log (units x daily close + cash) matches simulator")
    check(True, "no negative cash, no negative units (spot only, no leverage/shorting)")
    check(True, "IS run equals the first part of FULL run exactly")

    # look-ahead truncation test: physically remove all data after T, re-derive indicators, re-run
    cuts = [pd.Timestamp(x) for x in ("2019-03-17", "2020-03-15", "2021-11-10", "2022-06-19", "2024-03-13")]
    for name, (factory, cal) in STRATS.items():
        p_start = p_sol if cal == "SOL" else p_common
        full = run(mkt, factory, p_start, p_end)
        truncation_test(name, factory, dates[p_start], mkt, full, [c for c in cuts if c > dates[p_start] + pd.Timedelta(days=7)])
    check(True, "truncation test: equity up to T identical when all data after T is deleted (5 cut dates, all strategies)")

    # strategy-specific sanity
    d1 = run(mkt, STRATS["S1_DCA_BTC_52W"][0], p_common, p_end)
    check(len(d1["log"]) == 52 and abs(sum(t["notional"] for t in d1["log"]) - 100) < 1e-9,
          "S1: exactly 52 weekly buys totalling $100")
    d4 = run(mkt, STRATS["S4_RSI_GATED_DCA_BTC"][0], p_common, p_end)
    for t in d4["log"]:
        assert mkt["sig"]["BTC_rsi14"][t["sig_p"]] < 50 and t["side"] == "BUY"
    check(True, "S4: every buy has prior-Sunday RSI14 < 50; never sells")

    out = dict(
        spec="SPEC.md frozen v1", implementation="implA (pandas/numpy)", variant="primary",
        common_start=str(dates[p_common].date()), common_start_first_signal_sunday=str(dates[first_sun].date()),
        sol_start=str(dates[p_sol].date()), end=str(LAST_DAY.date()), is_end=str(IS_END.date()),
        oos_start=str(OOS_START.date()), rows=rows, detail=detail, self_checks=list(dict.fromkeys(SELF_CHECKS)),
    )
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("common start", out["common_start"], "SOL start", out["sol_start"])
    print(len(set(SELF_CHECKS)), "distinct self-checks passed")


if __name__ == "__main__":
    main()
