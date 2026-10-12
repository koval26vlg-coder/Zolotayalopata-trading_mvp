# Independent re-implementation of C14 DAX_ORB from SPEC2.md (verifier)
import json, hashlib, sys
import numpy as np, pandas as pd

BASE = "C:/Users/koval/AppData/Local/Temp/claude/C--Users-koval------------/c3d42fa1-b83c-49f0-8567-13ebcd1f7317/scratchpad/st/C14"
RAW = BASE + "/data/gdaxi_60m_730d.json"
EXPECTED_SHA = "04ba87fd5d8ff8af300f240d8a4361fce8d42f61bd4f2f46fbdb70a9094c3f58"
COST = 0.0003  # 3 bps per side
LAST_UTC = pd.Timestamp("2026-10-06 23:59:59", tz="UTC")

sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
assert sha == EXPECTED_SHA, sha

d = json.load(open(RAW))["chart"]["result"][0]
q = d["indicators"]["quote"][0]
df = pd.DataFrame({"ts": d["timestamp"], "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]})
df["utc"] = pd.to_datetime(df.ts, unit="s", utc=True)
df["t"] = df.utc.dt.tz_convert("Europe/Berlin")
gran = d["meta"]["dataGranularity"]
assert gran in ("1h", "60m"), gran

# bar end = start + 60m; the session's final bar (17:00) ends at 17:30 (session close). Keep bars whose close time <= cutoff.
df["end_utc"] = df.utc + pd.Timedelta(hours=1)
df = df[df.end_utc.dt.tz_convert("Europe/Berlin").dt.normalize() <= pd.Timestamp("2026-10-06", tz="Europe/Berlin")]
# exclude irregular partial bars (non-hour-aligned timestamps, e.g. live 09:52:29 bar)
df = df[(df.t.dt.minute == 0) & (df.t.dt.second == 0)]
df = df.dropna(subset=["open", "high", "low", "close"])
# session 09:00-17:30 Berlin: hourly bars starting 09:00..17:00
mins = df.t.dt.hour * 60 + df.t.dt.minute
df = df[(mins >= 9 * 60) & (mins < 17 * 60 + 30)].copy()
df["date"] = df.t.dt.date
assert df.utc.max() + pd.Timedelta(minutes=30) <= LAST_UTC

def run(cost, cost_mode="additive"):
    trades = []
    skipped = []
    bars_in_pos = 0
    total_bars = 0
    for dt, g in df.groupby("date", sort=True):
        g = g.sort_values("t").reset_index(drop=True)
        total_bars += len(g)
        if g.t.iloc[0].hour != 9:
            skipped.append(str(dt)); continue
        H, L = g.high.iloc[0], g.low.iloc[0]
        sig_i, side = None, 0
        for i in range(1, len(g)):
            c = g.close.iloc[i]
            if c > H:
                sig_i, side = i, 1; break
            if c < L:
                sig_i, side = i, -1; break
        if sig_i is None or sig_i + 1 >= len(g):
            continue  # no breakout, or breakout on last session bar (no next bar in session)
        e_i = sig_i + 1
        entry = g.open.iloc[e_i]
        stop = L if side == 1 else H
        exit_px, exit_i, reason = None, None, None
        for j in range(e_i, len(g)):
            o, h, l = g.open.iloc[j], g.high.iloc[j], g.low.iloc[j]
            if side == 1:
                if o <= stop: exit_px, reason = o, "gap_stop"
                elif l <= stop: exit_px, reason = stop, "stop"
            else:
                if o >= stop: exit_px, reason = o, "gap_stop"
                elif h >= stop: exit_px, reason = stop, "stop"
            if exit_px is not None:
                exit_i = j; break
        if exit_px is None:
            exit_i = len(g) - 1; exit_px = g.close.iloc[exit_i]; reason = "eod"
        gross = side * (exit_px / entry - 1.0)
        if cost_mode == "additive":
            net = gross - 2 * cost
        else:  # multiplicative: fee on entry notional and on exit notional
            if side == 1:
                net = (1 - cost) * (exit_px / entry) * (1 - cost) - 1
            else:
                net = (1 - cost) * (2 - exit_px / entry) - (exit_px / entry) * cost - 1 + 0  # proceeds model
        bars_in_pos += exit_i - e_i + 1
        trades.append(dict(date=str(dt), side=side, sig_t=str(g.t.iloc[sig_i]), entry_t=str(g.t.iloc[e_i]),
                           exit_t=str(g.t.iloc[exit_i]), H=H, L=L, entry=entry, exit=exit_px, reason=reason,
                           gross=gross, net=net))
    return pd.DataFrame(trades), skipped, bars_in_pos, total_bars

def metrics(tr, days, bars_in_pos, total_bars):
    eq = 1.0
    daily = {}
    pnl = []
    for r in tr.itertuples():
        p = eq * r.net
        pnl.append(p); eq += p
        daily[r.date] = eq
    s = pd.Series(1.0, index=[str(x) for x in days])
    cur = 1.0
    for k in s.index:
        if k in daily: cur = daily[k]
        s[k] = cur
    s = pd.concat([pd.Series([1.0], index=["start"]), s])
    dd = (s / s.cummax() - 1).min() * 100
    pnl = np.array(pnl)
    pf = pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()
    pf_ret = tr.net[tr.net > 0].sum() / -tr.net[tr.net < 0].sum()
    yrs = (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days / 365.25
    net = (eq - 1) * 100
    cagr = (eq ** (1 / yrs) - 1) * 100
    return dict(trades=len(tr), win_rate_pct=(tr.net > 0).mean() * 100, pf=pf, pf_on_returns=pf_ret,
                net_return_pct=net, cagr_pct=cagr, max_dd_pct=dd, exposure_pct=bars_in_pos / total_bars * 100,
                years=yrs)

days = sorted(df.date.unique())
tr, skipped, bip, tb = run(COST)
m = metrics(tr, days, bip, tb)
tr2, _, bip2, _ = run(2 * COST)
m2 = metrics(tr2, days, bip2, tb)
trm, _, _, _ = run(COST, "mult")
mm = metrics(trm, days, bip, tb)

# benchmark: buy at first session open, hold, sell at last session close; daily marks at session close; costs 1 entry + 1 exit
first_open = df[df.date == days[0]].sort_values("t").open.iloc[0]
closes = df.sort_values("t").groupby("date").close.last()
bench_eq = (closes / first_open) * (1 - COST)
bench_eq.iloc[-1] *= (1 - COST)
bser = pd.concat([pd.Series([1.0]), bench_eq.reset_index(drop=True)])
b_dd = (bser / bser.cummax() - 1).min() * 100
b_net = (bench_eq.iloc[-1] - 1) * 100
b_cagr = (bench_eq.iloc[-1] ** (1 / m["years"]) - 1) * 100

print("sha256 OK", sha)
print("days", len(days), days[0], days[-1], "skipped", skipped, "session bars", tb)
print("1x additive:", {k: round(v, 3) for k, v in m.items()})
print("1x multiplic:", {k: round(v, 3) for k, v in mm.items()})
print("2x additive:", {k: round(v, 3) for k, v in m2.items()})
print("bench: net %.3f cagr %.3f maxdd %.3f" % (b_net, b_cagr, b_dd))
print("exit reasons", tr.reason.value_counts().to_dict(), "sides", tr.side.value_counts().to_dict())
print("mean gross bps %.3f" % (tr.gross.mean() * 1e4))
for s_, gname in [(1, "long"), (-1, "short")]:
    t = tr[tr.side == s_]
    print(gname, len(t), "sum net %.4f" % t.net.sum(), "prod %.4f" % ((1 + t.net).prod() - 1))
tr["year"] = tr.date.str[:4]
print(tr.groupby("year").net.apply(lambda x: (1 + x).prod() - 1).round(4).to_dict())
# look-ahead self-checks
assert (pd.to_datetime(tr.entry_t) > pd.to_datetime(tr.sig_t)).all()
assert tr.date.is_unique
assert (pd.to_datetime(tr.exit_t, utc=True).dt.tz_convert("Europe/Berlin").dt.date.astype(str) == tr.date).all()
tr.to_csv(BASE + "/verify/trades_verify.csv", index=False)
json.dump(dict(m1=m, m2=m2, mm=mm, bench=dict(net=b_net, cagr=b_cagr, dd=b_dd)), open(BASE + "/verify/verify_out.json", "w"), indent=1, default=float)
