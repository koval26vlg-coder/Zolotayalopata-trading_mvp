# -*- coding: utf-8 -*-
"""
C2 FUNDING_OVERHEAT_FILTER  (SPEC2.md, frozen 2026-10-07)

Rule (frozen): BTC spot long by default; go to USDT when trailing 7-day mean BTC funding > 0.03%/8h;
re-enter BTC when trailing 7-day mean < 0.01%/8h. Evaluate daily at 00:00 UTC using funding settled
before then. Execution at that day's open (00:00 UTC). Benchmark: BTC buy&hold same period.
Costs: crypto spot 20 bps per side; stress 2x = 40 bps.

Data (public, one-shot, no keys):
  - Binance USD-M futures funding: https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT
  - Binance spot daily klines:     https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d
"""
import hashlib
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

F_FUND = os.path.join(DATA, "binance_fapi_fundingRate_BTCUSDT.json")
F_KL = os.path.join(DATA, "binance_spot_klines_BTCUSDT_1d.json")

CUTOFF = pd.Timestamp("2026-10-07 00:00", tz="UTC")  # bars closed on/before 2026-10-06 23:59 UTC
IS_END = pd.Timestamp("2022-12-31", tz="UTC")
OOS_START = pd.Timestamp("2023-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-10-06", tz="UTC")

HI = 0.0003   # 0.03% per 8h -> exit to USDT
LO = 0.0001   # 0.01% per 8h -> re-enter BTC
WIN = pd.Timedelta(days=7)
COST = 0.0020  # 20 bps per side


def ms(ts):
    return int(ts.timestamp() * 1000)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research-backtest"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def download():
    end_ms = ms(CUTOFF) - 1
    if not os.path.exists(F_FUND):
        out, start = [], ms(pd.Timestamp("2019-09-01", tz="UTC"))
        while True:
            url = (f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT"
                   f"&startTime={start}&endTime={end_ms}&limit=1000")
            page = get_json(url)
            if not page:
                break
            out.extend(page)
            last = page[-1]["fundingTime"]
            if len(page) < 1000:
                break
            start = last + 1
            time.sleep(0.3)
        with open(F_FUND, "w") as f:
            json.dump(out, f)
    if not os.path.exists(F_KL):
        out, start = [], ms(pd.Timestamp("2017-08-01", tz="UTC"))
        while True:
            url = (f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d"
                   f"&startTime={start}&endTime={end_ms}&limit=1000")
            page = get_json(url)
            if not page:
                break
            out.extend(page)
            if len(page) < 1000:
                break
            start = page[-1][0] + 1
            time.sleep(0.3)
        with open(F_KL, "w") as f:
            json.dump(out, f)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load():
    fund = pd.DataFrame(json.load(open(F_FUND)))
    fund["t"] = pd.to_datetime(fund["fundingTime"].astype("int64"), unit="ms", utc=True)
    fund["rate"] = fund["fundingRate"].astype(float)
    # exact integer representation in units of 1e-8 (Binance publishes 8 decimals) so that the strict
    # thresholds "> 0.03%" and "< 0.01%" are applied without floating-point error
    # (21 x 0.00010000 summed in float gives 9.999999999999999e-05 < 1e-4, a spurious trigger)
    from decimal import Decimal
    dec = fund["fundingRate"].map(Decimal)
    assert all((x * Decimal(10**8)) == (x * Decimal(10**8)).to_integral_value() for x in dec)
    fund["r_int"] = dec.map(lambda x: int(x * Decimal(10**8))).astype("int64")
    fund = fund[["t", "rate", "r_int"]].drop_duplicates("t").sort_values("t").reset_index(drop=True)
    fund = fund[fund["t"] < CUTOFF]

    kl = pd.DataFrame(json.load(open(F_KL)))
    kl = kl.iloc[:, :7]
    kl.columns = ["ot", "open", "high", "low", "close", "vol", "ct"]
    kl["date"] = pd.to_datetime(kl["ot"].astype("int64"), unit="ms", utc=True)
    kl["close_time"] = pd.to_datetime(kl["ct"].astype("int64"), unit="ms", utc=True)
    for c in ["open", "high", "low", "close"]:
        kl[c] = kl[c].astype(float)
    kl = kl[kl["close_time"] < CUTOFF]  # only closed bars
    kl = kl.drop_duplicates("date").set_index("date").sort_index()
    return fund, kl


def compute_signal(fund, dates):
    """For each evaluation date D (00:00 UTC), trailing 7d mean of funding settled strictly before D.
    Returns DataFrame with mean8h, n settlements, last funding timestamp used."""
    t = fund["t"].values
    r = fund["rate"].values
    ri = fund["r_int"].values
    rows = []
    for D in dates:
        lo = np.searchsorted(t, np.datetime64((D - WIN).tz_convert(None)), side="left")
        hi = np.searchsorted(t, np.datetime64(D.tz_convert(None)), side="left")  # strictly < D
        seg = r[lo:hi]
        last_used = pd.Timestamp(t[hi - 1]).tz_localize("UTC") if hi > 0 else pd.NaT
        # normalise to "per 8h": total funding over 7 days / 21 eight-hour periods
        # (identical to the plain mean when the venue settles every 8h)
        mean8h = seg.sum() / 21.0 if len(seg) else np.nan
        sum_int = int(ri[lo:hi].sum())  # exact 7-day sum in 1e-8 units
        rows.append((D, mean8h, sum_int, len(seg), last_used))
    s = pd.DataFrame(rows, columns=["date", "mean8h", "sum_int", "n", "last_used"]).set_index("date")
    return s


def state_machine(sig):
    """Hysteresis. Start long BTC (default). Returns position (1=BTC, 0=USDT) to hold during day D,
    decided at D 00:00 and executed at D open."""
    # exact comparisons: mean > 0.03%  <=>  sum_21 > 21*30000 (1e-8 units); mean < 0.01% <=> sum_21 < 21*10000
    HI_SUM = 21 * round(HI * 10**8)
    LO_SUM = 21 * round(LO * 10**8)
    pos, out = 1, []
    for si in sig["sum_int"].values:
        if pos == 1 and si > HI_SUM:
            pos = 0
        elif pos == 0 and si < LO_SUM:
            pos = 1
        out.append(pos)
    return pd.Series(out, index=sig.index, name="pos")


def simulate(kl, pos, start, end, cost):
    """Independent run for a period. Capital 1.0 in USDT at period start.
    At each day open: trade to target pos (cost per side). Mark at close. At period end, liquidate at last close."""
    d = kl.loc[start:end].copy()
    p = pos.loc[start:end]
    assert (d.index == p.index).all()
    cash, btc = 1.0, 0.0
    eq = [1.0]
    eq_dates = [d.index[0] - pd.Timedelta(seconds=1)]
    trades = []
    cur = 0
    entry_eq = None
    entry_date = None
    for D, row in d.iterrows():
        tgt = int(p.loc[D])
        if tgt != cur:
            if tgt == 1:
                entry_eq = cash
                entry_date = D
                btc = cash * (1 - cost) / row["open"]
                cash = 0.0
            else:
                cash = btc * row["open"] * (1 - cost)
                btc = 0.0
                trades.append({"entry": entry_date, "exit": D, "pnl": cash - entry_eq,
                               "ret": cash / entry_eq - 1})
            cur = tgt
        eq.append(cash + btc * row["close"])
        eq_dates.append(D)
    # final liquidation at last close
    last = d.index[-1]
    if cur == 1:
        cash = btc * d["close"].iloc[-1] * (1 - cost)
        btc = 0.0
        trades.append({"entry": entry_date, "exit": last, "pnl": cash - entry_eq,
                       "ret": cash / entry_eq - 1, "forced_end": True})
        eq[-1] = cash
    eqs = pd.Series(eq, index=eq_dates)
    return eqs, trades, d, p


def metrics(eqs, trades, p, ndays):
    final = eqs.iloc[-1]
    net = (final - 1) * 100
    years = ndays / 365.25
    cagr = (final ** (1 / years) - 1) * 100 if final > 0 else -100.0
    dd = (eqs / eqs.cummax() - 1).min() * 100
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gl = -sum(losses)
    pf = (sum(wins) / gl) if gl > 0 else None
    wr = (len(wins) / len(trades) * 100) if trades else None
    expo = float(p.mean() * 100)
    return {"trades": len(trades), "win_rate_pct": None if wr is None else round(wr, 2),
            "pf": None if pf is None else round(pf, 3), "net_return_pct": round(net, 2),
            "cagr_pct": round(cagr, 2), "max_dd_pct": round(dd, 2), "exposure_pct": round(expo, 2)}


def run_period(kl, pos, start, end, label):
    ndays = (end - start).days + 1
    eqs, trades, d, p = simulate(kl, pos, start, end, COST)
    m = metrics(eqs, trades, p, ndays)
    eqs2, tr2, _, _ = simulate(kl, pos, start, end, 2 * COST)
    m["net_return_2x_cost_pct"] = round((eqs2.iloc[-1] - 1) * 100, 2)
    # benchmark: buy&hold same period, same cost model (buy at first open, sell at last close)
    ones = pd.Series(1, index=p.index)
    beqs, btr, _, _ = simulate(kl, ones, start, end, COST)
    bm = metrics(beqs, btr, ones, ndays)
    m["bench_net_return_pct"] = bm["net_return_pct"]
    m["bench_max_dd_pct"] = bm["max_dd_pct"]
    m["bench_cagr_pct"] = bm["cagr_pct"]
    m["period"] = label
    m["start"] = str(start.date())
    m["end"] = str(end.date())
    m["n_days"] = ndays
    m["trade_list"] = [{"entry": str(t["entry"].date()), "exit": str(t["exit"].date()),
                        "ret_pct": round(t["ret"] * 100, 2),
                        "forced_end": bool(t.get("forced_end", False))} for t in trades]
    return m


def self_checks(fund, kl, sig, pos):
    checks = {}
    # 1) every funding settlement used for day D is strictly before D 00:00 (= execution time, D open)
    ok = bool((sig["last_used"] < sig.index).all())
    checks["signal_time_lt_execution_time"] = ok
    assert ok
    # 2) full 21-settlement window everywhere in the evaluated range
    checks["min_settlements_in_window"] = int(sig["n"].min())
    checks["max_settlements_in_window"] = int(sig["n"].max())
    # 3) truncation test: recompute signal/state using only data available before cutoff T;
    #    positions for D <= T must be identical (no future data leaks into past decisions)
    rng = np.random.default_rng(0)
    idx = sig.index
    cut_ok = True
    for T in sorted(rng.choice(idx[30:-1], 8, replace=False)):
        T = pd.Timestamp(T)
        f_tr = fund[fund["t"] < T]
        s_tr = compute_signal(f_tr, idx[idx <= T])
        p_tr = state_machine(s_tr)
        if not (p_tr.values == pos.loc[:T].values).all():
            cut_ok = False
    checks["truncation_test_positions_identical"] = cut_ok
    assert cut_ok
    # 4) only closed daily bars used
    checks["last_daily_bar"] = str(kl.index[-1].date())
    checks["last_funding_used"] = str(fund["t"].max())
    # 5) funding interval sanity (hours between settlements)
    dh = fund["t"].diff().dt.total_seconds().div(3600).dropna()
    checks["funding_interval_hours_counts"] = {str(k): int(v) for k, v in dh.round(2).value_counts().items()}
    checks["intrabar_stop_rule"] = "N/A (no stops/TP; switches only at daily open)"
    return checks


def main():
    download()
    fund, kl = load()
    # evaluation dates: daily bars where a full 7-day funding window exists
    first_full = fund["t"].min() + WIN  # window [D-7d, D) must start at/after first settlement
    first_full = first_full.ceil("D")
    dates = kl.index[kl.index >= first_full]
    sig = compute_signal(fund, dates)
    pos = state_machine(sig)
    checks = self_checks(fund, kl, sig, pos)

    start = dates[0]
    full_end = kl.index[-1]
    periods = [("IS", start, IS_END), ("OOS", OOS_START, min(OOS_END, full_end)),
               ("FULL", start, min(OOS_END, full_end))]
    rows = [run_period(kl, pos, a, b, lab) for lab, a, b in periods]

    # regime switches overview (full history)
    sw = pos.diff().fillna(0)
    switch_list = [{"date": str(d.date()), "to": "BTC" if pos.loc[d] == 1 else "USDT",
                    "mean8h_pct": round(sig.loc[d, "sum_int"] / 21 / 1e6, 6)} for d in pos.index[sw != 0]]

    # mechanical verdict on OOS
    o = [r for r in rows if r["period"] == "OOS"][0]
    fail_reasons = []
    if o["net_return_pct"] <= 0:
        fail_reasons.append("OOS net <= 0")
    if o["pf"] is not None and o["pf"] < 1.0:
        fail_reasons.append("PF < 1.0")
    if o["net_return_pct"] < o["bench_net_return_pct"] and o["max_dd_pct"] < o["bench_max_dd_pct"]:
        fail_reasons.append("worse than benchmark on BOTH return and maxDD")
    ratio = o["net_return_pct"] / abs(o["max_dd_pct"]) if o["max_dd_pct"] else None
    bratio = o["bench_net_return_pct"] / abs(o["bench_max_dd_pct"]) if o["bench_max_dd_pct"] else None
    pass_crit = {
        "net_positive": bool(o["net_return_pct"] > 0),
        "pf_ge_1.2": (o["pf"] is not None and o["pf"] >= 1.2) or (o["pf"] is None and o["trades"] > 0),
        "beats_bench_ret_over_maxdd": bool(ratio is not None and bratio is not None and ratio > bratio),
        "net_positive_2x_cost": bool(o["net_return_2x_cost_pct"] > 0),
        "oos_trades_ge_30": bool(o["trades"] >= 30),
    }
    if fail_reasons:
        verdict = "FAIL"
    elif not pass_crit["oos_trades_ge_30"]:
        verdict = "INCONCLUSIVE"
    elif all(pass_crit.values()):
        verdict = "PASS_CANDIDATE"
    else:
        verdict = "INCONCLUSIVE"

    result = {
        "id": "C2",
        "data_sources": [
            {"name": "Binance USD-M BTCUSDT funding (fapi/v1/fundingRate)",
             "url": "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT",
             "file": F_FUND, "sha256": sha256(F_FUND), "rows": int(len(fund)),
             "start": str(fund["t"].min()), "end": str(fund["t"].max())},
            {"name": "Binance spot BTCUSDT 1d klines (api/v3/klines)",
             "url": "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d",
             "file": F_KL, "sha256": sha256(F_KL), "rows": int(len(kl)),
             "start": str(kl.index.min().date()), "end": str(kl.index.max().date())},
        ],
        "eval_start": str(start.date()),
        "rows": rows,
        "self_checks": checks,
        "switches": switch_list,
        "ret_over_maxdd": {"strategy": ratio, "bench": bratio},
        "verdict": verdict,
        "fail_reasons": fail_reasons,
        "pass_criteria": pass_crit,
    }
    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows",)}, ensure_ascii=False, indent=1, default=str)[:6000])
    for r in rows:
        rr = {k: v for k, v in r.items() if k != "trade_list"}
        print(rr)
        print("  trades:", r["trade_list"])


if __name__ == "__main__":
    main()
