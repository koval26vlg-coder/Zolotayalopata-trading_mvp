# Independent verification of C13 GOLD_MACD_TREND per SPEC2.md (frozen).
# Rule: long when MACD(12,26,9) line > signal AND close > EMA220; else flat.
# Signal on closed daily bar t, execution at open of bar t+1. Cost 5 bps per side (2x stress = 10 bps).
# Benchmark: gold buy&hold over the same evaluation window (5 bps in and out).
import json, hashlib, sys
import numpy as np
import pandas as pd

BASE = "C:/Users/koval/AppData/Local/Temp/claude/C--Users-koval------------/c3d42fa1-b83c-49f0-8567-13ebcd1f7317/scratchpad/st/C13"
F = BASE + "/data/GC_F_1d_period.json"
EXPECTED_SHA = "bf8a85e65458c9b12e68cb10e004781ca258748191b42bbd62028e090b777369"
LAST_DATE = pd.Timestamp("2026-10-06")
IS_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")
COST = 0.0005

sha = hashlib.sha256(open(F, "rb").read()).hexdigest()
assert sha == EXPECTED_SHA, sha


def load():
    d = json.load(open(F))
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close"]})
    ts = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
    # trading date = New York calendar date of the bar stamp (00:00 ET, or 07:20/09:30 ET on half days)
    df["date"] = pd.to_datetime(ts.date)
    raw = len(df)
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[df["date"] <= LAST_DATE].reset_index(drop=True)
    assert not df["date"].duplicated().any()
    return df, raw


def ema_sma_seed(x: np.ndarray, n: int) -> np.ndarray:
    """EMA with alpha=2/(n+1), seeded with SMA of the first n valid values; NaN before."""
    out = np.full(len(x), np.nan)
    a = 2.0 / (n + 1)
    valid = np.where(~np.isnan(x))[0]
    if len(valid) < n:
        return out
    s0 = valid[0]
    seed_idx = s0 + n - 1
    out[seed_idx] = np.mean(x[s0:s0 + n])
    for i in range(seed_idx + 1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def ema_pandas(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def signals(close: np.ndarray, method="sma"):
    f = ema_sma_seed if method == "sma" else ema_pandas
    e12, e26 = f(close, 12), f(close, 26)
    macd = e12 - e26
    sig = f(macd, 9)
    e220 = f(close, 220)
    ok = ~np.isnan(macd) & ~np.isnan(sig) & ~np.isnan(e220)
    if method != "sma":
        # pandas ewm is defined from bar 0; impose same warm-up as SMA seed (219 bars) for comparability
        ok[:219] = False
    s = ok & (macd > sig) & (close > e220)
    return s.astype(int), ok


def backtest(df, sig, i0, i1, cost):
    """Run on bars i0..i1 inclusive, starting flat. Position on bar i = sig[i-1] (known at close i-1),
    changed at open of bar i. Forced exit at close of bar i1 if still long."""
    o, c = df["open"].values, df["close"].values
    eq = 1.0
    units = 0.0
    inpos = False
    entry_eq = None
    trades = []
    curve = np.empty(i1 - i0 + 1)
    exposure_bars = 0
    for k, i in enumerate(range(i0, i1 + 1)):
        target = sig[i - 1] if i - 1 >= 0 else 0
        if target == 1 and not inpos:
            entry_eq = eq
            units = eq * (1 - cost) / o[i]
            inpos = True
            entry_date = df["date"].iat[i]
            entry_px = o[i]
        elif target == 0 and inpos:
            eq = units * o[i] * (1 - cost)
            trades.append((entry_date, df["date"].iat[i], entry_px, o[i], eq / entry_eq - 1, eq - entry_eq, "open"))
            inpos = False
            units = 0.0
        if inpos:
            exposure_bars += 1
            curve[k] = units * c[i]
        else:
            curve[k] = eq
    if inpos:
        eq = units * c[i1] * (1 - cost)
        trades.append((entry_date, df["date"].iat[i1], entry_px, c[i1], eq / entry_eq - 1, eq - entry_eq, "forced_close"))
        curve[-1] = eq
    tr = pd.DataFrame(trades, columns=["entry", "exit", "px_in", "px_out", "ret", "pnl", "how"])
    return eq, curve, tr, exposure_bars


def metrics(df, i0, i1, eq, curve, tr, expo):
    d0, d1 = df["date"].iat[i0], df["date"].iat[i1]
    yrs = (d1 - d0).days / 365.25
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))
    dd = (np.concatenate([[1.0], curve]) / peak - 1).min()
    gw = tr.loc[tr.pnl > 0, "pnl"].sum()
    gl = -tr.loc[tr.pnl < 0, "pnl"].sum()
    gwr = tr.loc[tr.ret > 0, "ret"].sum()
    glr = -tr.loc[tr.ret < 0, "ret"].sum()
    return dict(
        start=str(d0.date()), end=str(d1.date()), years=round(yrs, 3), bars=i1 - i0 + 1,
        trades=len(tr), win_rate_pct=round(100 * (tr.ret > 0).mean(), 2) if len(tr) else None,
        pf=round(gw / gl, 3) if gl > 0 else None, pf_on_returns=round(gwr / glr, 3) if glr > 0 else None,
        net_return_pct=round(100 * (eq - 1), 2), cagr_pct=round(100 * (eq ** (1 / yrs) - 1), 2),
        max_dd_pct=round(100 * dd, 2), exposure_pct=round(100 * expo / (i1 - i0 + 1), 2),
        avg_trade_pct=round(100 * tr.ret.mean(), 3) if len(tr) else None,
    )


def bench(df, i0, i1, cost):
    o, c = df["open"].values, df["close"].values
    units = (1 - cost) / o[i0]
    curve = units * c[i0:i1 + 1]
    final = units * c[i1] * (1 - cost)
    curve[-1] = final
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))
    dd = (np.concatenate([[1.0], curve]) / peak - 1).min()
    yrs = (df["date"].iat[i1] - df["date"].iat[i0]).days / 365.25
    return dict(net_return_pct=round(100 * (final - 1), 2), max_dd_pct=round(100 * dd, 2),
                cagr_pct=round(100 * (final ** (1 / yrs) - 1), 2))


def run(method="sma", verbose=True):
    df, raw = load()
    sig, ok = signals(df["close"].values, method)
    first_valid = int(np.argmax(ok))
    first_trade_bar = first_valid + 1
    dates = df["date"]
    is_end = int(np.where(dates <= IS_END)[0].max())
    oos_start = int(np.where(dates >= OOS_START)[0].min())
    last = len(df) - 1
    periods = {"IS": (first_trade_bar, is_end), "OOS": (oos_start, last), "FULL": (first_trade_bar, last)}
    out = {}
    for name, (a, b) in periods.items():
        eq, curve, tr, expo = backtest(df, sig, a, b, COST)
        m = metrics(df, a, b, eq, curve, tr, expo)
        eq2, *_ = backtest(df, sig, a, b, 2 * COST)
        m["net_return_2x_cost_pct"] = round(100 * (eq2 - 1), 2)
        bm = bench(df, a, b, COST)
        m["bench_net_return_pct"] = bm["net_return_pct"]
        m["bench_max_dd_pct"] = bm["max_dd_pct"]
        m["bench_cagr_pct"] = bm["cagr_pct"]
        m["ratio_ret_dd"] = round(m["net_return_pct"] / abs(m["max_dd_pct"]), 3)
        m["bench_ratio_ret_dd"] = round(bm["net_return_pct"] / abs(bm["max_dd_pct"]), 3)
        m["forced_close"] = int((tr.how == "forced_close").sum()) if len(tr) else 0
        out[name] = (m, tr)
    if verbose:
        print(f"method={method} raw_rows={raw} clean_rows={len(df)} first={df.date.iat[0].date()} last={df.date.iat[-1].date()} first_valid_signal={df.date.iat[first_valid].date()}")
        for k, (m, tr) in out.items():
            print(k, json.dumps(m, ensure_ascii=False))
    return df, sig, out


def lookahead_tests(df, sig_full):
    rng = np.random.default_rng(0)
    c = df["close"].values
    n = len(c)
    for _ in range(30):
        cut = int(rng.integers(300, n))
        s_cut, _ = signals(c[:cut], "sma")
        assert np.array_equal(s_cut, sig_full[:cut]), cut
    # corrupt future
    c2 = c.copy(); c2[5000:] *= rng.uniform(0.5, 1.5, n - 5000)
    s2, _ = signals(c2, "sma")
    assert np.array_equal(s2[:5000], sig_full[:5000])
    print("look-ahead tests OK (truncation x30, future corruption)")


def vector_check(df, sig, a, b, cost):
    """Independent vectorised equity: daily return = position * (close-to-close) with open-based entry/exit legs."""
    o, c = df["open"].values, df["close"].values
    pos = np.zeros(len(df)); pos[1:] = sig[:-1]
    pos = pos[a:b + 1].copy()
    # start flat: pos on bar a = sig[a-1] (allowed: signal known at close a-1)
    prev = np.concatenate([[0], pos[:-1]])
    oo, cc = o[a:b + 1], c[a:b + 1]
    cprev = np.concatenate([[np.nan], cc[:-1]])
    r = np.zeros(len(pos))
    for k in range(len(pos)):
        if prev[k] == 0 and pos[k] == 1:
            r[k] = (cc[k] / oo[k]) * (1 - cost) - 1
        elif prev[k] == 1 and pos[k] == 1:
            r[k] = cc[k] / cprev[k] - 1
        elif prev[k] == 1 and pos[k] == 0:
            r[k] = (oo[k] / cprev[k]) * (1 - cost) - 1
    if pos[-1] == 1:
        r[-1] = (1 + r[-1]) * (1 - cost) - 1
    eq = np.cumprod(1 + r)
    switches = int(np.abs(np.diff(np.concatenate([[0], pos, [0]]))).sum())
    return 100 * (eq[-1] - 1), switches


if __name__ == "__main__":
    df, sig, out = run("sma")
    lookahead_tests(df, sig)
    dates = df["date"]
    for name, (a, b) in {"OOS": (int(np.where(dates >= OOS_START)[0].min()), len(df) - 1)}.items():
        v, sw = vector_check(df, sig, a, b, COST)
        print(f"vector check {name}: net={v:.2f}% switches={sw}")
    print("--- sensitivity: pandas ewm(adjust=False) seed ---")
    run("pandas")
    m, tr = out["OOS"]
    tr.to_csv(BASE + "/verify/oos_trades.csv", index=False)
    out["IS"][1].to_csv(BASE + "/verify/is_trades.csv", index=False)
    json.dump({k: v[0] for k, v in out.items()}, open(BASE + "/verify/verify_result.json", "w"), ensure_ascii=False, indent=1)
