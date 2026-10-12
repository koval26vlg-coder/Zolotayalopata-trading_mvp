# C7 TREND_PULLBACK_4H — frozen rule from SPEC2.md (no tuning, no extra variants)
# BTCUSDT / ETHUSDT / SOLUSDT Binance spot 4h.
# Trend: close > EMA200. Setup: low <= EMA50 and close > EMA50 and close > EMA200 (closed bar t).
# Entry: open of bar t+1. Stop = lowest low of the 10 bars before entry (t-9..t). TP = entry + 2R.
# Risk 1% of sleeve equity, notional capped at 100% sleeve equity, one position per asset,
# each asset = own 1/3 sleeve. Intrabar: stop first if both touched. Costs 20 bps/side (stress 40 bps).
import json, os, hashlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
COST = 0.0020
END_MS = 1791331199999  # 2026-10-06 23:59:59.999 UTC
IS_END = pd.Timestamp("2022-12-31 23:59:59.999", tz="UTC")
OOS_START = pd.Timestamp("2023-01-01 00:00:00", tz="UTC")
WARMUP = 200          # bars needed before EMA200 is considered valid
STOP_LB = 10
RISK = 0.01
RR = 2.0
MIN_NOTIONAL = 5.0    # Binance spot NOTIONAL filter (exchangeInfo.json)


def load(sym):
    p = os.path.join(DATA, f"{sym}_4h.json")
    raw = json.load(open(p))
    df = pd.DataFrame(raw, columns=["ot", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "x"])
    for k in ["o", "h", "l", "c", "v"]:
        df[k] = df[k].astype(float)
    df["open_time"] = pd.to_datetime(df["ot"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["ct"], unit="ms", utc=True)
    # data checks
    assert df["ot"].is_monotonic_increasing and not df["ot"].duplicated().any()
    assert (df["ct"] <= END_MS).all(), "bar closing after cutoff"
    assert ((df["h"] >= df[["o", "c"]].max(axis=1)) & (df["l"] <= df[["o", "c"]].min(axis=1))).all()
    df = df.reset_index(drop=True)
    df["ema50"] = df["c"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["c"].ewm(span=200, adjust=False).mean()
    valid = np.arange(len(df)) >= (WARMUP - 1)
    df["setup"] = valid & (df["l"] <= df["ema50"]) & (df["c"] > df["ema50"]) & (df["c"] > df["ema200"])
    gaps = int(((df["ot"].diff().dropna()) != 4 * 3600 * 1000).sum())
    return df, gaps, hashlib.sha256(open(p, "rb").read()).hexdigest(), len(raw)


def sim_sleeve(df, i0, i1, cost, eq0):
    """Event loop over bars i0..i1 (inclusive). Returns marks (equity at each bar close), trades, inpos flags."""
    o, h, l, c = df["o"].values, df["h"].values, df["l"].values, df["c"].values
    setup = df["setup"].values
    cash = eq0
    pos = None
    pending = None
    marks = np.empty(i1 - i0 + 1)
    posval = np.zeros(i1 - i0 + 1)
    inpos = np.zeros(i1 - i0 + 1, dtype=bool)
    trades = []
    ambiguous = []
    for i in range(i0, i1 + 1):
        # 1) execute pending entry at this bar's open
        if pending is not None and pos is None:
            t = pending
            entry = o[i]
            stop = l[t - STOP_LB + 1: t + 1].min()   # 10 bars before entry bar: t-9..t
            if entry > stop:
                R = entry - stop
                qty = RISK * cash / R
                qty = min(qty, cash / (entry * (1 + cost)))  # notional cap = 100% sleeve equity (incl. fee)
                fee = qty * entry * cost
                cash -= qty * entry + fee
                pos = dict(sig=t, ent=i, entry=entry, stop=stop, tp=entry + RR * R, qty=qty, fee_in=fee,
                           stop_win_max=t, eq_before=cash + qty * entry + fee, notional=qty * entry)
            pending = None
        # 2) manage open position inside this bar (stop first)
        if pos is not None:
            inpos[i - i0] = True
            hit_s = l[i] <= pos["stop"]
            hit_t = h[i] >= pos["tp"]
            if hit_s and hit_t:
                ambiguous.append(i)
            px, why = None, None
            if hit_s:
                px, why = min(o[i], pos["stop"]), "stop"   # gap through stop -> fill at open
            elif hit_t:
                px, why = max(o[i], pos["tp"]), "tp"
            if px is not None:
                fee = pos["qty"] * px * cost
                cash += pos["qty"] * px - fee
                pnl = pos["qty"] * (px - pos["entry"]) - pos["fee_in"] - fee
                trades.append(dict(pos, exit_i=i, exit=px, why=why, pnl=pnl, ambiguous=bool(hit_s and hit_t)))
                pos = None
        # 3) signal at this bar's close (only if flat and an entry bar exists inside the period)
        if pos is None and setup[i] and i < i1:
            pending = i
        pv = pos["qty"] * c[i] if pos is not None else 0.0
        posval[i - i0] = pv
        marks[i - i0] = cash + pv
    if pos is not None:  # forced exit at last close of the period
        px = c[i1]
        fee = pos["qty"] * px * cost
        cash += pos["qty"] * px - fee
        pnl = pos["qty"] * (px - pos["entry"]) - pos["fee_in"] - fee
        trades.append(dict(pos, exit_i=i1, exit=px, why="period_end", pnl=pnl, ambiguous=False))
        marks[-1] = cash
        posval[-1] = 0.0
    return marks, posval, inpos, trades, ambiguous


def bench_sleeve(df, i0, i1, cost, eq0):
    o, c = df["o"].values, df["c"].values
    qty = eq0 / (o[i0] * (1 + cost))
    marks = qty * c[i0:i1 + 1].copy()
    marks[-1] = qty * c[i1] * (1 - cost)
    return marks


def max_dd(series):
    s = np.asarray(series, dtype=float)
    peak = np.maximum.accumulate(s)
    return float((s / peak - 1).min() * 100)


def run_period(dfs, start_ts, end_ts, cost, eq_total=100.0):
    eq0 = eq_total / 3
    sleeves, bench, alltrades, amb = {}, {}, [], 0
    exp_time = []
    notional_ratio = []
    ref = dfs["BTCUSDT"]
    ref_idx = ref.index[(ref["open_time"] >= start_ts) & (ref["close_time"] <= end_ts)]
    nref = len(ref_idx)
    for s in SYMS:
        df = dfs[s]
        first_valid = df["open_time"].iloc[WARMUP - 1]
        st = max(start_ts, first_valid)
        sel = df.index[(df["open_time"] >= st) & (df["close_time"] <= end_ts)]
        i0, i1 = int(sel[0]), int(sel[-1])
        marks, posval, inpos, trades, ambiguous = sim_sleeve(df, i0, i1, cost, eq0)
        idx = pd.DatetimeIndex(df["close_time"].iloc[i0:i1 + 1])
        sleeves[s] = (pd.Series(marks, index=idx), pd.Series(posval, index=idx))
        bench[s] = pd.Series(bench_sleeve(df, i0, i1, cost, eq0), index=idx)
        for t in trades:
            t["sym"] = s
            t["sig_time"] = str(df["close_time"].iloc[t["sig"]])
            t["ent_time"] = str(df["open_time"].iloc[t["ent"]])
            t["exit_time"] = str(df["close_time"].iloc[t["exit_i"]])
        alltrades += trades
        amb += len(ambiguous)
        exp_time.append(inpos.sum() / nref)
    # align on union timeline (ffill; before a sleeve is active it is cash = eq0)
    tl = sleeves[SYMS[0]][0].index
    for s in SYMS[1:]:
        tl = tl.union(sleeves[s][0].index)
    eq = sum(sleeves[s][0].reindex(tl, method="ffill").fillna(eq0) for s in SYMS)
    pv = sum(sleeves[s][1].reindex(tl, method="ffill").fillna(0.0) for s in SYMS)
    beq = sum(bench[s].reindex(tl, method="ffill").fillna(eq0) for s in SYMS)
    eqd = eq.resample("1D").last().dropna()
    beqd = beq.resample("1D").last().dropna()
    real_start = max(pd.Timestamp(start_ts), dfs["BTCUSDT"]["open_time"].iloc[WARMUP - 1])
    real_end = pd.Timestamp(tl[-1])
    days = (real_end - real_start).total_seconds() / 86400
    pnl = np.array([t["pnl"] for t in alltrades])
    gw, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    net = (eq.iloc[-1] / eq_total - 1) * 100
    bnet = (beq.iloc[-1] / eq_total - 1) * 100
    cagr = ((eq.iloc[-1] / eq_total) ** (365.25 / days) - 1) * 100
    bcagr = ((beq.iloc[-1] / eq_total) ** (365.25 / days) - 1) * 100
    m = dict(
        start=str(real_start), end=str(real_end), days=round(days, 1),
        trades=int(len(pnl)), win_rate_pct=float((pnl > 0).mean() * 100) if len(pnl) else None,
        pf=float(gw / gl) if gl > 0 else None, net_return_pct=float(net), cagr_pct=float(cagr),
        max_dd_pct=max_dd(eqd.values), max_dd_4h_pct=max_dd(eq.values),
        exposure_time_pct=float(np.mean(exp_time) * 100),
        exposure_notional_pct=float((pv / eq).mean() * 100),
        bench_net_return_pct=float(bnet), bench_cagr_pct=float(bcagr), bench_max_dd_pct=max_dd(beqd.values),
        ambiguous_bars=int(amb),
        exits={k: int(sum(1 for t in alltrades if t["why"] == k)) for k in ["stop", "tp", "period_end"]},
        per_asset={s: dict(trades=int(sum(1 for t in alltrades if t["sym"] == s)),
                           pnl_usd_on_100=float(sum(t["pnl"] for t in alltrades if t["sym"] == s)),
                           win_rate_pct=float(np.mean([t["pnl"] > 0 for t in alltrades if t["sym"] == s]) * 100)
                           if any(t["sym"] == s for t in alltrades) else None)
                   for s in SYMS},
        avg_R_multiple=float(np.mean([(t["exit"] - t["entry"]) / (t["entry"] - t["stop"]) for t in alltrades]))
        if alltrades else None,
        median_notional_pct_of_sleeve=float(np.median([t["notional"] / t["eq_before"] * 100 for t in alltrades]))
        if alltrades else None,
        share_notional_capped_pct=float(np.mean([t["notional"] >= t["eq_before"] / (1 + cost) * 0.999
                                                 for t in alltrades]) * 100) if alltrades else None,
    )
    return m, alltrades, eqd, beqd


# ---------------- self-checks against look-ahead ----------------
def self_checks(dfs, trades_full):
    out = {}
    # (a) signal bar strictly before execution bar; signal close time <= entry open time
    out["entry_is_next_bar"] = all(t["ent"] == t["sig"] + 1 for t in trades_full)
    out["signal_close_before_entry_open"] = all(pd.Timestamp(t["sig_time"]) < pd.Timestamp(t["ent_time"]) for t in trades_full)
    # (b) stop window uses only bars < entry bar
    out["stop_window_before_entry"] = all(t["stop_win_max"] < t["ent"] for t in trades_full)
    # (c) exit bar >= entry bar and fill prices consistent with exit-bar range / rule
    ok = True
    for t in trades_full:
        df = dfs[t["sym"]]
        i = t["exit_i"]
        if t["exit_i"] < t["ent"]:
            ok = False
        if t["why"] == "stop" and not (t["exit"] <= t["stop"] + 1e-9 and df["l"].iloc[i] <= t["stop"]):
            ok = False
        if t["why"] == "tp" and not (t["exit"] >= t["tp"] - 1e-9 and df["h"].iloc[i] >= t["tp"]
                                     and df["l"].iloc[i] > t["stop"]):
            ok = False
    out["exit_fills_consistent"] = ok
    # (d) stop-first: every bar where both stop and TP were touched closed as 'stop'
    out["ambiguous_bars_resolved_stop_first"] = all(t["why"] == "stop" for t in trades_full if t["ambiguous"])
    out["ambiguous_bar_count_full"] = int(sum(t["ambiguous"] for t in trades_full))
    # (e) no bar between entry and exit (exclusive) touched stop or TP (no missed exits)
    missed = 0
    for t in trades_full:
        df = dfs[t["sym"]]
        seg = df.iloc[t["ent"]:t["exit_i"]]
        missed += int(((seg["l"] <= t["stop"]) | (seg["h"] >= t["tp"])).sum())
    out["missed_exit_bars"] = missed
    # (f) EMA causality: EMA computed on truncated history equals full-history EMA at the same bar
    rng = np.random.default_rng(7)
    df = dfs["BTCUSDT"]
    errs = []
    for k in rng.integers(300, len(df) - 1, 15):
        tr = df["c"].iloc[:k + 1]
        errs.append(abs(tr.ewm(span=200, adjust=False).mean().iloc[-1] - df["ema200"].iloc[k]))
        errs.append(abs(tr.ewm(span=50, adjust=False).mean().iloc[-1] - df["ema50"].iloc[k]))
    out["ema_causal_max_abs_err"] = float(max(errs))
    # (g) future-perturbation: scramble prices after bar K; signals/trades fully decided by K must not change
    K = 12000
    d2 = df.copy()
    noise = rng.uniform(0.5, 1.5, len(d2) - K - 1)
    for col in ["o", "h", "l", "c"]:
        d2.loc[K + 1:, col] = d2.loc[K + 1:, col].values * noise
    d2["ema50"] = d2["c"].ewm(span=50, adjust=False).mean()
    d2["ema200"] = d2["c"].ewm(span=200, adjust=False).mean()
    valid = np.arange(len(d2)) >= (WARMUP - 1)
    d2["setup"] = valid & (d2["l"] <= d2["ema50"]) & (d2["c"] > d2["ema50"]) & (d2["c"] > d2["ema200"])
    out["perturb_signals_unchanged_upto_K"] = bool((d2["setup"].iloc[:K + 1] == df["setup"].iloc[:K + 1]).all())
    _, _, _, tA, _ = sim_sleeve(df, WARMUP - 1, len(df) - 1, COST, 100 / 3)
    _, _, _, tB, _ = sim_sleeve(d2, WARMUP - 1, len(d2) - 1, COST, 100 / 3)
    a = [(t["ent"], t["exit_i"], round(t["pnl"], 10)) for t in tA if t["exit_i"] <= K]
    b = [(t["ent"], t["exit_i"], round(t["pnl"], 10)) for t in tB if t["exit_i"] <= K]
    out["perturb_trades_unchanged_upto_K"] = (a == b) and len(a) > 0
    out["all_passed"] = bool(out["entry_is_next_bar"] and out["signal_close_before_entry_open"]
                             and out["stop_window_before_entry"] and out["exit_fills_consistent"]
                             and out["ambiguous_bars_resolved_stop_first"] and missed == 0
                             and out["ema_causal_max_abs_err"] < 1e-6 and out["perturb_signals_unchanged_upto_K"]
                             and out["perturb_trades_unchanged_upto_K"])
    return out


def verdict(oos, oos2x):
    ratio = oos["net_return_pct"] / abs(oos["max_dd_pct"]) if oos["max_dd_pct"] < 0 else float("inf")
    bratio = oos["bench_net_return_pct"] / abs(oos["bench_max_dd_pct"])
    worse_both = (oos["net_return_pct"] < oos["bench_net_return_pct"]) and (oos["max_dd_pct"] < oos["bench_max_dd_pct"])
    pf = oos["pf"] if oos["pf"] is not None else 0
    reasons = dict(oos_net=oos["net_return_pct"], oos_pf=pf, oos_trades=oos["trades"], ratio=ratio, bench_ratio=bratio,
                   worse_both=worse_both, net_2x=oos2x["net_return_pct"])
    if oos["net_return_pct"] <= 0 or pf < 1.0 or worse_both:
        return "FAIL", reasons
    if oos["trades"] < 30:
        return "INCONCLUSIVE", reasons
    if oos["net_return_pct"] > 0 and pf >= 1.2 and ratio > bratio and oos2x["net_return_pct"] > 0:
        return "PASS_CANDIDATE", reasons
    return "INCONCLUSIVE", reasons


def main():
    dfs, src = {}, []
    for s in SYMS:
        df, gaps, sha, n = load(s)
        dfs[s] = df
        src.append(dict(name=f"Binance spot {s} 4h klines (api.binance.com/api/v3/klines)",
                        url=f"https://api.binance.com/api/v3/klines?symbol={s}&interval=4h",
                        rows=n, start=str(df["open_time"].iloc[0]), end=str(df["close_time"].iloc[-1]),
                        sha256=sha, gaps_non4h=gaps, file=os.path.join(DATA, f"{s}_4h.json")))
    exi = os.path.join(DATA, "exchangeInfo.json")
    src.append(dict(name="Binance spot exchangeInfo (min notional / lot size)",
                    url="https://api.binance.com/api/v3/exchangeInfo", rows=None,
                    sha256=hashlib.sha256(open(exi, "rb").read()).hexdigest(), file=exi))
    start_all = min(dfs[s]["open_time"].iloc[0] for s in SYMS)
    end_all = pd.Timestamp(END_MS, unit="ms", tz="UTC")
    periods = {"IS": (start_all, IS_END), "OOS": (OOS_START, end_all), "FULL": (start_all, end_all)}
    res, res2 = {}, {}
    trades_by = {}
    for p, (a, b) in periods.items():
        res[p], trades_by[p], _, _ = run_period(dfs, a, b, COST)
        res2[p], _, _, _ = run_period(dfs, a, b, 2 * COST)
    checks = self_checks(dfs, trades_by["FULL"])
    v, why = verdict(res["OOS"], res2["OOS"])
    # $100 feasibility: simulation is scale-free, runs start at $100 total ($33.33 per sleeve)
    feas = {}
    for p in ["IS", "OOS", "FULL"]:
        tr = trades_by[p]
        feas[p] = dict(trades=len(tr),
                       below_min_notional=int(sum(t["notional"] < MIN_NOTIONAL for t in tr)),
                       median_notional_usd=float(np.median([t["notional"] for t in tr])) if tr else None,
                       median_risk_usd=float(np.median([t["eq_before"] * RISK for t in tr])) if tr else None)
    rows = []
    for p in ["IS", "OOS", "FULL"]:
        m = res[p]
        rows.append(dict(period=p, trades=m["trades"], win_rate_pct=m["win_rate_pct"], pf=m["pf"],
                         net_return_pct=m["net_return_pct"], cagr_pct=m["cagr_pct"], max_dd_pct=m["max_dd_pct"],
                         exposure_pct=m["exposure_time_pct"], bench_net_return_pct=m["bench_net_return_pct"],
                         bench_max_dd_pct=m["bench_max_dd_pct"], net_return_2x_cost_pct=res2[p]["net_return_pct"]))
    out = dict(id="C7", strategy="TREND_PULLBACK_4H", verdict=v, verdict_inputs=why, rows=rows,
               details=res, details_2x=res2, self_checks=checks, feasibility_100usd=feas, data_sources=src,
               conventions=dict(
                   warmup_bars=WARMUP, cost_per_side=COST, min_notional_usd=MIN_NOTIONAL,
                   period_runs="each period simulated independently from $100 (1/3 per sleeve); open position "
                               "force-closed at last close of the period; indicators use full prior history (causal)",
                   sol_sleeve="SOL sleeve holds cash until SOLUSDT has 200 bars (2020-09); benchmark SOL sleeve buys "
                              "at the same bar",
                   exposure="time-in-market averaged over the 3 sleeves; notional exposure in details",
                   max_dd="portfolio equity marked at 4h closes, sampled at daily (UTC) last mark"))
    json.dump(out, open(os.path.join(HERE, "result.json"), "w"), indent=2, default=str)
    pd.DataFrame(trades_by["FULL"]).to_csv(os.path.join(HERE, "trades_full.csv"), index=False)
    print(json.dumps(dict(rows=rows, verdict=v, why=why, checks=checks, feas=feas), indent=1, default=str))
    for p in res:
        print(p, {k: res[p][k] for k in ["start", "end", "exits", "per_asset", "avg_R_multiple",
                                         "median_notional_pct_of_sleeve", "share_notional_capped_pct",
                                         "exposure_notional_pct", "max_dd_4h_pct", "bench_cagr_pct", "ambiguous_bars"]})


if __name__ == "__main__":
    main()
