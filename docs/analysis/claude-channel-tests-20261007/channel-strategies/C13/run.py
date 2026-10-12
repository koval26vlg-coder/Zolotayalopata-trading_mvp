# C13 GOLD_MACD_TREND — frozen rule from SPEC2.md (2026-10-07)
# Long when MACD(12,26,9) line > signal AND close > EMA220; else flat.
# Daily evaluation on closed bar t, execution at open of bar t+1. Cost 5 bps per side (gold). Stress 2x.
# Benchmark: gold buy&hold over the same period. Type: trade.
import json, hashlib, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "GC_F_1d_period.json")      # Yahoo chart API GC=F interval=1d (period1/period2)
RAW_MAX = os.path.join(DATA, "GC_F_max_1d.json")     # range=max attempt -> Yahoo returned 1mo granularity (unused)
LAST_DATE = pd.Timestamp("2026-10-06")
IS_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")
COST = 0.0005  # 5 bps per side
N_FAST, N_SLOW, N_SIG, N_TREND = 12, 26, 9, 220


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load():
    d = json.load(open(RAW))
    r = d["chart"]["result"][0]
    assert r["meta"].get("dataGranularity") == "1d", "expected daily granularity"
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": r["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"]})
    # timestamps are 04:00/05:00 UTC (NY midnight) or 13:30/14:30 UTC (half days) -> UTC date == trading date
    df["date"] = pd.to_datetime(df.ts, unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    n_raw = len(df)
    df = df.dropna(subset=["o", "c"]).copy()
    df = df[df.date <= LAST_DATE].reset_index(drop=True)  # drop in-progress 2026-10-07 bar
    assert not df.date.duplicated().any()
    assert df.date.is_monotonic_increasing
    return df, n_raw


def ema_sma_seed(x, n):
    """EMA seeded with SMA of the first n valid values (TradingView-style); NaN before."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    valid = np.where(~np.isnan(x))[0]
    if len(valid) < n:
        return out
    start = valid[0]
    seed_idx = start + n - 1
    out[seed_idx] = np.mean(x[start:seed_idx + 1])
    a = 2.0 / (n + 1)
    for i in range(seed_idx + 1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def signals(close):
    close = np.asarray(close, dtype=float)
    macd = ema_sma_seed(close, N_FAST) - ema_sma_seed(close, N_SLOW)
    sig = ema_sma_seed(macd, N_SIG)
    ema_t = ema_sma_seed(close, N_TREND)
    valid = ~np.isnan(macd) & ~np.isnan(sig) & ~np.isnan(ema_t)
    long_sig = valid & (macd > sig) & (close > ema_t)
    return long_sig, valid, macd, sig, ema_t


def simulate(df, long_sig, i0, i1, cost):
    """Run from bar i0 to i1 inclusive. Position during bar i is decided by long_sig[i-1] (closed bar),
    executed at open[i]. Start flat in cash (0%). Open trade at i1 is closed at close[i1] (forced, cost applied)."""
    o, c = df.o.values, df.c.values
    e = 1.0
    in_pos = False
    marks, held = [], []
    trades = []
    cur = None
    for i in range(i0, i1 + 1):
        want = bool(long_sig[i - 1])          # signal from CLOSED bar i-1
        if want and not in_pos:
            e_before = e
            e *= (1 - cost)
            e *= c[i] / o[i]
            in_pos = True
            cur = dict(sig_i=i - 1, entry_i=i, entry_date=str(df.date[i].date()), entry_px=float(o[i]), e_before=e_before)
        elif (not want) and in_pos:
            e *= o[i] / c[i - 1]
            e *= (1 - cost)
            in_pos = False
            cur.update(exit_sig_i=i - 1, exit_i=i, exit_date=str(df.date[i].date()), exit_px=float(o[i]),
                       e_after=e, forced=False)
            trades.append(cur); cur = None
        elif want and in_pos:
            e *= c[i] / c[i - 1]
        marks.append(e)
        held.append(in_pos)
    if in_pos:
        e *= (1 - cost)
        marks[-1] = e
        cur.update(exit_sig_i=None, exit_i=i1, exit_date=str(df.date[i1].date()), exit_px=float(c[i1]),
                   e_after=e, forced=True)
        trades.append(cur)
    return np.array(marks), np.array(held), trades


def bench(df, i0, i1, cost):
    o, c = df.o.values, df.c.values
    e = (1 - cost) * c[i0] / o[i0]
    marks = [e]
    for i in range(i0 + 1, i1 + 1):
        e *= c[i] / c[i - 1]
        marks.append(e)
    e *= (1 - cost)
    marks[-1] = e
    return np.array(marks)


def max_dd(marks):
    eq = np.concatenate([[1.0], marks])
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min() * 100)


def metrics(df, i0, i1, marks, held, trades):
    days = (df.date[i1] - df.date[i0]).days
    yrs = days / 365.25
    final = marks[-1]
    pnl = np.array([t["e_after"] - t["e_before"] for t in trades])
    rets = np.array([t["e_after"] / t["e_before"] - 1 for t in trades])
    gw, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = float(gw / gl) if gl > 0 else (float("inf") if gw > 0 else None)
    return dict(
        start=str(df.date[i0].date()), end=str(df.date[i1].date()), bars=int(i1 - i0 + 1), years=round(yrs, 3),
        trades=len(trades), win_rate_pct=round(float((rets > 0).mean() * 100), 2) if len(trades) else None,
        pf=round(pf, 3) if pf not in (None, float("inf")) else pf,
        net_return_pct=round((final - 1) * 100, 2),
        cagr_pct=round((final ** (1 / yrs) - 1) * 100, 2),
        max_dd_pct=round(max_dd(marks), 2),
        exposure_pct=round(float(held.mean() * 100), 2) if held is not None else 100.0,
        avg_trade_pct=round(float(rets.mean() * 100), 3) if len(trades) else None,
        avg_hold_bars=round(float(np.mean([t["exit_i"] - t["entry_i"] for t in trades])), 1) if len(trades) else None,
        forced_close_at_end=sum(1 for t in trades if t["forced"]),
    )


def bench_metrics(df, i0, i1, marks):
    days = (df.date[i1] - df.date[i0]).days
    yrs = days / 365.25
    final = marks[-1]
    return dict(net_return_pct=round((final - 1) * 100, 2), cagr_pct=round((final ** (1 / yrs) - 1) * 100, 2),
                max_dd_pct=round(max_dd(marks), 2), trades=1, win_rate_pct=100.0 if final > 1 else 0.0,
                exposure_pct=100.0)


def main():
    df, n_raw = load()
    long_sig, valid, macd, sig, ema_t = signals(df.c.values)
    first_valid = int(np.argmax(valid))
    n = len(df)
    # Period index ranges (independent runs, start flat; indicators use all prior history = no look-ahead)
    is_i0 = first_valid + 1
    is_i1 = int(np.where(df.date <= IS_END)[0][-1])
    oos_i0 = int(np.where(df.date >= OOS_START)[0][0])
    oos_i1 = n - 1
    periods = {"IS": (is_i0, is_i1), "OOS": (oos_i0, oos_i1), "FULL": (is_i0, oos_i1)}

    # ---------------- self-checks against look-ahead ----------------
    checks = {}
    # 1) signal bar strictly before execution bar for every entry/exit
    m, h, tr = simulate(df, long_sig, is_i0, oos_i1, COST)
    ok1 = all(t["sig_i"] < t["entry_i"] for t in tr) and all(
        (t["exit_sig_i"] is None) or (t["exit_sig_i"] < t["exit_i"]) for t in tr)
    checks["signal_bar_lt_execution_bar"] = bool(ok1)
    # 2) truncation test: signals computed on data truncated at k must equal full-data signals at k
    rng = np.random.default_rng(13)
    ks = rng.integers(first_valid + 5, n - 1, size=40)
    ok2 = True
    for k in ks:
        ls_k, _, _, _, _ = signals(df.c.values[:k + 1])
        if not np.array_equal(ls_k, long_sig[:k + 1]):
            ok2 = False
            break
    checks["truncation_invariance_40_random_cuts"] = bool(ok2)
    # 3) future-perturbation test: scrambling closes after k does not change positions up to k+1
    ok3 = True
    for k in ks[:10]:
        cc = df.c.values.copy()
        cc[k + 1:] = cc[k + 1:] * rng.uniform(0.5, 1.5, size=len(cc) - k - 1)
        ls_p, _, _, _, _ = signals(cc)
        if not np.array_equal(ls_p[:k + 1], long_sig[:k + 1]):
            ok3 = False
            break
    checks["future_perturbation_invariance"] = bool(ok3)
    # 4) equity reconciliation: product of trade multipliers == final equity (cash earns 0)
    prod = np.prod([t["e_after"] / t["e_before"] for t in tr])
    checks["equity_equals_product_of_trades"] = bool(abs(prod - m[-1]) < 1e-9)
    # 5) manual recompute of one trade return
    t0 = tr[0]
    manual = (t0["exit_px"] / t0["entry_px"]) * (1 - COST) ** 2 - 1
    checks["trade_return_formula"] = bool(abs(manual - (t0["e_after"] / t0["e_before"] - 1)) < 1e-9)
    checks["intrabar_stop_first"] = "не применимо: в правиле C13 нет стопов/тейков, только вход/выход по открытию"
    checks["last_bar_used"] = str(df.date.iloc[-1].date())
    checks["first_valid_signal_bar"] = str(df.date[first_valid].date())

    # ---------------- run periods ----------------
    out_rows, detail = [], {}
    for name, (i0, i1) in periods.items():
        marks, held, trades = simulate(df, long_sig, i0, i1, COST)
        marks2, _, _ = simulate(df, long_sig, i0, i1, 2 * COST)
        mt = metrics(df, i0, i1, marks, held, trades)
        mt["net_return_2x_cost_pct"] = round((marks2[-1] - 1) * 100, 2)
        bm = bench(df, i0, i1, COST)
        bmt = bench_metrics(df, i0, i1, bm)
        bmt["net_return_2x_cost_pct"] = round((bench(df, i0, i1, 2 * COST)[-1] - 1) * 100, 2)
        mt["ret_over_dd"] = round(mt["net_return_pct"] / abs(mt["max_dd_pct"]), 3) if mt["max_dd_pct"] else None
        bmt["ret_over_dd"] = round(bmt["net_return_pct"] / abs(bmt["max_dd_pct"]), 3) if bmt["max_dd_pct"] else None
        mt["cagr_over_dd"] = round(mt["cagr_pct"] / abs(mt["max_dd_pct"]), 3) if mt["max_dd_pct"] else None
        bmt["cagr_over_dd"] = round(bmt["cagr_pct"] / abs(bmt["max_dd_pct"]), 3) if bmt["max_dd_pct"] else None
        detail[name] = dict(strategy=mt, benchmark=bmt,
                            trades=[{k: v for k, v in t.items() if k not in ("e_before", "e_after")} |
                                    {"ret_pct": round((t["e_after"] / t["e_before"] - 1) * 100, 3)} for t in trades])

    # ---------------- pre-registered verdict on OOS ----------------
    s, b = detail["OOS"]["strategy"], detail["OOS"]["benchmark"]
    fail_reasons = []
    if s["net_return_pct"] <= 0:
        fail_reasons.append("OOS net <= 0")
    if s["pf"] is not None and s["pf"] < 1.0:
        fail_reasons.append("PF < 1.0")
    if s["net_return_pct"] < b["net_return_pct"] and s["max_dd_pct"] < b["max_dd_pct"]:
        fail_reasons.append("хуже бенчмарка и по доходности, и по просадке")
    pass_checks = {
        "net_positive": s["net_return_pct"] > 0,
        "pf_ge_1_2": (s["pf"] is not None and s["pf"] >= 1.2),
        "beats_bench_ret_over_dd": (s["ret_over_dd"] or -1e9) > (b["ret_over_dd"] or -1e9),
        "net_positive_2x_cost": s["net_return_2x_cost_pct"] > 0,
        "oos_trades_ge_30": s["trades"] >= 30,
    }
    if fail_reasons:
        verdict = "FAIL"
    elif s["trades"] < 30:
        verdict = "INCONCLUSIVE"
    elif all(pass_checks.values()):
        verdict = "PASS_CANDIDATE"
    else:
        verdict = "INCONCLUSIVE"
    verdict_note = ("Остаточная категория: ни одно условие FAIL не сработало, но не выполнены все условия PASS_CANDIDATE "
                    f"(не пройдено: {[k for k, v in pass_checks.items() if not v]}). SPEC2 этот случай явно не описывает; "
                    "INCONCLUSIVE выбран как остаточный, без подгонки.") if verdict == "INCONCLUSIVE" and s["trades"] >= 30 else ""

    res = dict(verdict_note=verdict_note,id="C13", rule="Long if MACD(12,26,9) > signal AND close > EMA220 (closed daily bar), else flat; "
                              "execute next-day open; 5 bps/side; benchmark gold B&H",
               data=dict(source="Yahoo chart API https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&period1=..&period2=.. "
                                "(range=max&interval=1d returned dataGranularity=1mo -> saved as unused file; daily pulled by period1/period2). "
                                "GC=F = непрерывный front-month COMEX, без back-adjust роллов.",
                         file=os.path.basename(RAW), sha256=sha256(RAW), rows_raw=n_raw, rows_used=n,
                         start=str(df.date.iloc[0].date()), end=str(df.date.iloc[-1].date()),
                         unused_file=os.path.basename(RAW_MAX), unused_sha256=sha256(RAW_MAX)),
               info_cost_20bps_paxg_route={p: round((simulate(df, long_sig, *periods[p], 0.002)[0][-1] - 1) * 100, 2)
                                           for p in periods},  # NOT a variant: $100-route (PAXG, crypto-spot 20 bps) cost check
               data_quality={str(y): dict(open_eq_close=int(((g.o == g.c)).sum()),
                                          bad_high_low=int(((g.h < g[["o", "c"]].max(axis=1) - 1e-6) |
                                                            (g.l > g[["o", "c"]].min(axis=1) + 1e-6)).sum()))
                             for y, g in df.groupby(df.date.dt.year)},
               self_checks=checks, periods=detail, verdict=verdict, fail_reasons=fail_reasons,
               pass_checks={k: bool(v) for k, v in pass_checks.items()})
    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    # console summary
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    for p in ("IS", "OOS", "FULL"):
        print(p, json.dumps(detail[p]["strategy"], ensure_ascii=False))
        print("  bench", json.dumps(detail[p]["benchmark"], ensure_ascii=False))
    print("VERDICT", verdict, fail_reasons, pass_checks)


if __name__ == "__main__":
    main()
