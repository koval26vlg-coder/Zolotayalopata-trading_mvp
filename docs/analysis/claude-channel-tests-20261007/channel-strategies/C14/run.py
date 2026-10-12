# C14 DAX_ORB — frozen per SPEC2.md (2026-10-07). No tuning, no variants.
# Data: Yahoo chart API ^GDAXI interval=60m range=730d (one-shot download, saved in data/).
import json, hashlib, math, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "gdaxi_60m_730d.json")
OUT = os.path.join(HERE, "result.json")

COST = 0.0003          # DAX index CFD/fut proxy: 3 bps per side
LAST_UTC = pd.Timestamp("2026-10-06 23:59:59", tz="UTC")
SESSION_FIRST = "09:00"  # range bar 09:00-10:00
SESSION_LAST = "17:00"   # last hourly bar 17:00-17:30 (Xetra close 17:30)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load():
    d = json.load(open(RAW))
    r = d["chart"]["result"][0]
    ts = pd.to_datetime(r["timestamp"], unit="s", utc=True)
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ["open", "high", "low", "close"]}, index=ts)
    df = df.dropna()
    # bar must be closed on/before cutoff: bar end = start + 1h (17:00 bar ends 17:30)
    df = df[df.index + pd.Timedelta(hours=1) <= LAST_UTC]
    df.index = df.index.tz_convert("Europe/Berlin")  # handles DST
    df["hm"] = df.index.strftime("%H:%M")
    df = df[(df.hm >= SESSION_FIRST) & (df.hm <= SESSION_LAST)].copy()
    df["date"] = df.index.date
    return df


def day_signal(o, h, l, c):
    """Uses ONLY closed bars. Returns (signal_idx, side) or (None, 0).
    Bar 0 = range bar. Signal on first close outside the range at bar i>=1; needs bar i+1 to execute."""
    rh, rl = h[0], l[0]
    for i in range(1, len(c)):
        if c[i] > rh:
            return i, 1
        if c[i] < rl:
            return i, -1
    return None, 0


def simulate(df, cost):
    trades, daily = [], []
    eq = 1.0
    bars_total = 0
    bars_in = 0
    skipped_days = []
    for dt, g in df.groupby("date", sort=True):
        o, h, l, c = (g[k].to_numpy() for k in ["open", "high", "low", "close"])
        hm = g["hm"].to_list()
        bars_total += len(g)
        if hm[0] != SESSION_FIRST:
            skipped_days.append(str(dt))
            daily.append((dt, eq, c[-1]))
            continue
        si, side = day_signal(o, h, l, c)
        if si is None or si + 1 >= len(c):
            daily.append((dt, eq, c[-1]))
            continue
        ei = si + 1
        # --- look-ahead self-check: signal must be identical when computed on data truncated at signal bar
        si2, side2 = day_signal(o[: si + 1], h[: si + 1], l[: si + 1], c[: si + 1])
        assert si2 == si and side2 == side, "truncation check failed"
        assert ei > si >= 1, "signal bar must precede execution bar and follow range bar"
        entry = o[ei]
        stop = l[0] if side == 1 else h[0]
        exit_px, exit_i, reason = None, None, None
        for j in range(ei, len(c)):
            # stop-first intrabar rule: stop checked before end-of-session close
            if side == 1:
                if o[j] <= stop:
                    exit_px, exit_i, reason = o[j], j, "stop_gap"
                    break
                if l[j] <= stop:
                    exit_px, exit_i, reason = stop, j, "stop"
                    break
            else:
                if o[j] >= stop:
                    exit_px, exit_i, reason = o[j], j, "stop_gap"
                    break
                if h[j] >= stop:
                    exit_px, exit_i, reason = stop, j, "stop"
                    break
        if exit_px is None:
            exit_px, exit_i, reason = c[-1], len(c) - 1, "session_close"
        assert exit_i >= ei
        gross = side * (exit_px - entry) / entry
        ret = gross - cost - cost * exit_px / entry
        pnl = eq * ret
        eq_before = eq
        eq = eq + pnl
        bars_in += exit_i - ei + 1
        trades.append(dict(date=str(dt), side=side, signal_bar=g.index[si].isoformat(),
                           entry_bar=g.index[ei].isoformat(), exit_bar=g.index[exit_i].isoformat(),
                           range_high=h[0], range_low=l[0], entry=entry, exit=exit_px,
                           reason=reason, ret=ret, pnl=pnl, eq_before=eq_before, eq_after=eq))
        daily.append((dt, eq, c[-1]))
    tr = pd.DataFrame(trades)
    dl = pd.DataFrame(daily, columns=["date", "eq", "dax_close"]).set_index("date")
    return tr, dl, bars_in / bars_total, skipped_days


def max_dd(series_with_start):
    s = np.asarray(series_with_start, dtype=float)
    peak = np.maximum.accumulate(s)
    return float(((s / peak) - 1).min() * 100)


def years_between(d0, d1):
    return (pd.Timestamp(d1) - pd.Timestamp(d0)).days / 365.25


def metrics(tr, dl, exposure, first_date, last_date):
    eq_path = [1.0] + dl["eq"].tolist()
    final = eq_path[-1]
    yrs = years_between(first_date, last_date)
    wins = tr.loc[tr.pnl > 0, "pnl"].sum()
    losses = -tr.loc[tr.pnl < 0, "pnl"].sum()
    return dict(
        trades=int(len(tr)),
        win_rate_pct=round(float((tr.pnl > 0).mean() * 100), 2) if len(tr) else None,
        pf=round(float(wins / losses), 3) if losses > 0 else None,
        net_return_pct=round((final - 1) * 100, 2),
        cagr_pct=round((final ** (1 / yrs) - 1) * 100, 2),
        max_dd_pct=round(max_dd(eq_path), 2),
        exposure_pct=round(exposure * 100, 2),
    )


def benchmark(df, cost):
    first = df.iloc[0]
    entry = first["open"]
    closes = df.groupby("date")["close"].last()
    path = [1.0] + list((1 - cost) * closes.to_numpy() / entry)
    final = (1 - cost) * closes.iloc[-1] / entry * (1 - cost)
    path[-1] = final
    yrs = years_between(closes.index[0], closes.index[-1])
    return dict(net_return_pct=round((final - 1) * 100, 2),
                cagr_pct=round((final ** (1 / yrs) - 1) * 100, 2),
                max_dd_pct=round(max_dd(path), 2))


def main():
    df = load()
    first_date, last_date = df["date"].iloc[0], df["date"].iloc[-1]
    tr, dl, expo, skipped = simulate(df, COST)
    tr2, dl2, _, _ = simulate(df, 2 * COST)
    m = metrics(tr, dl, expo, first_date, last_date)
    m2 = metrics(tr2, dl2, expo, first_date, last_date)
    b = benchmark(df, COST)

    # self-checks
    assert (pd.to_datetime(tr.entry_bar, utc=True) > pd.to_datetime(tr.signal_bar, utc=True)).all()
    assert (pd.to_datetime(tr.exit_bar, utc=True) >= pd.to_datetime(tr.entry_bar, utc=True)).all()
    assert (tr.entry_bar.str[:10] == tr.exit_bar.str[:10]).all() and (tr.entry_bar.str[:10] == tr.date).all()
    assert tr.date.is_unique  # max one trade per day
    assert pd.Timestamp(last_date) <= pd.Timestamp("2026-10-06")
    # stop exits never better than stop level (stop-first, no favourable fill)
    st = tr[tr.reason == "stop"]
    assert ((st.side == 1) & np.isclose(st.exit, st.range_low) | (st.side == -1) & np.isclose(st.exit, st.range_high)).all()

    # verdict (FULL only: data starts 2023-11-21, i.e. after 2022)
    ret, pf, dd = m["net_return_pct"], m["pf"], m["max_dd_pct"]
    worse_both = (ret < b["net_return_pct"]) and (dd < b["max_dd_pct"])
    ratio = ret / abs(dd) if dd < 0 else float("inf")
    bratio = b["net_return_pct"] / abs(b["max_dd_pct"]) if b["max_dd_pct"] < 0 else float("inf")
    if ret <= 0 or (pf is not None and pf < 1.0) or worse_both:
        verdict = "FAIL"
    elif m["trades"] < 30:
        verdict = "INCONCLUSIVE"
    elif ret > 0 and pf >= 1.2 and ratio > bratio and m2["net_return_pct"] > 0:
        verdict = "PASS_CANDIDATE"
    else:
        verdict = "INCONCLUSIVE"

    # descriptive breakdowns (not used for verdict)
    tr["year"] = tr.date.str[:4]
    by_year = tr.groupby("year").apply(lambda x: dict(trades=len(x), compounded_ret_pct=round((np.prod(1 + x.ret) - 1) * 100, 2),
                                                        win_rate_pct=round((x.ret > 0).mean() * 100, 1))).to_dict()
    by_side = tr.groupby("side").apply(lambda x: dict(trades=len(x), compounded_ret_pct=round((np.prod(1 + x.ret) - 1) * 100, 2),
                                                        win_rate_pct=round((x.ret > 0).mean() * 100, 1),
                                                        mean_ret_bps=round(x.ret.mean() * 1e4, 2))).to_dict()
    reasons = tr.reason.value_counts().to_dict()
    gross_mean_bps = round(float(((tr.ret + COST + COST * tr.exit / tr.entry)).mean() * 1e4), 2)

    res = dict(
        id="C14", verdict=verdict,
        data=dict(file=os.path.relpath(RAW, HERE), sha256=sha256(RAW), first_date=str(first_date), last_date=str(last_date),
                  sessions=int(df["date"].nunique()), bars=int(len(df)), skipped_days_no_0900_bar=skipped),
        full=m, full_2x_cost=m2, benchmark=b,
        ret_dd_ratio=round(ratio, 3), bench_ret_dd_ratio=round(bratio, 3),
        by_year=by_year, by_side={str(k): v for k, v in by_side.items()}, exit_reasons=reasons,
        mean_gross_ret_bps=gross_mean_bps, mean_net_ret_bps=round(float(tr.ret.mean() * 1e4), 2),
        days_with_trade_pct=round(len(tr) / df["date"].nunique() * 100, 2),
        self_checks="passed: entry_bar>signal_bar; signal identical on truncated data; signal bar>=1 (after 09:00 range bar); "
                    "exit same session; one trade/day; stop-first incl. gap-through at open; last bar <= 2026-10-06",
    )
    json.dump(res, open(OUT, "w"), indent=2, default=str)
    tr.to_csv(os.path.join(HERE, "trades.csv"), index=False)
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
