# Independent re-implementation of SPEC2 C2 FUNDING_OVERHEAT_FILTER.
# Written from SPEC2.md only (run.py / result.json of the other agent NOT read).
import json, hashlib, sys, math
from decimal import Decimal
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
FUND = DATA / "binance_fapi_fundingRate_BTCUSDT.json"
KL = DATA / "binance_spot_klines_BTCUSDT_1d.json"
EXPECTED = {
    FUND.name: "0233ed631f31ba460a1cc9a19909961e8e2ab1c1190a704c2a7a229588557d0f",
    KL.name: "1cebf2e8f9fc7f4c4a2558f4542a81de7d29daff0fc2ce689acdc0bb2f11016b",
}
for p in (FUND, KL):
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    assert h == EXPECTED[p.name], (p.name, h)
    print("sha256 OK", p.name)

H8 = 8 * 3600 * 1000
DAY = 24 * 3600 * 1000
HI = 30000  # 0.03% in 1e-8 units
LO = 10000  # 0.01% in 1e-8 units
LAST_DAY = pd.Timestamp("2026-10-06", tz="UTC")

# ---------------- funding ----------------
fr = json.load(open(FUND))
rows = []
for x in fr:
    assert x["symbol"] == "BTCUSDT"
    t = int(x["fundingTime"])
    slot = (t // H8) * H8  # jitter is only + a few ms (checked); floor to 8h slot
    assert t - slot < 1000, t
    q = Decimal(x["fundingRate"]) * Decimal(10**8)
    assert q == q.to_integral_value(), x["fundingRate"]
    rows.append((slot, t, int(q)))
f = pd.DataFrame(rows, columns=["slot", "raw", "r"]).sort_values("slot")
assert f.slot.is_unique
assert (f.slot.diff().dropna() == H8).all(), "non-8h gaps"
print("funding rows", len(f), pd.to_datetime(f.slot.min(), unit="ms", utc=True), pd.to_datetime(f.slot.max(), unit="ms", utc=True))

# ---------------- klines ----------------
kl = json.load(open(KL))
k = pd.DataFrame([(int(a[0]), float(a[1]), float(a[4]), int(a[6])) for a in kl], columns=["ot", "open", "close", "ct"])
k["date"] = pd.to_datetime(k.ot, unit="ms", utc=True)
assert (k.ot.diff().dropna() == DAY).all(), "kline gaps"
k = k[k.date <= LAST_DAY].reset_index(drop=True)
assert k.date.iloc[-1] == LAST_DAY
k = k.set_index("date")
print("klines", k.index[0].date(), k.index[-1].date(), len(k))


def build_signal(f, include_d0=False, use_float=False, cutoff_ms=None):
    """state[D] for each day D: True=BTC, False=USDT. Decision at 00:00 UTC of D using
    settlements with slot in [D-7d, D) (include_d0 shifts window to (D-7d, D] = look-ahead sensitivity)."""
    ff = f if cutoff_ms is None else f[f.raw < cutoff_ms]
    slots = ff.slot.values
    rates = ff.r.values
    cs = np.concatenate([[0], np.cumsum(rates)])
    first_day = (int(slots[0]) // DAY + 1) * DAY
    last_day = int(LAST_DAY.value // 10**6)
    if cutoff_ms is not None:
        last_day = min(last_day, (cutoff_ms // DAY) * DAY)
    days = np.arange(first_day, last_day + DAY, DAY)
    out = []
    state = True  # BTC by default
    lastslot_used = []
    for D in days:
        if include_d0:
            lo, hi = D - 7 * DAY + H8, D + H8  # (D-7d, D]
        else:
            lo, hi = D - 7 * DAY, D  # [D-7d, D)
        i0 = np.searchsorted(slots, lo, "left")
        i1 = np.searchsorted(slots, hi, "left")
        n = i1 - i0
        if n < 21:
            out.append((D, np.nan, None, n))
            continue
        assert n == 21
        s = cs[i1] - cs[i0]
        if use_float:
            m = sum(rates[i0:i1] * 1e-8) / 21
            over, under = m > 0.0003, m < 0.0001
        else:
            over, under = s > HI * 21, s < LO * 21
        if state and over:
            state = False
        elif (not state) and under:
            state = True
        out.append((D, s / 21 * 1e-8, state, n))
        lastslot_used.append((D, int(ff.raw.values[i1 - 1])))
    sig = pd.DataFrame(out, columns=["D", "mean", "btc", "n"])
    sig["date"] = pd.to_datetime(sig.D, unit="ms", utc=True)
    sig = sig.set_index("date")
    sig = sig[sig.btc.notna()]
    return sig, lastslot_used


sig, used = build_signal(f)
first_valid = sig.index[0]
print("first valid signal day", first_valid.date())
# look-ahead check: last raw funding timestamp used < decision/exec time (D 00:00)
assert all(raw < D for D, raw in used), "look-ahead in funding window"
print("look-ahead check: every used funding raw time < 00:00 of decision day: OK")


def simulate(start, end, sig, cost):
    """$1 USDT at start-day open; position for day D set at open D per sig; daily close marks;
    forced liquidation at end-day close."""
    px = k.loc[start:end]
    st = sig.btc.reindex(px.index)
    assert st.notna().all(), "signal missing in period"
    cash, units, inpos = 1.0, 0.0, False
    eq = [1.0]
    trades = []
    entry_cash = None
    entry_date = None
    exposure_days = 0
    for d, row in px.iterrows():
        want = bool(st.loc[d])
        if want and not inpos:
            entry_cash = cash
            entry_date = d
            units = cash * (1 - cost) / row.open
            cash = 0.0
            inpos = True
        elif (not want) and inpos:
            cash = units * row.open * (1 - cost)
            units = 0.0
            inpos = False
            trades.append((entry_date, d, "open", entry_cash, cash))
        if inpos:
            exposure_days += 1
        eq.append(cash + units * row.close)
    if inpos:
        cash = units * px.close.iloc[-1] * (1 - cost)
        trades.append((entry_date, px.index[-1], "close(forced)", entry_cash, cash))
        units = 0.0
        eq[-1] = cash
    eq = np.array(eq)
    return eq, trades, exposure_days / len(px), len(px)


def bench(start, end, cost):
    px = k.loc[start:end]
    units = (1 - cost) / px.open.iloc[0]
    eq = np.concatenate([[1.0], units * px.close.values])
    eq[-1] = units * px.close.iloc[-1] * (1 - cost)
    return eq


def mdd(eq):
    pk = np.maximum.accumulate(eq)
    return float((eq / pk - 1).min() * 100)


def metrics(start, end, sig, cost=0.002):
    eq, tr, expo, ndays = simulate(start, end, sig, cost)
    eq2, _, _, _ = simulate(start, end, sig, 2 * cost)
    b = bench(start, end, cost)
    yrs = ndays / 365.25
    pnl = [x[4] - x[3] for x in tr]
    rets = [x[4] / x[3] - 1 for x in tr]
    gw = sum(p for p in pnl if p > 0)
    gl = -sum(p for p in pnl if p < 0)
    gwr = sum(p for p in rets if p > 0)
    glr = -sum(p for p in rets if p < 0)
    R = eq[-1] - 1
    out = dict(
        trades=len(tr),
        win_rate_pct=round(100 * sum(p > 0 for p in pnl) / len(tr), 2) if tr else None,
        pf=round(gw / gl, 3) if gl > 0 else None,
        pf_pct_based=round(gwr / glr, 3) if glr > 0 else None,
        net_return_pct=round(100 * R, 2),
        cagr_pct=round(100 * ((1 + R) ** (1 / yrs) - 1), 2),
        max_dd_pct=round(mdd(eq), 2),
        exposure_pct=round(100 * expo, 2),
        net_return_2x_cost_pct=round(100 * (eq2[-1] - 1), 2),
        bench_net_return_pct=round(100 * (b[-1] - 1), 2),
        bench_max_dd_pct=round(mdd(b), 2),
        bench_cagr_pct=round(100 * (b[-1] ** (1 / yrs) - 1), 2),
        days=ndays,
    )
    out["ret_dd_ratio"] = round(out["net_return_pct"] / abs(out["max_dd_pct"]), 3)
    out["bench_ret_dd_ratio"] = round(out["bench_net_return_pct"] / abs(out["bench_max_dd_pct"]), 3)
    return out, tr, eq


PER = {
    "IS": (first_valid, pd.Timestamp("2022-12-31", tz="UTC")),
    "OOS": (pd.Timestamp("2023-01-01", tz="UTC"), LAST_DAY),
    "FULL": (first_valid, LAST_DAY),
}
results = {}
for name, (s, e) in PER.items():
    m, tr, eq = metrics(s, e, sig)
    results[name] = m
    print(f"\n== {name} {s.date()}..{e.date()} ==")
    print(json.dumps(m, ensure_ascii=False))
    for t in tr:
        print("   trade", t[0].date(), "->", t[1].date(), t[2], f"{100*(t[4]/t[3]-1):+.2f}%", f"pnl$={t[4]-t[3]:+.4f}")

# switches
sw = sig.btc.astype(int).diff().fillna(0)
print("\nswitches (date, new state, 7d mean %):")
for d in sig.index[sw != 0]:
    print("  ", d.date(), "BTC" if sig.btc.loc[d] else "USDT", f"{sig['mean'].loc[d]*100:.4f}%")
print("current state on", sig.index[-1].date(), "BTC" if sig.btc.iloc[-1] else "USDT", f"mean={sig['mean'].iloc[-1]*100:.4f}%")

# OOS drawdown dates
eqo = metrics(*PER["OOS"], sig)[2]
idx = [PER["OOS"][0] - pd.Timedelta(days=1)] + list(k.loc[PER["OOS"][0]:PER["OOS"][1]].index)
pk = np.maximum.accumulate(eqo)
dd = eqo / pk - 1
it = int(dd.argmin()); ip = int(np.argmax(eqo[: it + 1]))
print("OOS DD peak", idx[ip].date(), "trough", idx[it].date(), f"{dd[it]*100:.2f}%")

# ---------------- truncation (look-ahead) test ----------------
rng = np.random.default_rng(7)
cut_days = rng.choice(sig.index[30:], 8, replace=False)
ok = True
for cd in cut_days:
    cms = int(pd.Timestamp(cd).value // 10**6)  # cutoff at 00:00 of cd: only funding raw < cutoff
    s2, _ = build_signal(f, cutoff_ms=cms)
    common = s2.index.intersection(sig.index)
    common = common[common <= cd]
    if not (s2.btc.loc[common] == sig.btc.loc[common]).all():
        ok = False
        print("TRUNCATION MISMATCH at", cd)
print("truncation test:", "OK" if ok else "FAIL")

# ---------------- sensitivity (NOT the spec result) ----------------
print("\n--- sensitivity (diagnostic only) ---")
for lab, kw in [("float compare", dict(use_float=True)), ("include 00:00 D settlement (look-ahead-ish)", dict(include_d0=True))]:
    s3, _ = build_signal(f, **kw)
    for name, (s, e) in PER.items():
        s_ = max(s, s3.index[0])
        m, tr, _ = metrics(s_, e, s3)
        print(lab, name, m["trades"], m["net_return_pct"], m["max_dd_pct"])

json.dump(results, open(Path(__file__).resolve().parent / "verify_result.json", "w"), ensure_ascii=False, indent=1)
