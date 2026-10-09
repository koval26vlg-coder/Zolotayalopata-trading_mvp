# Independent re-implementation of C5 FEAR_GREED_CONTRARIAN from SPEC2.md
import json, hashlib, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "data")
EXP = {"fng.json": "9d8d256b208a3b64bd49c66d10fa8a373877171d8a46132d734a9f1e85145575",
       "btcusdt_1d_part0.json": "66c6c45e9f3b6a5e25a1f3391cba9499f745704b91a211f4675717b51f8d95d2",
       "btcusdt_1d_part1.json": "c45eb665553d0312afa49f9456a49335ebcd4e66ab3847226f070a8de1e3f5f0",
       "btcusdt_1d_part2.json": "9c307a25f0bdf94370fe448fc0686534c26af79200218e5671c38b2292c72794",
       "btcusdt_1d_part3.json": "2c22d8825e3d98b3446e52db5a500ae5739e5668a131a571ac6493ed21fff0ee"}
for f, h in EXP.items():
    got = hashlib.sha256(open(os.path.join(D, f), "rb").read()).hexdigest()
    assert got == h, (f, got)
print("sha256 OK")

LAST = pd.Timestamp("2026-10-06")
# ---- FGI
fj = json.load(open(os.path.join(D, "fng.json")))["data"]
fg = pd.Series({pd.Timestamp(int(r["timestamp"]), unit="s"): int(r["value"]) for r in fj}).sort_index()
assert all(t.hour == 0 and t.minute == 0 for t in fg.index)
assert not fg.index.duplicated().any()
print("FGI", fg.index.min().date(), fg.index.max().date(), len(fg))
full = pd.date_range(fg.index.min(), fg.index.max(), freq="D")
print("FGI missing days:", [str(d.date()) for d in full.difference(fg.index)])
fg = fg[fg.index <= LAST]  # value dated 2026-10-07 excluded (published after cutoff)

# ---- klines
rows = []
for i in range(4):
    rows += json.load(open(os.path.join(D, f"btcusdt_1d_part{i}.json")))
k = pd.DataFrame(rows).iloc[:, :7]
k.columns = ["ot", "o", "h", "l", "c", "v", "ct"]
k["date"] = pd.to_datetime(k.ot, unit="ms")
k = k.set_index("date")[["o", "h", "l", "c", "ct"]].astype(float)
assert not k.index.duplicated().any()
assert all(t.hour == 0 for t in k.index)
kr = pd.date_range(k.index.min(), k.index.max(), freq="D")
print("klines", k.index.min().date(), k.index.max().date(), len(k), "missing:", [str(d.date()) for d in kr.difference(k.index)])
assert k.index.max() == LAST
assert pd.Timestamp(int(k.ct.iloc[-1]), unit="ms") <= pd.Timestamp("2026-10-06 23:59:59.999")
k = k.reindex(kr)
assert k.o.notna().all(), "missing kline days"


def simulate(start, end, cost):
    """FGI dated D (published ~00:00 UTC of D). Action executes at open of D+1.
    Start in USDT at `start`. Open position force-closed at `end` close (with cost)."""
    days = pd.date_range(start, end, freq="D")
    cash = 1.0; qty = 0.0
    trades = []; eq = []; held = []
    entry = None
    for d in days:
        o = k.at[d, "o"]; c = k.at[d, "c"]
        sig_day = d - pd.Timedelta(days=1)
        v = fg.get(sig_day, None)
        if v is not None:
            if qty == 0 and v <= 20:
                entry = dict(sig=sig_day, date=d, px=o, fgi=int(v), eq_in=cash)
                qty = cash * (1 - cost) / o; cash = 0.0
            elif qty > 0 and v >= 80:
                cash = qty * o * (1 - cost); qty = 0.0
                trades.append(dict(**entry, exit_date=d, exit_px=o, exit_sig=sig_day, exit_fgi=int(v), eq_out=cash, forced=False))
                entry = None
        held.append(qty > 0)
        eq.append(cash + qty * c)
    if qty > 0:
        c = k.at[days[-1], "c"]
        cash = qty * c * (1 - cost); qty = 0.0
        trades.append(dict(**entry, exit_date=days[-1], exit_px=c, exit_sig=None, exit_fgi=None, eq_out=cash, forced=True))
        eq[-1] = cash
    return pd.Series(eq, index=days), trades, np.array(held)


def bench(start, end, cost):
    days = pd.date_range(start, end, freq="D")
    q = (1 - cost) / k.at[days[0], "o"]
    eq = q * k.loc[days, "c"].values
    eq[-1] = eq[-1] * (1 - cost)
    return pd.Series(eq, index=days)


def maxdd(eqs, init=1.0):
    s = np.concatenate([[init], np.asarray(eqs)])
    pk = np.maximum.accumulate(s)
    return (s / pk - 1).min() * 100


def metrics(eqs, trades, held):
    n = len(eqs); yrs = n / 365.25
    fin = eqs.iloc[-1]
    pnl = [t["eq_out"] - t["eq_in"] for t in trades]
    gw = sum(p for p in pnl if p > 0); gl = -sum(p for p in pnl if p < 0)
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else None)
    return dict(trades=len(trades), win_rate_pct=(100 * np.mean([p > 0 for p in pnl]) if pnl else None),
                pf=pf, net_return_pct=(fin - 1) * 100, cagr_pct=(fin ** (1 / yrs) - 1) * 100,
                max_dd_pct=maxdd(eqs), exposure_pct=100 * held.mean())


C = 0.002
P = {"IS": ("2018-02-01", "2022-12-31"), "OOS": ("2023-01-01", "2026-10-06"), "FULL": ("2018-02-01", "2026-10-06")}
out = {}
for name, (s, e) in P.items():
    eqs, tr, held = simulate(s, e, C)
    m = metrics(eqs, tr, held)
    eqs2, _, _ = simulate(s, e, 2 * C)
    m["net_return_2x_cost_pct"] = (eqs2.iloc[-1] - 1) * 100
    b = bench(s, e, C)
    m["bench_net_return_pct"] = (b.iloc[-1] - 1) * 100
    m["bench_max_dd_pct"] = maxdd(b)
    m["bench_cagr_pct"] = (b.iloc[-1] ** (365.25 / len(b)) - 1) * 100
    m["bench_ret_dd"] = m["bench_net_return_pct"] / abs(m["bench_max_dd_pct"])
    m["ret_dd"] = m["net_return_pct"] / abs(m["max_dd_pct"])
    m["dd_diff_vs_bench"] = m["max_dd_pct"] - m["bench_max_dd_pct"]
    out[name] = m
    print("\n==", name, s, e)
    for kk, vv in m.items():
        print(f"  {kk}: {vv}")
    for t in tr:
        r = (t['eq_out'] / t['eq_in'] - 1) * 100
        ex = 'FORCED' if t['forced'] else f"sig {t['exit_sig'].date()} fgi={t['exit_fgi']}"
        print(f"   sig {t['sig'].date()} fgi={t['fgi']} BUY {t['date'].date()} @{t['px']:.2f} -> {ex} SELL {t['exit_date'].date()} @{t['exit_px']:.2f}  ret {r:.2f}%")
    # where does max DD occur (strategy vs bench)
    s_ = eqs.values; pk = np.maximum.accumulate(np.concatenate([[1.0], s_]))[1:]
    i = np.argmin(s_ / pk - 1)
    bs = b.values; bpk = np.maximum.accumulate(np.concatenate([[1.0], bs]))[1:]
    j = np.argmin(bs / bpk - 1)
    print(f"  strat DD trough {eqs.index[i].date()}  bench DD trough {b.index[j].date()}")

# ---- look-ahead / consistency checks
eqs, tr, held = simulate("2018-02-01", "2026-10-06", C)
for t in tr:
    assert t["date"] - t["sig"] == pd.Timedelta(days=1) and fg[t["sig"]] <= 20
    if not t["forced"]:
        assert t["exit_date"] - t["exit_sig"] == pd.Timedelta(days=1) and fg[t["exit_sig"]] >= 80
prod = np.prod([t['eq_out'] / t['eq_in'] for t in tr]); assert abs(prod - eqs.iloc[-1]) < 1e-9
rng = np.random.default_rng(0)
fg0 = fg.copy(); k0 = k.copy()
for X in pd.to_datetime(rng.choice(pd.date_range("2018-03-01", "2026-09-01").values, 25)):
    fg_s = fg0.copy(); m_ = fg_s.index >= X; fg_s[m_] = rng.integers(0, 101, m_.sum())
    k_s = k0.copy(); m2 = k_s.index > X
    k_s.loc[m2, ["o", "h", "l", "c"]] = k_s.loc[m2, ["o", "h", "l", "c"]].values * rng.uniform(0.5, 1.5, (m2.sum(), 1))
    fg, k = fg_s, k_s
    e2, _, _ = simulate("2018-02-01", "2026-10-06", C)
    fg, k = fg0, k0
    assert abs(e2[X] - eqs[X]) < 1e-12, X
print("\nlook-ahead checks OK (signal-date lag, product of trades, 25 truncation-scramble tests)")

print("FGI 2022-12-31:", fg.get(pd.Timestamp("2022-12-31")))
e_prev = eqs[pd.Timestamp("2022-12-31")]
eo = eqs["2023-01-01":]
print("continuous-run OOS slice return %:", (eo.iloc[-1] / e_prev - 1) * 100, " maxDD %:", maxdd(eo / e_prev))
e2x, _, _ = simulate("2018-02-01", "2026-10-06", 2 * C)
print("continuous-run OOS slice 2x cost return %:", (e2x.iloc[-1] / e2x[pd.Timestamp('2022-12-31')] - 1) * 100)
print("OOS FGI min 2023-01-01..2024-08-06:", fg["2023-01-01":"2024-08-06"].min())
print("FGI max since 2025-02-28:", fg["2025-02-28":].max(), fg["2025-02-28":].idxmax().date())
print("FGI last used:", fg.index[-1].date(), fg.iloc[-1])


def clean(v):
    if isinstance(v, (float, np.floating)) and not np.isfinite(v):
        return None
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


json.dump({p: {a: clean(b_) for a, b_ in v.items()} for p, v in out.items()},
          open(os.path.join(HERE, "verify_result.json"), "w"), indent=1)
