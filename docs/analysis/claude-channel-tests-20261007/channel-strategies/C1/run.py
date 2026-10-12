# C1 FUNDING_CARRY backtest (SPEC2, frozen 2026-10-07). Data: data/*.json from download.py (public Binance endpoints).
# Rule per asset (BTC, ETH; each 50% of capital): long spot + short USDT-M perp, equal notional = 50% of sleeve equity
# (other 50% of sleeve = perp margin). Enter when trailing 3-day (9 settlements) mean funding > 0.01%/8h; exit when < 0.
# Signals on closed 8h bars, execution at next 8h bar open. Funding settled at time s is credited to a position iff
# entry_time < s <= exit_time (entry/exit happen at bar open, just after the settlement stamped at that open).
# Costs per side: spot 20 bps, perp 10 bps (x2 in stress). Benchmark: cash 0%.
import json, os, hashlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ASSETS = ["BTCUSDT", "ETHUSDT"]
ENTER_TH, EXIT_TH, WIN = 0.0001, 0.0, 9          # 0.01% per 8h; 0; 3 days = 9 settlements
C_SPOT, C_PERP = 0.0020, 0.0010
CAP0 = 100.0
H8 = pd.Timedelta(hours=8)
LAST_CLOSE = pd.Timestamp("2026-10-07 00:00", tz="UTC")   # last bar closes 2026-10-06 23:59:59.999
IS_END = pd.Timestamp("2023-01-01 00:00", tz="UTC")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load_asset(sym):
    def kl(fn):
        k = pd.DataFrame(json.load(open(os.path.join(DATA, fn))))
        df = pd.DataFrame({"open": k[1].astype(float).values, "close": k[4].astype(float).values,
                           "high": k[2].astype(float).values},
                          index=pd.DatetimeIndex(pd.to_datetime(k[0], unit="ms", utc=True), name="t"))
        assert df.notna().all().all()
        assert (pd.to_datetime(k[6], unit="ms", utc=True) < LAST_CLOSE).all()
        return df
    spot = kl(f"spot_klines_8h_{sym}.json")
    perp = kl(f"perp_klines_8h_{sym}.json")
    f = pd.DataFrame(json.load(open(os.path.join(DATA, f"funding_{sym}.json"))))
    ft = pd.to_datetime(f["fundingTime"], unit="ms", utc=True).dt.round("h")
    fund = pd.Series(f["fundingRate"].astype(float).values, index=ft).sort_index()
    fund = fund[fund.index < LAST_CLOSE]                 # settlements at or before 2026-10-06 16:00
    idx = perp.index.intersection(spot.index)
    df = pd.DataFrame(index=idx)
    df["s_open"], df["s_close"] = spot.loc[idx, "open"], spot.loc[idx, "close"]
    df["p_open"], df["p_close"], df["p_high"] = perp.loc[idx, "open"], perp.loc[idx, "close"], perp.loc[idx, "high"]
    df["s_high"] = spot.loc[idx, "high"]
    assert df.notna().all().all()
    # funding settled at the CLOSE of bar i (time T_i + 8h); NaN if none
    df["fund_close"] = fund.reindex(df.index + H8).values
    df["fund_close_time"] = df.index + H8
    # trailing 3-day mean using only settlements with time <= close of bar i
    df["sig_mean"] = df["fund_close"].rolling(WIN, min_periods=WIN).mean()
    return df, fund


def simulate(df, a_time, b_time, cost_mult=1.0, cap=50.0):
    """Sleeve sim on bars with open time in [a_time, b_time]. Returns equity at each bar close, trades, in_pos flags."""
    cs, cp = C_SPOT * cost_mult, C_PERP * cost_mult
    bars = df[(df.index >= a_time) & (df.index <= b_time)]
    T = bars.index
    pos = False
    E = cap                 # realised sleeve equity when flat / base when in position
    base = qs = qp = se = pe = cumf = 0.0
    trades, eq, inpos = [], [], []
    entry = None
    full_idx = {t: k for k, t in enumerate(df.index)}
    for i, t in enumerate(T):
        gi = full_idx[t]
        # (a) funding stamped at this bar's open T_i (= close of previous bar) credited to a position held into T_i
        if pos and gi >= 1:
            fr = df["fund_close"].iat[gi - 1]
            if not np.isnan(fr):
                st = df["fund_close_time"].iat[gi - 1]
                assert entry["time"] < st <= t
                amt = fr * qp * df["p_close"].iat[gi - 1]       # short perp receives rate * notional
                cumf += amt
                entry["fund_n"] += 1
                entry["fund_times"].append(st)
        # (b) decision from signal at close of previous bar (gi-1), executed at open of this bar
        if gi >= 1:
            m = df["sig_mean"].iat[gi - 1]
            want = pos
            if not pos and not np.isnan(m) and m > ENTER_TH:
                want = True
            elif pos and not np.isnan(m) and m < EXIT_TH:
                want = False
            if want != pos:
                so, po = df["s_open"].iat[gi], df["p_open"].iat[gi]
                if want:
                    N = 0.5 * E
                    qs, qp, se, pe = N / so, N / po, so, po
                    cost = N * (cs + cp)
                    base, cumf = E - cost, 0.0
                    entry = {"sig_bar": df.index[gi - 1], "sig_bar_close": df.index[gi - 1] + H8, "time": t,
                             "eq_before": E, "cost": cost, "fund_n": 0, "fund_times": [], "notional": N,
                             "max_rise": 0.0}
                    pos = True
                else:
                    cost = qs * so * cs + qp * po * cp
                    pricepnl = qs * (so - se) - qp * (po - pe)
                    E_new = base + pricepnl + cumf - cost
                    entry.update({"exit_sig_bar": df.index[gi - 1], "exit_time": t, "eq_after": E_new,
                                  "funding": cumf, "price_pnl": pricepnl, "cost": entry["cost"] + cost,
                                  "pnl": E_new - entry["eq_before"], "forced": False})
                    trades.append(entry)
                    E, pos, entry = E_new, False, None
        inpos.append(pos)
        # (c) mark at bar close
        if pos:
            entry["max_rise"] = max(entry["max_rise"], df["p_high"].iat[gi] / pe - 1)
            eq.append(base + qs * (df["s_close"].iat[gi] - se) - qp * (df["p_close"].iat[gi] - pe) + cumf)
        else:
            eq.append(E)
    # forced close at last bar close of window (no funding at the next stamp)
    if pos:
        gi = full_idx[T[-1]]
        sc, pc = df["s_close"].iat[gi], df["p_close"].iat[gi]
        cost = qs * sc * cs + qp * pc * cp
        pricepnl = qs * (sc - se) - qp * (pc - pe)
        E_new = base + pricepnl + cumf - cost
        entry.update({"exit_sig_bar": T[-1], "exit_time": T[-1] + H8, "eq_after": E_new, "funding": cumf,
                      "price_pnl": pricepnl, "cost": entry["cost"] + cost, "pnl": E_new - entry["eq_before"],
                      "forced": True})
        trades.append(entry)
        E = E_new
        eq[-1] = E
    eqs = pd.Series(eq, index=T + H8)    # equity at bar close times
    return eqs, trades, pd.Series(inpos, index=T), E


def metrics(eq_total, trades, inpos_list, start_cap, start_time):
    end_cap = eq_total.iloc[-1]
    years = (eq_total.index[-1] - start_time).total_seconds() / (365.25 * 86400)
    # daily marks: equity at the last 8h close of each UTC day (closes at 00:00 belong to previous day)
    daily = eq_total.groupby((eq_total.index - pd.Timedelta(milliseconds=1)).floor("D")).last()
    daily = pd.concat([pd.Series([start_cap], index=[start_time - pd.Timedelta(days=1)]), daily])
    dd = (daily / daily.cummax() - 1).min() * 100
    pnl = np.array([t["pnl"] for t in trades])
    gw, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = float(gw / gl) if gl > 0 else (None if gw == 0 else float("inf"))
    expo = float(np.mean([s.mean() for s in inpos_list]) * 100)
    ret = (end_cap / start_cap - 1) * 100
    cagr = ((end_cap / start_cap) ** (1 / years) - 1) * 100 if years > 0 else None
    return {"trades": int(len(pnl)), "win_rate_pct": float((pnl > 0).mean() * 100) if len(pnl) else None,
            "pf": pf, "net_return_pct": float(ret), "cagr_pct": float(cagr), "max_dd_pct": float(dd),
            "exposure_pct": expo, "years": years}


def run_window(data, a_time, b_time, cost_mult=1.0):
    eqs, trs, ips, sleeves = [], [], [], {}
    for sym in ASSETS:
        e, t, ip, E = simulate(data[sym][0], a_time, b_time, cost_mult, cap=CAP0 / 2)
        eqs.append(e); trs += t; ips.append(ip)
        sleeves[sym] = {"end": E, "trades": t, "eq": e}
    eq_total = sum(eqs)
    # reconciliation: sum of trade pnl == equity change
    tot_pnl = sum(t["pnl"] for t in trs)
    assert abs((eq_total.iloc[-1] - CAP0) - tot_pnl) < 1e-6, "equity/trade P&L mismatch"
    m = metrics(eq_total, trs, ips, CAP0, a_time)
    return m, sleeves, eq_total, trs


def main():
    data = {s: load_asset(s) for s in ASSETS}
    # common start: first bar where both perps exist (ETH perp listing 2019-11-27)
    start = max(d[0].index[0] for d in data.values())
    last_bar = min(d[0].index[-1] for d in data.values())
    assert last_bar + H8 == LAST_CLOSE
    windows = {"IS": (start, IS_END - H8), "OOS": (IS_END, last_bar), "FULL": (start, last_bar)}

    # ---------- look-ahead self-checks ----------
    checks = {}
    # 1) signal uses only settlements stamped <= signal bar close; truncation test: recompute signals on data truncated
    #    at 2024-06-30 and compare with full-data signals on overlapping bars
    for sym in ASSETS:
        df, fund = data[sym]
        cut = pd.Timestamp("2024-06-30", tz="UTC")
        f_tr = fund[fund.index <= cut]
        sig_tr = pd.Series(f_tr.reindex(df.index + H8).values, index=df.index).rolling(WIN, min_periods=WIN).mean()
        ov = df.index[df.index + H8 <= cut]
        checks[f"{sym}_truncation_signal_identical"] = bool(np.allclose(sig_tr.loc[ov].fillna(-9), df["sig_mean"].loc[ov].fillna(-9)))
        checks[f"{sym}_funding_stamp_eq_bar_close"] = bool((df["fund_close_time"] == df.index + H8).all())
        # strict '>' vs ties at exactly 0.01%: float rolling mean must agree with exact integer (1e-8 units) sums
        ex = (df["fund_close"] * 1e8).round().rolling(WIN, min_periods=WIN).sum()
        checks[f"{sym}_float_vs_exact_threshold_agree"] = bool(((df["sig_mean"] > ENTER_TH) == (ex > WIN * 1e4)).all()
                                                               and ((df["sig_mean"] < EXIT_TH) == (ex < 0)).all())
        checks[f"{sym}_bars_with_mean_exactly_0.01pct"] = int((ex == WIN * 1e4).sum())
    res, extra = {}, {}
    for lab, (a, b) in windows.items():
        m, sleeves, eq_total, trs = run_window(data, a, b, 1.0)
        m2, _, _, _ = run_window(data, a, b, 2.0)
        # 2) execution strictly after signal bar; funding credited only after entry and up to exit
        for t in trs:
            assert t["sig_bar"] < t["time"] and t["sig_bar_close"] <= t["time"]
            assert t["exit_sig_bar"] < t["exit_time"] or t["forced"]
            assert all(t["time"] < s <= t["exit_time"] for s in t["fund_times"])
        m["net_return_2x_cost_pct"] = m2["net_return_pct"]
        m["cagr_2x_cost_pct"] = m2["cagr_pct"]
        m["start"], m["end"] = str(a), str(b + H8)
        per = {}
        for sym in ASSETS:
            st = sleeves[sym]["trades"]
            per[sym] = {"sleeve_return_pct": (sleeves[sym]["end"] / (CAP0 / 2) - 1) * 100,
                        "trades": len(st),
                        "funding_usd": sum(x["funding"] for x in st),
                        "basis_usd": sum(x["price_pnl"] for x in st),
                        "costs_usd": sum(x["cost"] for x in st),
                        "max_perp_rise_in_trade_pct": max([x["max_rise"] for x in st] or [0]) * 100,
                        "avg_hold_days": float(np.mean([(x["exit_time"] - x["time"]).total_seconds() / 86400 for x in st])) if st else None}
        m["per_asset"] = per
        # diagnostics (not variants): DD on 8h marks; trades whose perp rose >= 90% (1x-margined short would be
        # liquidated without moving collateral from the spot leg)
        e8 = pd.concat([pd.Series([CAP0], index=[a]), eq_total])
        m["max_dd_8h_marks_pct"] = float((e8 / e8.cummax() - 1).min() * 100)
        m["trades_perp_rise_ge_90pct"] = int(sum(1 for x in trs if x["max_rise"] >= 0.9))
        if lab == "FULL":
            ye = pd.concat([pd.Series([CAP0], index=[a]), eq_total])
            yl = ye.groupby((ye.index - pd.Timedelta(milliseconds=1)).year).last()
            prev = pd.Series([CAP0] + list(yl.values[:-1]), index=yl.index)
            m["calendar_year_return_pct"] = {int(y): float((yl[y] / prev[y] - 1) * 100) for y in yl.index}
        res[lab] = m
        extra[lab] = trs
    checks["all_trades_signal_bar_before_execution_bar"] = True
    checks["funding_only_within_(entry,exit]"] = True
    checks["equity_reconciles_with_trade_pnl"] = True

    # ---------- pre-registered verdict (carry type), applied mechanically on OOS ----------
    o = res["OOS"]
    bench_ret, bench_dd = 0.0, 0.0      # cash 0%
    fail = (o["net_return_pct"] <= 0) or (o["pf"] is not None and o["pf"] < 1.0) or            (o["net_return_pct"] < bench_ret and o["max_dd_pct"] < bench_dd)
    pass_c = (o["net_return_pct"] > 0 and o["cagr_pct"] > 4.0 and o["max_dd_pct"] > -10.0
              and o["net_return_2x_cost_pct"] > 0)   # return/maxDD vs cash: cash ratio 0 -> any positive ratio beats
    verdict = "FAIL" if fail else ("PASS_CANDIDATE" if pass_c else "INCONCLUSIVE")
    for lab in res:
        if res[lab]["pf"] == float("inf"):
            res[lab]["pf"] = None
            res[lab]["pf_note"] = "no losing trades (PF infinite)"

    out = {"strategy": "C1 FUNDING_CARRY", "params": {"enter_mean_gt": ENTER_TH, "exit_mean_lt": EXIT_TH,
           "window_settlements": WIN, "cost_spot_side": C_SPOT, "cost_perp_side": C_PERP, "notional_frac_of_sleeve": 0.5},
           "data_start_common": str(start), "results": res, "self_checks": checks,
           "verdict": verdict, "verdict_inputs": {"oos_net": o["net_return_pct"], "oos_cagr": o["cagr_pct"],
           "oos_maxdd": o["max_dd_pct"], "oos_2x": o["net_return_2x_cost_pct"], "fail": fail, "pass": pass_c},
           "data_sha256": {fn: sha(os.path.join(DATA, fn)) for fn in sorted(os.listdir(DATA))}}
    # trades list (FULL) for audit
    out["trades_full"] = [{"asset": None, "entry": str(t["time"]), "exit": str(t["exit_time"]), "pnl": t["pnl"],
                           "funding": t["funding"], "basis": t["price_pnl"], "cost": t["cost"], "forced": t["forced"],
                           "max_rise_pct": t["max_rise"] * 100} for t in extra["FULL"]]
    # recompute per-asset labels for FULL trades
    k = 0
    for sym in ASSETS:
        _, trs_s, _, _ = simulate(data[sym][0], *windows["FULL"], 1.0, CAP0 / 2)
        for _ in trs_s:
            out["trades_full"][k]["asset"] = sym; k += 1
    with open(os.path.join(HERE, "result.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    for lab in ["IS", "OOS", "FULL"]:
        r = res[lab]
        print(lab, {k2: (round(v, 3) if isinstance(v, float) else v) for k2, v in r.items() if k2 != "per_asset"})
        for sym in ASSETS:
            print("   ", sym, {k2: (round(v, 3) if isinstance(v, float) else v) for k2, v in r["per_asset"][sym].items()})
    print("checks", checks)
    print("verdict", verdict, out["verdict_inputs"])


if __name__ == "__main__":
    main()
