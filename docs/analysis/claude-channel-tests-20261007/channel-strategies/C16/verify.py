# Independent re-implementation of C16 AAVE_V3_USDC per SPEC2.md (frozen). Does not read run.py/result.json.
import json, hashlib, os, math
import numpy as np, pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
EXP = {"chart_aa70268e.json": "4af1d137f1917eb1705a8cc5955fa65b8932722f4fe65a375277f267c9d1e8a3",
       "pools.json": "90030a369feed818cb411c0054bd7e6fdeed1ca3dd57ff0c13d77a9faf18fdb7",
       "binance_USDCUSDT_1d.json": "b51fcdf75fd4d779a05848fe67fe184c8989ad2a78f8bedc664df92d70ea194b"}
for f, h in EXP.items():
    got = hashlib.sha256(open(os.path.join(BASE, f), "rb").read()).hexdigest()
    assert got == h, (f, got)
print("sha256 OK")

# --- pool identification (independent) ---
pools = json.load(open(os.path.join(BASE, "pools.json"), encoding="utf-8"))["data"]
cand = [p for p in pools if p["project"] == "aave-v3" and p["chain"] == "Ethereum" and p["symbol"] == "USDC"
        and (p.get("underlyingTokens") or [""])[0].lower() == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        and not p.get("poolMeta")]
assert len(cand) == 1 and cand[0]["pool"] == "aa70268e-4b52-42bf-a116-608b370f9501", cand
print("pool:", cand[0]["pool"])

# --- APY history ---
raw = json.load(open(os.path.join(BASE, "chart_aa70268e.json"), encoding="utf-8"))
df = pd.DataFrame(raw["data"])
df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values("ts").reset_index(drop=True)
CUT = pd.Timestamp("2026-10-06 23:59:59", tz="UTC")
n_all = len(df)
df = df[df["ts"] <= CUT].reset_index(drop=True)
print("rows all", n_all, "used", len(df), "first", df.ts.iloc[0], "last", df.ts.iloc[-1])
assert df["ts"].is_monotonic_increasing and df["ts"].dt.date.duplicated().sum() == 0
print("apyReward non-null:", df["apyReward"].notna().sum(), " apy==apyBase all:", np.allclose(df.apy, df.apyBase.fillna(df.apy)))
dt_days = df["ts"].diff().dt.total_seconds().div(86400)
print("gaps >1.2d:", [(str(df.ts[i].date()), round(dt_days[i], 2)) for i in dt_days.index if dt_days[i] > 1.2])
assert df["apy"].notna().all()

apy = df["apy"].to_numpy() / 100.0
t = df["ts"]
d = dt_days.to_numpy()[1:]           # length n-1, interval (t_i, t_{i+1}]
# causal: rate observed at t_i applied to interval (t_i, t_{i+1}]
g_causal = (1 + apy[:-1]) ** (d / 365.0)
g_look = (1 + apy[1:]) ** (d / 365.0)  # diagnostic look-ahead variant
gross_c = np.prod(g_causal) - 1
gross_l = np.prod(g_look) - 1
span_days = (t.iloc[-1] - t.iloc[0]).total_seconds() / 86400
years = span_days / 365.25
print(f"span {span_days:.3f} d = {years:.4f} y; gross causal {gross_c*100:.4f}%  lookahead {gross_l*100:.4f}%")
print(f"gross CAGR {( (1+gross_c)**(1/years)-1)*100:.3f}%")

def run(C, gas_rt):
    half = gas_rt / 2.0
    E = C - half                    # deposited principal after entry gas
    marks = [C]                     # pre-deposit cash mark
    times = [t.iloc[0]]
    marks.append(E - half); times.append(t.iloc[0])   # liquidation value right after deposit
    for i in range(len(d)):
        E *= g_causal[i]
        marks.append(E - half); times.append(t.iloc[i + 1])
    final = E - half
    m = np.array(marks)
    dd = (m / np.maximum.accumulate(m) - 1).min()
    net = final / C - 1
    cagr = (final / C) ** (1 / years) - 1
    interest = E - (C - half)
    incr = np.diff(m)
    pf_daily = incr[incr > 0].sum() / -incr[incr < 0].sum() if (incr < 0).any() else float("inf")
    return dict(final=final, net=net * 100, cagr=cagr * 100, dd=dd * 100, interest=interest, pf_daily=pf_daily,
                cagr365=((final / C) ** (365 / span_days) - 1) * 100)

res = {}
for C in (100.0, 10000.0):
    r1 = run(C, 5.0); r2 = run(C, 10.0)
    res[C] = (r1, r2)
    print(f"C={C:>8}: final {r1['final']:.2f} net {r1['net']:.3f}% CAGR {r1['cagr']:.3f}% (365-basis {r1['cagr365']:.3f}%) "
          f"maxDD {r1['dd']:.3f}% interest {r1['interest']:.2f} PF_daily {r1['pf_daily']:.2f} | 2x gas net {r2['net']:.3f}% CAGR {r2['cagr']:.3f}% DD {r2['dd']:.3f}%")
    # alternative gas placement: whole $5 at exit
    alt = (C * (1 + gross_c) - 5) / C - 1
    print(f"   alt (all gas at exit) net {alt*100:.3f}% CAGR {((1+alt)**(1/years)-1)*100:.3f}%")

# --- APY diagnostics ---
a = df["apy"].to_numpy()
drop = np.diff(a)
k = int(np.argmin(drop))
print(f"max single-step APY drop {drop[k]:.2f} pp: {a[k]:.2f}% ({t[k].date()}) -> {a[k+1]:.2f}% ({t[k+1].date()}), dt {d[k]:.2f} d, tvl {df.tvlUsd[k+1]:,.0f}")
low = df[df.apy < 1.0]
print("days APY<1%:", [(str(x.date()), round(y, 3)) for x, y in zip(low.ts, low.apy)])
print(f"APY mean {a.mean():.3f} median {np.median(a):.3f} max {a.max():.3f} min {a.min():.3f}")
# per-year realised (causal) growth
yr = t.iloc[:-1].dt.year.to_numpy()
for y in sorted(set(yr)):
    msk = yr == y
    gy = np.prod(g_causal[msk]); dy = d[msk].sum()
    print(f"  {y}: growth {(gy-1)*100:.3f}% over {dy:.1f} d -> annualised {(gy**(365.25/dy)-1)*100:.3f}%")
last365 = t.iloc[:-1] >= t.iloc[-1] - pd.Timedelta(days=365)
gy = np.prod(g_causal[last365.to_numpy()]); dy = d[last365.to_numpy()].sum()
print(f"  last 365d: annualised {(gy**(365.25/dy)-1)*100:.3f}%")
cap = np.minimum(apy, 0.15)
gc = np.prod((1 + cap[:-1]) ** (d / 365.0))
print(f"  diag: APY capped at 15% -> gross CAGR {(gc**(1/years)-1)*100:.3f}%")
print("min tvlUsd (available liquidity):", f"{df.tvlUsd.min():,.0f}", df.ts[df.tvlUsd.idxmin()].date())

# --- depeg diagnostic: mark USDC in USDT ---
k = json.load(open(os.path.join(BASE, "binance_USDCUSDT_1d.json")))
bz = pd.DataFrame(k).iloc[:, [0, 4]]; bz.columns = ["ot", "close"]
bz["date"] = pd.to_datetime(bz.ot, unit="ms", utc=True).dt.date; bz["close"] = bz.close.astype(float)
px = bz.set_index("date")["close"]
for C in (100.0, 10000.0):
    half = 2.5; E = C - half; marks = [C]
    p0 = px.get(t.iloc[0].date(), 1.0)
    vals = [(E - half) * p0]
    for i in range(len(d)):
        E *= g_causal[i]
        p = px.get(t.iloc[i + 1].date(), 1.0)
        vals.append((E - half) * p)
    m = np.array(marks + vals)
    print(f"  USDT-marked maxDD C={C}: {(m/np.maximum.accumulate(m)-1).min()*100:.3f}%  min close {px.min()} on {px.idxmin()}")

out = {C: {"x1": res[C][0], "x2": res[C][1]} for C in res}
json.dump({str(k_): v for k_, v in out.items()}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_out.json"), "w"), indent=1, default=float)
