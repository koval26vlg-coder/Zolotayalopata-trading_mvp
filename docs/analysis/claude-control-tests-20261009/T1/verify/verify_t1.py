# Independent verifier for SPEC3 T1 (random-timing permutation test).
# Written from scratch (positions re-derived from the frozen rules in data/SPEC.md and data/SPEC2.md,
# conventions cross-checked against prior_code/*.py). Does NOT import or read ctrl/T1/run.py.
import json, glob, os, sys, math
from decimal import Decimal
import numpy as np
import pandas as pd

CTRL = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DATA = os.path.join(CTRL, "data")
PRIOR = os.path.join(CTRL, "prior_code")
OUT = os.path.dirname(os.path.abspath(__file__))
N_PERM = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
TOL = 1e-9


# ============================================================ engine
class Sleeve:
    """One asset sleeve within one period. r[i]: gross log return of holding bar i
    (open_i -> open_{i+1}; last bar open -> close). h[i]: 1 if held during bar i.
    end_cost: True if an open position at the period end is liquidated WITH cost."""

    def __init__(self, name, r, h, dur, cost, end_cost, w, bh_log, label=""):
        self.name, self.r, self.h = name, np.asarray(r, float), np.asarray(h, np.int8)
        self.dur, self.cost, self.end_cost, self.w, self.bh_log = np.asarray(dur, float), cost, end_cost, w, bh_log
        self.label = label
        assert len(self.r) == len(self.h) == len(self.dur) and np.isfinite(self.r).all()

    def n_entries_exits(self, h=None):
        h = self.h if h is None else h
        prev = np.r_[0, h[:-1]]
        ent = int(((h == 1) & (prev == 0)).sum())
        ex = int(((h == 0) & (prev == 1)).sum())
        if h[-1] == 1 and self.end_cost:
            ex += 1
        return ent, ex

    def cost_log(self, h=None):
        e, x = self.n_entries_exits(h)
        return (e + x) * math.log(1 - self.cost)

    def gross(self, h=None):
        h = self.h if h is None else h
        return float((h * self.r).sum())

    def net(self, h=None):
        return self.gross(h) + self.cost_log(h)

    def runs(self):
        h = self.h
        ch = np.flatnonzero(np.diff(h)) + 1
        b = np.r_[0, ch, len(h)]
        lens = np.diff(b)
        st = h[b[:-1]]
        return lens, st

    def exposure(self):
        return float((self.h * self.dur).sum() / self.dur.sum())

    def null(self, N, rng):
        """Permute ORDER of in-spells and out-gaps independently; keep start state and total length."""
        lens, st = self.runs()
        sp, gp = lens[st == 1], lens[st == 0]
        s0 = int(st[0])
        K, G = len(sp), len(gp)
        tot = K + G
        R = np.r_[0.0, np.cumsum(self.r)]
        L = np.empty((N, tot), dtype=np.int64)
        P_sp = sp[np.argsort(rng.random((N, K)), axis=1)] if K else np.empty((N, 0), np.int64)
        P_gp = gp[np.argsort(rng.random((N, G)), axis=1)] if G else np.empty((N, 0), np.int64)
        if s0 == 1:
            L[:, 0::2], L[:, 1::2] = P_sp, P_gp
            in_pos = np.arange(0, tot, 2)
        else:
            L[:, 0::2], L[:, 1::2] = P_gp, P_sp
            in_pos = np.arange(1, tot, 2)
        B = np.concatenate([np.zeros((N, 1), np.int64), np.cumsum(L, axis=1)], axis=1)
        assert (B[:, -1] == len(self.r)).all()
        g = (R[B[:, in_pos + 1]] - R[B[:, in_pos]]).sum(axis=1)
        # cost is invariant: #entries = K, exit count identical because start/end state identical
        return g + self.cost_log(), L, s0

    def schedule_from_L(self, Lrow, s0):
        h = np.empty(len(self.r), np.int8)
        st, p = s0, 0
        for l in Lrow:
            h[p:p + l] = st
            p += l
            st = 1 - st
        return h


def port_log(sleeves, gs):
    return np.log(sum(s.w * np.exp(g) for s, g in zip(sleeves, gs)) + (1 - sum(s.w for s in sleeves)))


# ============================================================ S2 / S6 (weekly, SPEC.md)
def load_daily(sym):
    df = pd.read_csv(os.path.join(DATA, f"{sym}USDT_1d.csv"))
    df["date"] = pd.to_datetime(df["open_time_utc_ms"], unit="ms")
    df = df[df["date"] < pd.Timestamp("2026-10-07")].set_index("date")[["open", "close"]].astype(float)
    assert (df.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()
    return df


def weekly_signal(d):
    """Return Series indexed by Sunday: 1 if weekly close > SMA40 of weekly closes (complete Mon..Sun weeks)."""
    wk = d.index - pd.to_timedelta(d.index.weekday, unit="D")
    g = d["close"].groupby(wk)
    n = g.size()
    lastday = pd.Series(d.index, index=d.index).groupby(wk).max()
    comp = (n == 7) & (lastday.dt.weekday == 6)
    wc = g.last()[comp]
    wc.index = wc.index + pd.Timedelta(days=6)
    sma = wc.rolling(40, min_periods=40).mean()
    return wc, sma


def weekly_sleeve(d, wc, sma, p0, p1, w, name, label):
    """Bars = weekly decision bars Monday open -> next Monday open; last (partial) bar Monday open -> close p1."""
    mondays = pd.date_range(p0, p1, freq="7D")
    assert all(m.weekday() == 0 for m in mondays)
    r, h, dur = [], [], []
    for k, m in enumerate(mondays):
        sun = m - pd.Timedelta(days=1)
        assert np.isfinite(sma.loc[sun])
        h.append(1 if wc.loc[sun] > sma.loc[sun] else 0)
        nxt = m + pd.Timedelta(days=7)
        if nxt <= p1:
            r.append(math.log(d.at[nxt, "open"] / d.at[m, "open"]))
            dur.append(7)
        else:
            r.append(math.log(d.at[p1, "close"] / d.at[m, "open"]))
            dur.append((p1 - m).days + 1)
    bh = math.log(d.at[p1, "close"] / d.at[mondays[0], "open"])
    return Sleeve(name, r, h, dur, 0.002, False, w, bh, label)


def weekly_sleeve_daily(d, wc, sma, p0, p1, w, name, label):
    """Same position but on DAILY bars (sensitivity for spell granularity)."""
    days = pd.date_range(p0, p1, freq="D")
    o = d.loc[days, "open"].values
    c = d.loc[days, "close"].values
    r = np.r_[np.log(o[1:] / o[:-1]), math.log(c[-1] / o[-1])]
    h = np.zeros(len(days), np.int8)
    for i, t in enumerate(days):
        m = t - pd.Timedelta(days=t.weekday())
        sun = m - pd.Timedelta(days=1)
        h[i] = 1 if wc.loc[sun] > sma.loc[sun] else 0
    return Sleeve(name, r, h, np.ones(len(days)), 0.002, False, w, math.log(c[-1] / o[0]), label)


# ============================================================ C9 (4h breakout 55/20)
END_MS = int(pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC").value // 10**6)


def c9_load(sym):
    df = pd.read_csv(os.path.join(DATA, "C9", f"{sym}USDT_4h_binance_spot.csv"))
    df = df.drop_duplicates("open_time").sort_values("open_time")
    df = df[df["close_time"] <= END_MS].reset_index(drop=True)
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    tgt = np.zeros(n, np.int8)
    st = 0
    for t in range(n):
        ent = t >= 55 and cl[t] > hi[t - 55:t].max()
        ex = t >= 20 and cl[t] < lo[t - 20:t].min()
        if st == 0 and ent:
            st = 1
        elif st == 1 and ex:
            st = 0
        tgt[t] = st
    return df, tgt


def c9_sleeve(df, tgt, p0_ms, p1_ms, name, label):
    m = (df["open_time"] >= p0_ms) & (df["close_time"] <= p1_ms)
    idx = np.flatnonzero(m.values)
    if len(idx) == 0:
        return None
    i0, i1 = idx[0], idx[-1]
    assert (np.diff(idx) == 1).all()
    o, c, ot = df["open"].values, df["close"].values, df["open_time"].values
    r = np.r_[np.log(o[i0 + 1:i1 + 1] / o[i0:i1]), math.log(c[i1] / o[i1])]
    h = np.array([tgt[i - 1] if i >= 1 else 0 for i in range(i0, i1 + 1)], np.int8)
    dur = np.r_[np.diff(ot[i0:i1 + 1]), 4 * 3600 * 1000].astype(float)
    return Sleeve(name, r, h, dur, 0.002, True, 1 / 3, math.log(c[i1] / o[i0]), label)


# ============================================================ C2 (funding overheat filter)
def c2_build():
    f = pd.DataFrame(json.load(open(os.path.join(DATA, "C2", "binance_fapi_fundingRate_BTCUSDT.json"))))
    f["t"] = pd.to_datetime(f["fundingTime"].astype("int64"), unit="ms")
    f["ri"] = f["fundingRate"].map(lambda x: int(Decimal(x) * Decimal(10**8)))
    f = f.drop_duplicates("t").sort_values("t")
    f = f[f["t"] < pd.Timestamp("2026-10-07")]
    kl = pd.DataFrame(json.load(open(os.path.join(DATA, "C2", "binance_spot_klines_BTCUSDT_1d.json")))).iloc[:, :7]
    kl.columns = ["ot", "open", "high", "low", "close", "vol", "ct"]
    kl["date"] = pd.to_datetime(kl["ot"].astype("int64"), unit="ms")
    kl = kl[pd.to_datetime(kl["ct"].astype("int64"), unit="ms") < pd.Timestamp("2026-10-07")]
    kl = kl.drop_duplicates("date").set_index("date").sort_index()[["open", "close"]].astype(float)
    first = (f["t"].min() + pd.Timedelta(days=7)).ceil("D")
    dates = kl.index[kl.index >= first]
    tt = f["t"].values
    ri = f["ri"].values
    cs = np.r_[0, np.cumsum(ri)]
    pos, st = [], 1
    for D in dates:
        lo = np.searchsorted(tt, np.datetime64(D - pd.Timedelta(days=7)), side="left")
        hi = np.searchsorted(tt, np.datetime64(D), side="left")
        s = cs[hi] - cs[lo]
        if st == 1 and s > 21 * 30000:
            st = 0
        elif st == 0 and s < 21 * 10000:
            st = 1
        pos.append(st)
    return kl, pd.Series(pos, index=dates)


def daily_sleeve(px, pos, s, e, cost, name, label, w=1.0):
    d = px.loc[s:e]
    p = pos.reindex(d.index)
    assert p.notna().all()
    o, c = d["open"].values, d["close"].values
    r = np.r_[np.log(o[1:] / o[:-1]), math.log(c[-1] / o[-1])]
    return Sleeve(name, r, p.values.astype(np.int8), np.ones(len(d)), cost, True, w, math.log(c[-1] / o[0]), label)


# ============================================================ C5 (Fear & Greed)
def c5_build():
    fng = json.load(open(os.path.join(DATA, "C5", "fng.json")))["data"]
    fgi = pd.Series({pd.to_datetime(int(x["timestamp"]), unit="s"): int(x["value"]) for x in fng}).sort_index()
    fgi = fgi[fgi.index <= pd.Timestamp("2026-10-06")]
    rows = []
    for p in sorted(glob.glob(os.path.join(DATA, "C5", "btcusdt_1d_part*.json"))):
        rows += json.load(open(p))
    k = pd.DataFrame(rows).iloc[:, :7]
    k.columns = ["ot", "open", "high", "low", "close", "vol", "ct"]
    k = k.drop_duplicates("ot")
    k.index = pd.to_datetime(k["ot"], unit="ms")
    k = k[["open", "close"]].astype(float).sort_index()
    k = k[k.index <= pd.Timestamp("2026-10-06")]
    return fgi, k


def c5_pos(fgi, k, s, e):
    days = k.loc[s:e].index
    st, out = 0, []
    for t in days:
        sd = t - pd.Timedelta(days=1)
        if sd in fgi.index:
            v = fgi[sd]
            if st == 0 and v <= 20:
                st = 1
            elif st == 1 and v >= 80:
                st = 0
        out.append(st)
    return pd.Series(out, index=days)


# ============================================================ C13 (gold MACD + EMA220)
def ema_seed(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    v = np.flatnonzero(~np.isnan(x))
    s = v[0]
    out[s + n - 1] = x[s:s + n].mean()
    a = 2 / (n + 1)
    for i in range(s + n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def c13_build():
    d = json.load(open(os.path.join(DATA, "C13", "GC_F_1d_period.json")))["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": d["timestamp"], "o": q["open"], "c": q["close"]})
    df["date"] = pd.to_datetime(df["ts"], unit="s").dt.normalize()
    df = df.dropna(subset=["o", "c"])
    df = df[df["date"] <= pd.Timestamp("2026-10-06")].reset_index(drop=True)
    c = df["c"].values.astype(float)
    macd = ema_seed(c, 12) - ema_seed(c, 26)
    sig = ema_seed(macd, 9)
    e220 = ema_seed(c, 220)
    valid = ~np.isnan(macd) & ~np.isnan(sig) & ~np.isnan(e220)
    ls = valid & (macd > sig) & (c > e220)
    return df, ls.astype(np.int8), int(np.argmax(valid))


def c13_sleeve(df, ls, i0, i1, name, label):
    o, c = df["o"].values.astype(float), df["c"].values.astype(float)
    r = np.r_[np.log(o[i0 + 1:i1 + 1] / o[i0:i1]), math.log(c[i1] / o[i1])]
    h = ls[i0 - 1:i1].copy()
    return Sleeve(name, r, h, np.ones(len(r)), 0.0005, True, 1.0, math.log(c[i1] / o[i0]), label)


# ============================================================ build all
def build():
    S = {}
    btc, eth = load_daily("BTC"), load_daily("ETH")
    wb, sb = weekly_signal(btc)
    we, se = weekly_signal(eth)
    # common start per SPEC.md (also needs RSI14/ret12, which become defined earlier than SMA40)
    first_sun = max(sb.first_valid_index(), se.first_valid_index())
    p0 = first_sun + pd.Timedelta(days=1)
    END = pd.Timestamp("2026-10-06")
    per = {"IS": (p0, pd.Timestamp("2021-12-31")), "OOS": (pd.Timestamp("2022-01-03"), END), "FULL": (p0, END)}
    for P, (a, b) in per.items():
        S[("S2", P)] = [weekly_sleeve(btc, wb, sb, a, b, 1.0, "BTC", f"{a.date()}..{b.date()}")]
        S[("S6", P)] = [weekly_sleeve(btc, wb, sb, a, b, 0.5, "BTC", f"{a.date()}..{b.date()}"),
                        weekly_sleeve(eth, we, se, a, b, 0.5, "ETH", f"{a.date()}..{b.date()}")]
        S[("S2d", P)] = [weekly_sleeve_daily(btc, wb, sb, a, b, 1.0, "BTC", "")]
        S[("S6d", P)] = [weekly_sleeve_daily(btc, wb, sb, a, b, 0.5, "BTC", ""),
                         weekly_sleeve_daily(eth, we, se, a, b, 0.5, "ETH", "")]
    # C9
    c9 = {s: c9_load(s) for s in ("BTC", "ETH", "SOL")}
    ms = lambda ts: int(pd.Timestamp(ts, tz="UTC").value // 10**6)
    per9 = {"IS": (ms("2000-01-01"), ms("2022-12-31 23:59:59.999")),
            "OOS": (ms("2023-01-01"), END_MS), "FULL": (ms("2000-01-01"), END_MS)}
    for P, (a, b) in per9.items():
        sl = [c9_sleeve(c9[s][0], c9[s][1], a, b, s, "") for s in ("BTC", "ETH", "SOL")]
        S[("C9", P)] = [x for x in sl if x is not None]
    # C2
    kl, pos2 = c2_build()
    s2 = pos2.index[0]
    per2 = {"IS": (s2, pd.Timestamp("2022-12-31")), "OOS": (pd.Timestamp("2023-01-01"), END), "FULL": (s2, END)}
    for P, (a, b) in per2.items():
        S[("C2", P)] = [daily_sleeve(kl, pos2, a, b, 0.002, "BTC", f"{a.date()}..{b.date()}")]
    # C5 (each period restarts in USDT)
    fgi, k5 = c5_build()
    f0 = fgi.index[0]
    per5 = {"IS": (f0, pd.Timestamp("2022-12-31")), "OOS": (pd.Timestamp("2023-01-01"), END), "FULL": (f0, END)}
    for P, (a, b) in per5.items():
        S[("C5", P)] = [daily_sleeve(k5, c5_pos(fgi, k5, a, b), a, b, 0.002, "BTC", f"{a.date()}..{b.date()}")]
    # C13
    df13, ls13, fv = c13_build()
    is_i0 = fv + 1
    is_i1 = int(np.flatnonzero(df13["date"] <= pd.Timestamp("2022-12-31"))[-1])
    oos_i0 = int(np.flatnonzero(df13["date"] >= pd.Timestamp("2023-01-01"))[0])
    n13 = len(df13) - 1
    for P, (a, b) in {"IS": (is_i0, is_i1), "OOS": (oos_i0, n13), "FULL": (is_i0, n13)}.items():
        S[("C13", P)] = [c13_sleeve(df13, ls13, a, b, "GOLD",
                                    f"{df13['date'][a].date()}..{df13['date'][b].date()}")]
    return S


def trades_count(strat, sleeves):
    tot = 0
    for s in sleeves:
        e, x = s.n_entries_exits()
        if strat.startswith("S"):
            tot += e + x            # SPEC.md: each buy or sell = 1 trade (no forced end sale)
        else:
            tot += e                # SPEC2: round trips (incl. forced end-of-period close)
    return tot


def prior_values():
    pv = {}
    rows = json.load(open(os.path.join(PRIOR, "weekly_final_rows.json")))
    for r in rows:
        if r["variant"] == "primary" and r["strategy"] in ("S2_TREND_BTC_40W", "S6_TREND_50_50_40W"):
            pv[(r["strategy"][:2], r["period"])] = (r["final_value"] - 100, r["trades"])
    c9 = json.load(open(os.path.join(PRIOR, "C9_result.json")))["periods"]
    for P, r in c9.items():
        pv[("C9", P)] = (r["ret"], r["trades"])
    for r in json.load(open(os.path.join(PRIOR, "C2_result.json")))["rows"]:
        pv[("C2", r["period"])] = (r["net_return_pct"], r["trades"])
    for P, r in json.load(open(os.path.join(PRIOR, "C5_result.json")))["periods"].items():
        pv[("C5", P)] = (r["net_return_pct"], r["trades"])
    for P, r in json.load(open(os.path.join(PRIOR, "C13_result.json")))["periods"].items():
        pv[("C13", P)] = (r["strategy"]["net_return_pct"], r["strategy"]["trades"])
    return pv


def holm(pvals, alpha=0.05):
    m = len(pvals)
    order = np.argsort(pvals)
    rej = np.zeros(m, bool)
    adj = np.zeros(m)
    run = 0.0
    for rank, i in enumerate(order):
        a = min(1.0, (m - rank) * pvals[i])
        run = max(run, a)
        adj[i] = run
    for rank, i in enumerate(order):
        if pvals[i] <= alpha / (m - rank):
            rej[i] = True
        else:
            break
    return rej, adj


def main():
    S = build()
    pv = prior_values()
    rng = np.random.default_rng(SEED)
    res = {}
    print(f"N_PERM={N_PERM} SEED={SEED}")
    print("=== reproduction vs prior published values ===")
    repro = []
    for key in [(s, P) for s in ("S2", "S6", "C9", "C2", "C5", "C13") for P in ("IS", "OOS", "FULL")]:
        sl = S[key]
        g = [s.net() for s in sl]
        net = (np.exp(port_log(sl, g)) - 1) * 100
        tr = trades_count(key[0], sl)
        pnet, ptr = pv[key]
        rel = abs((1 + net / 100) - (1 + pnet / 100)) / (1 + pnet / 100)
        repro.append(dict(key=key, net=net, prior=pnet, rel=rel, trades=tr, prior_trades=ptr))
        print(f"{key[0]:4s} {key[1]:4s} net={net:10.3f}% prior={pnet:10.3f}% rel_final={rel:.2e} trades={tr} prior={ptr}")

    print("\n=== self-check: vectorised null == explicit bar loop ===")
    chk_rng = np.random.default_rng(1)
    for key in [("S2", "OOS"), ("C9", "OOS"), ("C13", "FULL"), ("C2", "OOS"), ("C5", "IS")]:
        for s in S[key]:
            vals, L, s0 = s.null(20, chk_rng)
            lens, st = s.runs()
            for j in range(20):
                h = s.schedule_from_L(L[j], s0)
                l2, st2 = Sleeve(s.name, s.r, h, s.dur, s.cost, s.end_cost, s.w, s.bh_log).runs()
                assert sorted(l2[st2 == 1]) == sorted(lens[st == 1]) and sorted(l2[st2 == 0]) == sorted(lens[st == 0])
                assert st2[0] == st[0] and h[-1] == s.h[-1] and len(h) == len(s.h)
                assert abs(s.net(h) - vals[j]) < 1e-9, (key, s.name, s.net(h), vals[j])
                # explicit bar-by-bar equity loop with costs per entry/exit
                eq, inpos = 1.0, 0
                for i in range(len(h)):
                    if h[i] == 1 and not inpos:
                        eq *= (1 - s.cost); inpos = 1
                    elif h[i] == 0 and inpos:
                        eq *= (1 - s.cost); inpos = 0
                    if inpos:
                        eq *= math.exp(s.r[i])
                if inpos and s.end_cost:
                    eq *= (1 - s.cost)
                assert abs(math.log(eq) - vals[j]) < 1e-9
    print("ok")

    print("\n=== permutation test ===")
    for key in [(s, P) for s in ("S2", "S6", "C9", "C2", "C5", "C13", "S2d", "S6d") for P in ("IS", "OOS", "FULL")]:
        sl = S[key]
        act_g = [s.net() for s in sl]
        act = float(port_log(sl, act_g))
        nulls = [s.null(N_PERM, rng)[0] for s in sl]
        nul = port_log(sl, nulls)
        p = (1 + int((nul >= act - TOL).sum())) / (1 + N_PERM)
        se = math.sqrt(p * (1 - p) / N_PERM)
        p_sl = [(1 + int((n >= a - TOL).sum())) / (1 + N_PERM) for n, a in zip(nulls, act_g)]
        expo = [s.exposure() for s in sl]
        emb = float(np.log(sum(s.w * np.exp(e * s.bh_log) for s, e in zip(sl, expo)) + (1 - sum(s.w for s in sl))))
        bh = float(np.log(sum(s.w * np.exp(s.bh_log) for s in sl) + (1 - sum(s.w for s in sl))))
        nsp = [int((s.runs()[1] == 1).sum()) for s in sl]
        # number of distinct orderings (upper bound, ignoring equal lengths)
        dist = 1
        for s in sl:
            lens, st = s.runs()
            from collections import Counter
            for arr in (lens[st == 1], lens[st == 0]):
                c = Counter(arr.tolist())
                dist *= math.factorial(len(arr)) // math.prod(math.factorial(v) for v in c.values())
        res[f"{key[0]}|{key[1]}"] = dict(
            window=[s.label for s in sl][0], net_pct=(math.exp(act) - 1) * 100, logret=act,
            null_median=float(np.median(nul)), null_p5=float(np.percentile(nul, 5)), null_p95=float(np.percentile(nul, 95)),
            p=p, mc_se=se, p_sleeves=p_sl, exposure=expo, expo_matched_bh_log=emb, bh_log=bh, in_spells=nsp,
            distinct_orderings=dist if dist < 10**9 else ">1e9",
            cost_logs=[s.cost_log() for s in sl])
        print(f"{key[0]:4s} {key[1]:4s} net={res[f'{key[0]}|{key[1]}']['net_pct']:9.2f}% log={act:.3f} "
              f"null_med={np.median(nul):.3f} p5..p95={np.percentile(nul,5):.3f}..{np.percentile(nul,95):.3f} "
              f"p={p:.4f}±{se:.4f} p_sl={[round(x,3) for x in p_sl]} expoBH={emb:.3f} BH={bh:.3f} "
              f"expo={[round(e*100,2) for e in expo]} spells={nsp} orderings={res[f'{key[0]}|{key[1]}']['distinct_orderings']}")

    print("\n=== Holm-Bonferroni, m=25 (6 OOS p + 19 p=1) ===")
    names = ["S2", "S6", "C9", "C2", "C5", "C13"]
    ps = np.array([res[f"{n}|OOS"]["p"] for n in names] + [1.0] * 19)
    rej, adj = holm(ps)
    for i, n in enumerate(names):
        print(f"{n}: p={ps[i]:.4f} holm_adj={adj[i]:.3f} reject={rej[i]}")
    order = np.argsort(ps)
    for rank, i in enumerate(order[:6]):
        print(f"  rank {rank+1}: {names[i] if i < 6 else 'untested'} p={ps[i]:.4f} thr={0.05/(25-rank):.5f}")
    print("rejected:", int(rej.sum()))
    # raw p < 0.05
    for P in ("IS", "OOS", "FULL"):
        print(P, "raw p<0.05:", [(n, round(res[f'{n}|{P}']['p'], 4)) for n in names if res[f"{n}|{P}"]["p"] < 0.05])
    out = dict(n_perm=N_PERM, seed=SEED, reproduction=[{**r, "key": "|".join(r["key"])} for r in repro],
               tests=res, holm=dict(p=ps.tolist(), adj=adj.tolist(), rejected=int(rej.sum())))
    json.dump(out, open(os.path.join(OUT, f"verify_result_n{N_PERM}_s{SEED}.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
