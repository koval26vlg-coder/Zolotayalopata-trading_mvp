# C8 IMPULSE_PULLBACK_BREAKOUT_4H  (SPEC2.md, frozen 2026-10-07)
# Assets: Binance spot BTCUSDT, ETHUSDT, SOLUSDT 4h. Each asset = independent 1/3 sleeve.
# Rule (frozen):
#   ATR(14) (Wilder). Impulse at closed bar t: close_t - min(low[t-5..t]) >= 3*ATR_t.
#   L0 = min(low[t-5..t]) (impulse start low), H = max(high[t-5..t]) (impulse high), R = H - L0.
#   Within the next 12 bars (t+1..t+12): pullback low PL = min(low[t+1..j]) must retrace
#   >= 38.2% and <= 61.8% of R (retrace = (H-PL)/R), with no close < L0; then a close > H at bar j
#   -> entry at open of bar j+1. Stop = PL, TP = entry + 3*(entry-stop).
#   Risk 1% of sleeve equity per trade, notional capped at 100% of sleeve. Intrabar: stop first.
# Implementation choices (fixed BEFORE looking at results, no tuning):
#   * the whole pattern (pullback + breakout close) must complete within t+1..t+12;
#   * a close > H before the pullback reached 38.2% cancels the setup (breakout without pullback);
#   * retrace > 61.8% (low-based) or close < L0 cancels the setup immediately;
#   * one setup per asset at a time; a new impulse is armed only when flat and no setup is pending
#     (checked at the close of the bar on which a previous setup was cancelled/expired too);
#   * if the entry open <= stop (gap through stop) the trade is skipped;
#   * gap-through on later bars: exit at the open if open <= stop or open >= TP;
#   * no time exit (none in spec); open position is force-closed at the last bar close of the period;
#   * costs 20 bps per side on notional (2x stress = 40 bps);
#   * IS / OOS / FULL are separate runs with fresh capital; indicators use all prior data (causal);
#     setups are armed only from the first bar of the period.
import os, json, hashlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
COST = 0.0020
CUTOFF_CLOSE_MS = 1791331199999          # 2026-10-06 23:59:59.999 UTC
OOS_START = pd.Timestamp("2023-01-01", tz="UTC")
WARMUP = 50                              # bars before any setup can be armed in a series
ATR_N, IMP_LB, IMP_K, WIN = 14, 5, 3.0, 12
RET_LO, RET_HI, TP_R, RISK = 0.382, 0.618, 3.0, 0.01
MIN_NOTIONAL_USD = 5.0                   # Binance spot NOTIONAL filter for these pairs (approx., 5 USDT)


def sha256(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load(sym):
    p = os.path.join(DATA, f"{sym}_4h_raw.csv")
    d = pd.read_csv(p)
    d = d[d.close_time <= CUTOFF_CLOSE_MS].copy()
    d = d.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    assert d.open_time.is_monotonic_increasing
    d["t"] = pd.to_datetime(d.open_time, unit="ms", utc=True)
    d["tc"] = pd.to_datetime(d.close_time + 1, unit="ms", utc=True)  # bar close instant
    return d[["t", "tc", "open", "high", "low", "close"]].astype(
        {"open": float, "high": float, "low": float, "close": float}), p


def wilder_atr(h, l, c, n=ATR_N):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    atr = np.full(len(c), np.nan)
    if len(c) < n:
        return atr
    atr[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def features(d):
    o, h, l, c = (d[k].values for k in ("open", "high", "low", "close"))
    atr = wilder_atr(h, l, c)
    lmin = pd.Series(l).rolling(IMP_LB + 1).min().values   # t-5..t
    hmax = pd.Series(h).rolling(IMP_LB + 1).max().values
    imp = (c - lmin) >= IMP_K * atr
    imp = np.where(np.isnan(atr) | np.isnan(lmin), False, imp)
    return dict(o=o, h=h, l=l, c=c, atr=atr, lmin=lmin, hmax=hmax, imp=imp)


def simulate(F, s0, s1, e0, cost):
    """Bar loop over indices s0..s1 (inclusive). Returns trades, equity array (per bar close), notional array."""
    o, h, l, c, imp, lmin, hmax = F["o"], F["h"], F["l"], F["c"], F["imp"], F["lmin"], F["hmax"]
    cash, qty = e0, 0.0
    pos = None          # dict when in position
    setup = None        # dict when a setup is pending
    pend = None         # dict: entry scheduled at next bar open
    trades, skipped = [], 0
    eq = np.empty(s1 - s0 + 1)
    notional = np.empty(s1 - s0 + 1)
    for j in range(s0, s1 + 1):
        # 1) scheduled entry at this bar's open
        if pend is not None:
            entry = o[j]
            stop = pend["stop"]
            if entry > stop:
                rps = entry - stop
                q_risk = RISK * cash / rps
                q_cap = cash / (entry * (1 + cost))
                q = min(q_risk, q_cap)
                ncost = q * entry * cost
                cash -= q * entry + ncost
                qty = q
                pos = dict(sig=pend["sig"], imp=pend["imp"], ent=j, entry=entry, stop=stop,
                           tp=entry + TP_R * rps, q=q, cost_in=ncost, notional=q * entry,
                           eq_before=cash + q * entry + ncost, H=pend["H"], L0=pend["L0"],
                           capped=q_cap < q_risk)
            else:
                skipped += 1
            pend = None
        # 2) exits for this bar (stop-first)
        if pos is not None:
            ex, why, both = None, None, False
            if j > pos["ent"] and o[j] <= pos["stop"]:
                ex, why = o[j], "gap_stop"
            elif j > pos["ent"] and o[j] >= pos["tp"]:
                ex, why = o[j], "gap_tp"
            else:
                hit_s, hit_t = l[j] <= pos["stop"], h[j] >= pos["tp"]
                both = hit_s and hit_t
                if hit_s:
                    ex, why = pos["stop"], "stop"
                elif hit_t:
                    ex, why = pos["tp"], "tp"
            if ex is None and j == s1:
                ex, why = c[j], "end_of_period"
            if ex is not None:
                proceeds = pos["q"] * ex * (1 - cost)
                pnl = proceeds - pos["notional"] - pos["cost_in"]
                cash += proceeds
                qty = 0.0
                trades.append(dict(sig=pos["sig"], imp=pos["imp"], ent=pos["ent"], ex=j, entry=pos["entry"],
                                   exit=ex, stop=pos["stop"], tp=pos["tp"], why=why, both_touched=both,
                                   pnl=pnl, ret=pnl / pos["eq_before"], notional_frac=pos["notional"] / pos["eq_before"],
                                   capped=pos["capped"], H=pos["H"], L0=pos["L0"]))
                pos = None
        eq[j - s0] = cash + qty * c[j]
        notional[j - s0] = qty * c[j]
        # 3) setup logic at the close of bar j (only when flat and nothing scheduled)
        if pos is None and pend is None:
            if setup is not None:
                setup["PL"] = min(setup["PL"], l[j])
                H, L0 = setup["H"], setup["L0"]
                R = H - L0
                if c[j] < L0 or setup["PL"] < H - RET_HI * R:
                    setup = None
                elif c[j] > H:
                    if setup["PL"] <= H - RET_LO * R and j < s1:
                        pend = dict(sig=j, imp=setup["t"], stop=setup["PL"], H=H, L0=L0)
                    setup = None
                elif j - setup["t"] >= WIN:
                    setup = None
            if setup is None and pend is None and imp[j] and j >= WARMUP and j < s1:
                setup = dict(t=j, H=hmax[j], L0=lmin[j], PL=np.inf)
    return trades, eq, notional, skipped


def max_dd(series):
    v = np.asarray(series, float)
    peak = np.maximum.accumulate(v)
    return float(((v / peak) - 1).min() * 100)


def run_period(D, FE, start, end, cost, e_total=1.0):
    """start/end: Timestamps (bar open time inclusive start, bar open < end)."""
    e0 = e_total / len(SYMS)
    grid = sorted(set().union(*[set(D[s].t[(D[s].t >= start) & (D[s].t < end)]) for s in SYMS]))
    grid = pd.DatetimeIndex(grid)
    eq_cols, no_cols, bh_cols, all_trades, info = {}, {}, {}, [], {}
    for s in SYMS:
        d = D[s]
        idx = np.where((d.t >= start) & (d.t < end))[0]
        idx = idx[idx >= WARMUP]
        if len(idx) == 0:
            eq_cols[s] = pd.Series(e0, index=grid); no_cols[s] = pd.Series(0.0, index=grid)
            bh_cols[s] = pd.Series(e0, index=grid); continue
        s0, s1 = int(idx[0]), int(idx[-1])
        tr, eq, no, skipped = simulate(FE[s], s0, s1, e0, cost)
        for t in tr:
            t["sym"] = s
        all_trades += tr
        ts = d.t.iloc[s0:s1 + 1].values; ts = pd.DatetimeIndex(d.t.iloc[s0:s1 + 1])
        assert pd.Series(eq, index=ts).reindex(grid).notna().sum() == len(eq), "grid alignment"
        eq_cols[s] = pd.Series(eq, index=pd.DatetimeIndex(ts)).reindex(grid).ffill().fillna(e0)
        no_cols[s] = pd.Series(no, index=pd.DatetimeIndex(ts)).reindex(grid).ffill().fillna(0.0)
        # benchmark: buy at first bar open, hold, sell at last close (cost both sides)
        o0 = d.open.values[s0]
        bh = e0 * (1 - cost) * d.close.values[s0:s1 + 1] / o0
        bh[-1] *= (1 - cost)
        bh_cols[s] = pd.Series(bh, index=pd.DatetimeIndex(ts)).reindex(grid).ffill().fillna(e0)
        info[s] = dict(first_bar=str(d.t.iloc[s0]), last_bar=str(d.t.iloc[s1]), trades=len(tr), skipped_gap=skipped,
                       sleeve_ret_pct=round((eq[-1] / e0 - 1) * 100, 2),
                       bh_ret_pct=round((bh[-1] / e0 - 1) * 100, 2))
    E = sum(eq_cols.values()); N = sum(no_cols.values()); B = sum(bh_cols.values())
    # daily marks: last 4h close of each UTC day (bar open 20:00 closes at 24:00)
    day = (grid + pd.Timedelta(hours=4) - pd.Timedelta(milliseconds=1)).floor("D")
    Ed = E.groupby(day).last(); Bd = B.groupby(day).last()
    Ed = pd.concat([pd.Series([e_total], index=[Ed.index[0] - pd.Timedelta(days=1)]), Ed])
    Bd = pd.concat([pd.Series([e_total], index=[Bd.index[0] - pd.Timedelta(days=1)]), Bd])
    years = (grid[-1] + pd.Timedelta(hours=4) - grid[0]).total_seconds() / (365.25 * 86400)
    pnl = np.array([t["pnl"] for t in all_trades])
    gw, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    net = (E.iloc[-1] / e_total - 1) * 100
    bnet = (B.iloc[-1] / e_total - 1) * 100
    res = dict(
        trades=int(len(pnl)),
        win_rate_pct=round(float((pnl > 0).mean() * 100), 2) if len(pnl) else None,
        pf=round(float(gw / gl), 3) if gl > 0 else None,
        net_return_pct=round(float(net), 2),
        cagr_pct=round(float(((E.iloc[-1] / e_total) ** (1 / years) - 1) * 100), 2),
        max_dd_pct=round(max_dd(Ed.values), 2),
        max_dd_4h_pct=round(max_dd(np.r_[e_total, E.values]), 2),
        exposure_pct=round(float((N / E).mean() * 100), 2),
        time_in_market_pct=round(float(np.mean([(no_cols[s] > 0).mean() for s in SYMS]) * 100), 2),
        bench_net_return_pct=round(float(bnet), 2),
        bench_cagr_pct=round(float(((B.iloc[-1] / e_total) ** (1 / years) - 1) * 100), 2),
        bench_max_dd_pct=round(max_dd(Bd.values), 2),
        start=str(grid[0]), end=str(grid[-1] + pd.Timedelta(hours=4)), years=round(years, 3),
        per_asset=info,
    )
    return res, all_trades, E


def self_checks(D, FE, trades_full):
    chk = {}
    # (a) signal bar < entry bar, entry == next open, exit >= entry
    ok = all(t["sig"] < t["ent"] and t["ent"] == t["sig"] + 1 and t["ex"] >= t["ent"]
             and abs(t["entry"] - FE[t["sym"]]["o"][t["ent"]]) < 1e-12 and t["imp"] < t["sig"] for t in trades_full)
    chk["signal_before_entry_and_entry_at_next_open"] = ok
    # (b) stop-first: every bar where stop and TP both touched -> exit reason stop
    both = [t for t in trades_full if t["both_touched"]]
    chk["both_touched_bars"] = len(both)
    chk["both_touched_resolved_as_stop"] = all(t["why"] == "stop" for t in both)
    # (c) pattern re-verification from raw arrays
    bad = 0
    for t in trades_full:
        F = FE[t["sym"]]
        i, j = t["imp"], t["sig"]
        H, L0 = F["hmax"][i], F["lmin"][i]
        R = H - L0
        PL = F["l"][i + 1:j + 1].min()
        r = (H - PL) / R
        cond = (F["imp"][i] and 1 <= j - i <= WIN and F["c"][j] > H and RET_LO - 1e-12 <= r <= RET_HI + 1e-12
                and (F["c"][i + 1:j + 1] >= L0).all() and abs(PL - t["stop"]) < 1e-12
                and abs(t["tp"] - (t["entry"] + TP_R * (t["entry"] - t["stop"]))) < 1e-9 and t["stop"] < t["entry"])
        bad += (not cond)
    chk["pattern_reverified_bad_count"] = bad
    # (d) ATR causality: value at bar k computed on truncated data equals full-series value
    rng = np.random.default_rng(0)
    worst = 0.0
    for s in SYMS:
        d = D[s]
        for k in rng.integers(200, len(d) - 1, 5):
            a = wilder_atr(d.high.values[:k + 1], d.low.values[:k + 1], d.close.values[:k + 1])[-1]
            worst = max(worst, abs(a - FE[s]["atr"][k]))
    chk["atr_truncation_max_abs_diff"] = float(worst)
    # (e) truncation invariance: rerun on data cut at 2024-06-30; closed trades before cut must be identical
    cut = pd.Timestamp("2024-06-30", tz="UTC")
    same = True
    n_cmp = 0
    for s in SYMS:
        d = D[s][D[s].t < cut].reset_index(drop=True)
        F2 = features(d)
        for k in F2:
            n0 = len(d)
            assert np.allclose(F2[k][WARMUP:n0], FE[s][k][WARMUP:n0], equal_nan=True), k
        tr2, _, _, _ = simulate(F2, WARMUP, len(d) - 1, 1 / 3, COST)
        full_s = [t for t in trades_full if t["sym"] == s and t["ex"] <= len(d) - 1]
        tr2 = [t for t in tr2 if t["why"] != "end_of_period"]
        a = [(t["ent"], t["ex"], round(t["entry"], 8), round(t["exit"], 8)) for t in full_s]
        b = [(t["ent"], t["ex"], round(t["entry"], 8), round(t["exit"], 8)) for t in tr2]
        same &= (a == b)
        n_cmp += len(a)
    chk["truncation_invariance_trades_identical"] = bool(same)
    chk["truncation_invariance_trades_compared"] = n_cmp
    # (f) synthetic unit tests of the intrabar rule (no real bar had stop & TP both touched)
    def synth(exit_bar):
        n = 70
        o = np.full(n, 100.0); h = np.full(n, 100.5); l = np.full(n, 99.5); c = np.full(n, 100.0)
        imp = np.zeros(n, bool); lmin = np.full(n, 99.5); hmax = np.full(n, 100.5)
        imp[55], lmin[55], hmax[55] = True, 100.0, 110.0               # H=110, L0=100, R=10
        o[55], h[55], l[55], c[55] = 101, 110, 100, 109
        o[56], h[56], l[56], c[56] = 109, 109, 105, 106                # PL=105 -> retrace 50%
        o[57], h[57], l[57], c[57] = 106, 111.5, 105.5, 111            # close > H -> signal
        o[58:], h[58:], l[58:], c[58:] = 111, 112, 110, 111.5          # entry 111, stop 105, TP 129
        o[59], h[59], l[59], c[59] = exit_bar
        F = dict(o=o, h=h, l=l, c=c, imp=imp, lmin=lmin, hmax=hmax)
        tr, _, _, _ = simulate(F, WARMUP, n - 1, 1.0, COST)
        return tr
    t1 = synth((111, 130, 104, 120))      # both touched in one bar -> must be stop at 105
    t2 = synth((104, 106, 103, 105.5))    # gap below stop -> exit at open 104
    chk["synthetic_both_touched_exits_at_stop"] = bool(len(t1) == 1 and t1[0]["why"] == "stop"
                                                       and t1[0]["exit"] == 105 and t1[0]["sig"] == 57
                                                       and t1[0]["ent"] == 58 and t1[0]["entry"] == 111)
    chk["synthetic_gap_through_stop_exits_at_open"] = bool(len(t2) == 1 and t2[0]["why"] == "gap_stop"
                                                           and t2[0]["exit"] == 104)
    return chk


def main():
    D, FE, srcs = {}, {}, []
    for s in SYMS:
        D[s], p = load(s)
        FE[s] = features(D[s])
        srcs.append(dict(name=f"Binance spot {s} 4h klines (api.binance.com/api/v3/klines)",
                         url=f"https://api.binance.com/api/v3/klines?symbol={s}&interval=4h",
                         start=str(D[s].t.iloc[0]), end=str(D[s].tc.iloc[-1]), rows=int(len(D[s])),
                         sha256=sha256(p), file=p))
    t_first = min(D[s].t.iloc[0] for s in SYMS)
    t_end = max(D[s].tc.iloc[-1] for s in SYMS)
    periods = {"IS": (t_first, OOS_START), "OOS": (OOS_START, t_end), "FULL": (t_first, t_end)}
    out = {"strategy": "C8 IMPULSE_PULLBACK_BREAKOUT_4H", "data_sources": srcs, "periods": {}}
    trades_by = {}
    for name, (a, b) in periods.items():
        r1, tr, E = run_period(D, FE, a, b, COST)
        r2, tr2, _ = run_period(D, FE, a, b, 2 * COST)
        r1["net_return_2x_cost_pct"] = r2["net_return_pct"]
        r1["pf_2x_cost"] = r2["pf"]
        # time in market (avg over sleeves, fraction of bars in position)
        r1["exit_reasons"] = pd.Series([t["why"] for t in tr]).value_counts().to_dict() if tr else {}
        r1["avg_notional_frac_pct"] = round(float(np.mean([t["notional_frac"] for t in tr]) * 100), 2) if tr else None
        r1["share_trades_capped_pct"] = round(float(np.mean([t["capped"] for t in tr]) * 100), 2) if tr else None
        r1["avg_bars_held"] = round(float(np.mean([t["ex"] - t["ent"] + 1 for t in tr])), 2) if tr else None
        # $100 feasibility: sleeve $33.33 scaled by sleeve equity path ~ use notional_frac * sleeve equity before trade
        if tr:
            e0usd = 100 / 3
            # sleeve equity before trade in $ (from fresh $33.33 at period start)
            usd_notional = []
            for s in SYMS:
                eqs = e0usd
                for t in sorted([t for t in tr if t["sym"] == s], key=lambda x: x["ent"]):
                    usd_notional.append(t["notional_frac"] * eqs)
                    eqs *= (1 + t["ret"])
            usd_notional = np.array(usd_notional)
            r1["usd100_median_order_usd"] = round(float(np.median(usd_notional)), 2)
            r1["usd100_share_below_min_notional_pct"] = round(float((usd_notional < MIN_NOTIONAL_USD).mean() * 100), 2)
        out["periods"][name] = r1
        trades_by[name] = tr
        pd.DataFrame([{**t, "entry_time": str(D[t["sym"]].t.iloc[t["ent"]]),
                       "signal_bar_time": str(D[t["sym"]].t.iloc[t["sig"]]),
                       "exit_bar_time": str(D[t["sym"]].t.iloc[t["ex"]])} for t in tr]).to_csv(
            os.path.join(HERE, f"trades_{name}.csv"), index=False)
    out["self_checks"] = self_checks(D, FE, trades_by["FULL"])
    # pre-registered verdict on OOS (trade strategy)
    o = out["periods"]["OOS"]
    ratio = lambda r, dd: r / abs(dd) if dd else np.inf
    s_ratio, b_ratio = ratio(o["net_return_pct"], o["max_dd_pct"]), ratio(o["bench_net_return_pct"], o["bench_max_dd_pct"])
    fail = (o["net_return_pct"] <= 0 or (o["pf"] is not None and o["pf"] < 1.0) or
            (o["net_return_pct"] < o["bench_net_return_pct"] and o["max_dd_pct"] < o["bench_max_dd_pct"]))
    if fail:
        v = "FAIL"
    elif o["trades"] < 30:
        v = "INCONCLUSIVE"
    elif (o["net_return_pct"] > 0 and o["pf"] >= 1.2 and s_ratio > b_ratio and o["net_return_2x_cost_pct"] > 0):
        v = "PASS_CANDIDATE"
    else:
        v = "INCONCLUSIVE"
    out["verdict"] = dict(verdict=v, oos_ret_dd_ratio=round(float(s_ratio), 3), bench_ret_dd_ratio=round(float(b_ratio), 3),
                          fail_flags=dict(net_le_0=o["net_return_pct"] <= 0,
                                          pf_lt_1=(o["pf"] is not None and o["pf"] < 1.0),
                                          worse_both=(o["net_return_pct"] < o["bench_net_return_pct"] and
                                                      o["max_dd_pct"] < o["bench_max_dd_pct"])))
    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per_asset"} for k, v in out["periods"].items()},
                     indent=1, default=str))
    print(json.dumps({k: out["periods"][k]["per_asset"] for k in out["periods"]}, indent=1))
    print(json.dumps(out["self_checks"], indent=1))
    print(json.dumps(out["verdict"], indent=1, default=str))


if __name__ == "__main__":
    main()
