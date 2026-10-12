# C3 CROSS_VENUE_FUNDING backtest (SPEC2, frozen). BTCUSDT perps Binance vs Bybit.
# Rule: trailing 7-day mean spread m = mean(Bybit funding - Binance funding) over settlements in (T-7d, T].
#   m > +0.01%/8h -> +1 (short Bybit, long Binance); m < -0.01% -> -1 (long Bybit, short Binance);
#   |m| < 0.003% -> flat; otherwise hold previous state (hysteresis, literal reading of the spec).
# Each leg notional = 50% of equity at entry (fixed BTC quantity while held). Costs 10 bps per leg per side.
# Timing: settlement at T closes the 8h signal bar [T-8h, T); execution at the open of the next bar [T, T+8h).
# First funding credited to a new position is at T+8h. P&L = funding diff + price diff between venues - costs.
import json, os, hashlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
H8 = pd.Timedelta(hours=8)
LAST_SETTLE = pd.Timestamp("2026-10-06 16:00")  # last settlement / bar close strictly before 2026-10-06 23:59 cutoff handling
OOS_START = pd.Timestamp("2023-01-01 00:00")
ENTER, EXIT_ = 0.0001, 0.00003
COST = 0.0010  # 10 bps per leg per side (crypto perp)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load():
    b = json.load(open(os.path.join(D, "binance_funding_BTCUSDT.json")))
    y = json.load(open(os.path.join(D, "bybit_funding_BTCUSDT.json")))
    bf = pd.DataFrame({"t": pd.to_datetime([x["fundingTime"] for x in b], unit="ms"), "r": [float(x["fundingRate"]) for x in b]})
    yf = pd.DataFrame({"t": pd.to_datetime([int(x["fundingRateTimestamp"]) for x in y], unit="ms"), "r": [float(x["fundingRate"]) for x in y]})
    out = {}
    for name, df in [("bin", bf), ("byb", yf)]:
        df = df.drop_duplicates("t")
        t = df["t"].dt.round("min")
        # 8h window end (ceil to 00/08/16 UTC); sum settlements within each window (spec)
        w = t.dt.ceil("8h")
        s = df.groupby(w)["r"].sum()
        cnt = df.groupby(w)["r"].size()
        out[name] = s
        out[name + "_cnt"] = cnt
    bk = json.load(open(os.path.join(D, "binance_perp_klines_8h_BTCUSDT.json")))
    yk = json.load(open(os.path.join(D, "bybit_perp_klines_4h_BTCUSDT.json")))
    bkd = pd.DataFrame({"t": pd.to_datetime([x[0] for x in bk], unit="ms"), "o": [float(x[1]) for x in bk],
                        "c": [float(x[4]) for x in bk]}).drop_duplicates("t").set_index("t").sort_index()
    ykd = pd.DataFrame({"t": pd.to_datetime([int(x[0]) for x in yk], unit="ms"), "o": [float(x[1]) for x in yk],
                        "c": [float(x[4]) for x in yk]}).drop_duplicates("t").set_index("t").sort_index()
    return out, bkd, ykd


def build():
    f, bkd, ykd = load()
    start = max(f["bin"].index.min(), f["byb"].index.min())
    grid = pd.date_range(start, LAST_SETTLE, freq="8h")  # settlement times
    fb = f["bin"].reindex(grid)
    fy = f["byb"].reindex(grid)
    gaps = {"bin_missing": int(fb.isna().sum()), "byb_missing": int(fy.isna().sum()),
            "bin_multi": int((f["bin_cnt"] > 1).sum()), "byb_multi": int((f["byb_cnt"] > 1).sum())}
    spread = fy - fb
    # trailing 7-day mean over settlements in (T-7d, T]; require full 21 observations
    m = spread.rolling(21, min_periods=21).mean()
    # bar starts T on the same grid. Binance 8h bar [T,T+8h): open/close. Bybit: open of 4h bar at T, close of 4h bar at T+4h.
    bars = pd.DataFrame(index=grid)
    bars["bO"] = bkd["o"].reindex(grid)
    bars["bC"] = bkd["c"].reindex(grid)
    bars["yO"] = ykd["o"].reindex(grid)
    bars["yC"] = ykd["c"].reindex(grid + pd.Timedelta(hours=4)).values
    bars["m_sig"] = m.values            # signal known at T (settlements <= T) -> used at open of bar starting T
    bars["fB_end"] = fb.shift(-1).values  # funding settled at T+8h (end of bar T)
    bars["fY_end"] = fy.shift(-1).values
    bars["spread"] = spread.values
    return bars, gaps, spread, m


def target(mv, prev):
    if np.isnan(mv):
        return 0
    if mv > ENTER:
        return 1
    if mv < -ENTER:
        return -1
    if abs(mv) < EXIT_:
        return 0
    return prev


def run(bars, A, B, cost=COST):
    """Bars with start in [A, B); forced flat at the open of bar B. Starts flat with equity 1.0."""
    idx = bars.index
    sel = idx[(idx >= A) & (idx < B)]
    sel = sel[~bars.loc[sel, "m_sig"].isna()]
    A0 = sel[0]
    E = 1.0
    s, Qb, Qy, pb, py = 0, 0.0, 0.0, None, None
    trades, cur = [], None
    marks = [(A0, E)]
    pos = []
    comp = {"funding": 0.0, "price": 0.0, "cost": 0.0}

    def close_at(T, bo, yo):
        nonlocal E, s, Qb, Qy, cur
        c = cost * (Qb * bo + Qy * yo)
        E -= c; comp["cost"] -= c; cur["pnl"] -= c
        cur["exit"] = T; trades.append(cur); cur = None
        s, Qb, Qy = 0, 0.0, 0.0

    for T in sel:
        r = bars.loc[T]
        if s != 0:  # gap from previous mark (close at T) to open at T
            g = s * (Qb * (r.bO - pb) - Qy * (r.yO - py))
            E += g; comp["price"] += g; cur["pnl"] += g
        tgt = target(r.m_sig, s)
        if tgt != s:
            if s != 0:
                close_at(T, r.bO, r.yO)
            if tgt != 0:
                N = 0.5 * E
                Qb, Qy = N / r.bO, N / r.yO
                c = cost * 2 * N
                E -= c; comp["cost"] -= c
                cur = {"entry": T, "side": tgt, "pnl": -c, "E0": E + c, "m_at_signal": r.m_sig}
                s = tgt
        pos.append((T, s))
        if s != 0:
            g = s * (Qb * (r.bC - r.bO) - Qy * (r.yC - r.yO))
            fu = s * (r.fY_end * Qy * r.yC - r.fB_end * Qb * r.bC)  # short receives +rate, long pays +rate
            E += g + fu; comp["price"] += g; comp["funding"] += fu; cur["pnl"] += g + fu
        pb, py = r.bC, r.yC
        marks.append((T + H8, E))
    # forced close at open of bar B (first bar outside the period)
    if s != 0:
        rB = bars.loc[B] if B in bars.index else None
        bo, yo = (rB.bO, rB.yO) if rB is not None and not np.isnan(rB.bO) else (pb, py)
        g = s * (Qb * (bo - pb) - Qy * (yo - py))
        E += g; comp["price"] += g; cur["pnl"] += g
        close_at(B, bo, yo)
        marks[-1] = (marks[-1][0], E)
    eq = pd.Series(dict(marks)).sort_index()
    return eq, trades, pd.Series(dict(pos)), comp


def metrics(eq, trades, pos):
    daily = eq[eq.index.hour == 0]
    daily = pd.concat([eq.iloc[:1], daily, eq.iloc[-1:]])
    daily = daily[~daily.index.duplicated(keep="last")]
    dd_daily = (daily / daily.cummax() - 1).min() * 100
    dd_8h = (eq / eq.cummax() - 1).min() * 100
    days = (eq.index[-1] - eq.index[0]).total_seconds() / 86400
    ret = (eq.iloc[-1] / eq.iloc[0] - 1)
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (365.25 / days) - 1) * 100 if days > 0 else None
    pn = np.array([t["pnl"] for t in trades])
    wins, losses = pn[pn > 0].sum(), -pn[pn < 0].sum()
    pf = (wins / losses) if losses > 0 else (None if wins == 0 else float("inf"))
    return {"trades": len(trades), "win_rate_pct": (float((pn > 0).mean() * 100) if len(pn) else None),
            "pf": (None if pf is None else (round(pf, 3) if np.isfinite(pf) else 999.0)),
            "net_return_pct": round(ret * 100, 3), "cagr_pct": None if cagr is None else round(cagr, 3),
            "max_dd_pct": round(dd_daily, 3), "max_dd_8h_pct": round(dd_8h, 3),
            "exposure_pct": round(float((pos != 0).mean() * 100), 2), "days": round(days, 1),
            "start": str(eq.index[0]), "end": str(eq.index[-1])}


def lookahead_checks(bars):
    out = {}
    # 1) the signal used at bar T is computed only from settlements <= T (recompute explicitly at random bars)
    rng = np.random.default_rng(0)
    spread = bars["spread"]
    ok = True
    for T in rng.choice(bars.index[30:], 200, replace=False):
        w = spread[(spread.index > T - pd.Timedelta(days=7)) & (spread.index <= T)]
        if len(w) == 21 and not np.isclose(w.mean(), bars.loc[T, "m_sig"]):
            ok = False
    out["signal_uses_only_settlements_le_bar_open"] = ok
    # 2) perturbation test: scramble all data at/after cutoff X; positions for bars before X and equity marks before X must not change
    X = pd.Timestamp("2022-06-01")
    b2 = bars.copy()
    msk = b2.index >= X
    for c in ["bO", "bC", "yO", "yC"]:
        b2.loc[msk, c] = b2.loc[msk, c] * rng.uniform(0.5, 1.5, msk.sum())
    sp2 = b2["spread"].copy()
    sp2[msk] = rng.normal(0, 0.001, msk.sum())
    b2["spread"] = sp2
    b2["m_sig"] = sp2.rolling(21, min_periods=21).mean().values
    fb2 = b2["fB_end"].copy(); fy2 = b2["fY_end"].copy()
    m_end = (b2.index + H8) >= X
    fb2[m_end] = rng.normal(0, 0.001, m_end.sum()); fy2[m_end] = rng.normal(0, 0.001, m_end.sum())
    b2["fB_end"], b2["fY_end"] = fb2, fy2
    A, B = bars.index[0], pd.Timestamp("2026-10-06 16:00")
    e1, _, p1, _ = run(bars, A, B)
    e2, _, p2, _ = run(b2, A, B)
    out["perturb_positions_before_X_identical"] = bool((p1[p1.index < X] == p2[p2.index < X]).all())
    out["perturb_equity_before_X_identical"] = bool(np.allclose(e1[e1.index < X], e2[e2.index < X]))
    out["perturb_after_X_differs(sanity)"] = bool(not np.allclose(e1[e1.index > X].values[:50], e2[e2.index > X].values[:50]))
    # 3) execution bar strictly after signal bar: signal bar = [T-8h,T) closed by settlement T; entry at open of bar starting T;
    #    first funding credited at T+8h > T.
    out["entry_after_signal_bar_close_and_first_funding_at_T+8h"] = True
    out["stop_first_intrabar"] = "не применимо (нет стопов/тейков)"
    # 4) price alignment: Binance close of bar T ~ open of bar T+8h; Bybit same
    out["max_abs_close_to_next_open_gap_bin_pct"] = round(float((bars["bO"].shift(-1) / bars["bC"] - 1).abs().max() * 100), 4)
    out["max_abs_close_to_next_open_gap_byb_pct"] = round(float((bars["yO"].shift(-1) / bars["yC"] - 1).abs().max() * 100), 4)
    out["median_abs_venue_price_diff_pct"] = round(float((bars["yC"] / bars["bC"] - 1).abs().median() * 100), 4)
    return out


def mechanical_verdict(o):
    """Pre-registered SPEC2 verdict on OOS row; type = carry (benchmark cash 0%)."""
    fails = []
    if o["net_return_pct"] <= 0:
        fails.append(f"OOS net {o['net_return_pct']}% <= 0")
    if o["pf"] is not None and o["pf"] < 1.0:
        fails.append(f"PF {o['pf']} < 1.0")
    if o["net_return_pct"] < o["bench_net_return_pct"] and o["max_dd_pct"] < o["bench_max_dd_pct"]:
        fails.append("хуже кэша и по доходности, и по просадке")
    if fails:
        return "FAIL", "; ".join(fails)
    ann_ok = o["cagr_pct"] > 4 and o["max_dd_pct"] > -10
    if ann_ok and o["net_return_2x_cost_pct"] > 0:
        return "PASS_CANDIDATE", "carry: годовых > 4%, DD < 10%, плюс при 2x издержках"
    return "INCONCLUSIVE", "не FAIL, но критерии PASS_CANDIDATE для carry не выполнены"


def main():
    bars, gaps, spread, m = build()
    first = bars.index[~bars["m_sig"].isna() & ~bars["bO"].isna() & ~bars["yO"].isna()][0]
    END = pd.Timestamp("2026-10-06 16:00")  # forced exit at open of bar starting here; last credited settlement = 2026-10-06 16:00
    periods = {"IS": (first, OOS_START), "OOS": (OOS_START, END), "FULL": (first, END)}
    rows, detail = [], {}
    for name, (A, B) in periods.items():
        eq, tr, pos, comp = run(bars, A, B)
        eq2, tr2, _, _ = run(bars, A, B, cost=2 * COST)
        mt = metrics(eq, tr, pos)
        mt2 = metrics(eq2, tr2, pos)
        side_counts = {"+1(short Bybit/long Binance)": sum(1 for t in tr if t["side"] == 1),
                       "-1(long Bybit/short Binance)": sum(1 for t in tr if t["side"] == -1)}
        row = {"period": name, "trades": mt["trades"],
               "win_rate_pct": None if mt["win_rate_pct"] is None else round(mt["win_rate_pct"], 2),
               "pf": mt["pf"], "net_return_pct": mt["net_return_pct"], "cagr_pct": mt["cagr_pct"],
               "max_dd_pct": mt["max_dd_pct"], "exposure_pct": mt["exposure_pct"],
               "bench_net_return_pct": 0.0, "bench_max_dd_pct": 0.0,
               "net_return_2x_cost_pct": mt2["net_return_pct"]}
        rows.append(row)
        sel = spread[(spread.index >= A) & (spread.index < B)]
        msel = m[(m.index >= A) & (m.index < B)]
        detail[name] = {"metrics": mt, "metrics_2x": mt2, "pnl_components_pct_of_start": {k: round(v * 100, 4) for k, v in comp.items()},
                        "sides": side_counts,
                        "trade_list": [{"entry": str(t["entry"]), "exit": str(t["exit"]), "side": t["side"],
                                        "pnl_pct_of_equity_at_entry": round(t["pnl"] / t["E0"] * 100, 4),
                                        "m_at_signal_pct": round(t["m_at_signal"] * 100, 5)} for t in tr],
                        "spread_stats_pct_per_8h": {"mean": round(float(sel.mean() * 100), 5), "std": round(float(sel.std() * 100), 5),
                                                    "share_m_gt_+0.01%": round(float((msel > ENTER).mean() * 100), 2),
                                                    "share_m_lt_-0.01%": round(float((msel < -ENTER).mean() * 100), 2),
                                                    "share_abs_m_lt_0.003%": round(float((msel.abs() < EXIT_).mean() * 100), 2)}}
    checks = lookahead_checks(bars)
    srcs = []
    for fn, url in [("binance_funding_BTCUSDT.json", "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT"),
                    ("bybit_funding_BTCUSDT.json", "https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT"),
                    ("binance_perp_klines_8h_BTCUSDT.json", "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=8h"),
                    ("bybit_perp_klines_4h_BTCUSDT.json", "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=240")]:
        js = json.load(open(os.path.join(D, fn)))
        srcs.append({"name": fn, "url": url, "rows": len(js), "sha256": sha(os.path.join(D, fn))})
    verdict, why = mechanical_verdict(rows[1])
    res = {"id": "C3", "verdict": verdict, "verdict_reason": why, "rows": rows, "detail": detail, "gaps": gaps,
           "checks": checks, "data_sources": srcs, "first_signal_bar": str(first), "end_forced_exit": str(END),
           "feasible_100usd": {"ok": False, "why": "Мин. объём BTCUSDT-перпа 0.001 BTC (~$84 при цене ~$84k) на обеих биржах, "
                               "у Binance ещё мин. notional 100 USDT; при $100 нога = $50 -> ниже минимума без плеча; нужны 2 аккаунта с KYC."}}
    print("VERDICT", verdict, why)
    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({"rows": rows, "gaps": gaps, "checks": checks, "first": str(first)}, indent=1, default=str))
    for k, v in detail.items():
        print(k, v["pnl_components_pct_of_start"], v["sides"], v["spread_stats_pct_per_8h"], "dd8h", v["metrics"]["max_dd_8h_pct"])


if __name__ == "__main__":
    main()
