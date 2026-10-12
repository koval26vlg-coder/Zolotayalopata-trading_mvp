# C16 AAVE_V3_USDC (SPEC2, frozen 2026-10-07)
# Data: DefiLlama yields API, pool aa70268e-4b52-42bf-a116-608b370f9501 (aave-v3, Ethereum, USDC, core market)
# Rule: deposit USDC once at first snapshot, hold, withdraw at last usable snapshot (<= 2026-10-06 23:59 UTC).
# Interest accrues causally: APY observed at snapshot t_i is applied to interval (t_i, t_{i+1}].
# Costs: gas $5 per round trip (1x), $10 (2x stress); split half at deposit, half at withdrawal.
# Equity marks = liquidation value (balance minus the still-unpaid withdrawal gas).
import json, hashlib, os
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
POOL = "aa70268e-4b52-42bf-a116-608b370f9501"
CUTOFF = pd.Timestamp("2026-10-06 23:59:59", tz="UTC")
OOS_START = pd.Timestamp("2023-01-01", tz="UTC")
GAS_1X = 5.0
CAPITALS = [100.0, 10000.0]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---------- pool identification (from pools snapshot) ----------
pools = json.load(open(os.path.join(DATA, "pools.json"), encoding="utf-8"))["data"]
cand = [p for p in pools if p["project"] == "aave-v3" and p["chain"] == "Ethereum"
        and p["symbol"].upper() == "USDC" and not p.get("poolMeta")]
assert len(cand) == 1 and cand[0]["pool"] == POOL, cand
assert cand[0]["underlyingTokens"] == ["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"]  # native USDC

# ---------- APY history ----------
raw = json.load(open(os.path.join(DATA, f"chart_{POOL[:8]}.json")))
assert raw["status"] == "success"
df = pd.DataFrame(raw["data"])
df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
n_raw = len(df)
df = df[df["ts"] <= CUTOFF].reset_index(drop=True)
df["apy"] = df["apy"].astype(float)
df["tvlUsd"] = df["tvlUsd"].astype(float)
assert df["apyReward"].isna().all() or (df["apyReward"].fillna(0) == 0).all()  # no reward token income

t = df["ts"].values
apy = df["apy"].values / 100.0
dt_days = np.diff(t).astype("timedelta64[s]").astype(float) / 86400.0
assert (dt_days > 0).all()

# causal growth: interval i uses APY observed at t_i (start of interval), never t_{i+1}
idx_rate = np.arange(len(dt_days))          # index of APY used for interval i
idx_start = np.arange(len(dt_days))         # index of interval start
assert (t[idx_rate] <= t[idx_start]).all(), "look-ahead: rate observed after interval start"
growth = (1.0 + apy[idx_rate]) ** (dt_days / 365.0)
# diagnostic only: look-ahead version (rate from end of interval) to show sensitivity of the convention
growth_lookahead = (1.0 + apy[1:]) ** (dt_days / 365.0)

days_total = (t[-1] - t[0]).astype("timedelta64[s]").astype(float) / 86400.0
years = days_total / 365.0
gross_mult = float(np.prod(growth))
gross_mult_la = float(np.prod(growth_lookahead))


def run(capital, gas):
    half = gas / 2.0
    bal = np.empty(len(t))
    bal[0] = capital - half                  # deposit gas paid at entry
    bal[1:] = bal[0] * np.cumprod(growth)
    liq = bal - half                         # liquidation value (exit gas still to pay)
    final = float(liq[-1])
    eq = np.concatenate([[capital], liq])    # mark before deposit = capital
    peak = np.maximum.accumulate(eq)
    dd = float(((eq - peak) / peak).min())
    pnl = np.diff(eq)
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = float(wins / losses) if losses > 0 else None
    net = final / capital - 1.0
    cagr = (final / capital) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return dict(final=final, net_pct=100 * net, cagr_pct=100 * cagr, maxdd_pct=100 * dd, pf=pf,
                interest_usd=float(bal[-1] - bal[0]), gas_usd=gas, eq=eq)


results = {}
for C in CAPITALS:
    r1 = run(C, GAS_1X)
    r2 = run(C, 2 * GAS_1X)
    results[C] = (r1, r2)

# ---------- APY diagnostics ----------
d_apy = np.diff(df["apy"].values)            # percentage points, day over day
i_drop = int(np.argmin(d_apy))
max_drop = dict(pp=float(-d_apy[i_drop]), from_ts=str(df["ts"][i_drop]), to_ts=str(df["ts"][i_drop + 1]),
                from_apy=float(df["apy"][i_drop]), to_apy=float(df["apy"][i_drop + 1]))
# max drop excluding the obvious one-snapshot spike? (reported as-is, no filtering)
low = df[df["apy"] < 1.0][["timestamp", "apy"]]
low_list = [dict(ts=r.timestamp, apy=round(r.apy, 4)) for r in low.itertuples()]
liq_low = df[df["tvlUsd"] < 1e6][["timestamp", "apy", "tvlUsd"]]
liq_list = [dict(ts=r.timestamp, apy=round(r.apy, 3), available_liquidity_usd=r.tvlUsd) for r in liq_low.itertuples()]
gaps = [dict(after=str(df["ts"][i]), days=round(float(dt_days[i]), 3)) for i in np.where(dt_days > 1.4)[0]]

apy_stats = dict(mean=float(df["apy"].mean()), median=float(df["apy"].median()), min=float(df["apy"].min()),
                 max=float(df["apy"].max()), last=float(df["apy"].iloc[-1]),
                 by_year={str(k): round(float(v), 3) for k, v in df.groupby(df["ts"].dt.year)["apy"].mean().items()})
gross_cagr = gross_mult ** (1 / years) - 1

# decomposition (diagnostic, not a variant): annualised gross yield per calendar year of interval start
yr = df["ts"].dt.year.values[:-1]
by_year_ann = {}
for y in np.unique(yr):
    m = yr == y
    by_year_ann[str(y)] = round(100 * (np.prod(growth[m]) ** (365.0 / dt_days[m].sum()) - 1), 3)
# last 365 days (diagnostic)
t_last = t[-1] - np.timedelta64(365, "D")
m = t[:-1] >= t_last
ttm_ann = 100 * (np.prod(growth[m]) ** (365.0 / dt_days[m].sum()) - 1)
# contribution of APY spikes > 15% (diagnostic only: share of total gross log-growth)
lg = np.log(growth)
spike_share = float(lg[apy[:-1] > 0.15].sum() / lg.sum())
gross_cagr_ex_spikes = float(np.exp(lg[apy[:-1] <= 0.15].sum() / years) - 1)

# ---------- DIAGNOSTIC (not a variant, verdict unaffected): USDC marked in USDT ----------
# Binance USDCUSDT daily klines (pair relisted 2023-03-11 = depeg day). Before first kline USDC assumed = 1.0.
# Each APY snapshot (~23:00 UTC) is marked at the same-UTC-date daily close (close at 23:59:59, i.e. <= ~1h later;
# mark only, no decision uses it).
kl = json.load(open(os.path.join(DATA, "binance_USDCUSDT_1d.json")))
px = pd.Series({pd.Timestamp(k[0], unit="ms", tz="UTC").date(): float(k[4]) for k in kl})
px_low = pd.Series({pd.Timestamp(k[0], unit="ms", tz="UTC").date(): float(k[3]) for k in kl})
snap_dates = df["ts"].dt.date
mark = snap_dates.map(px).astype(float)
mark[snap_dates < px.index.min()] = 1.0
mark = mark.ffill().values
usd_diag = {}
for C in CAPITALS:
    half = GAS_1X / 2
    bal = np.empty(len(t)); bal[0] = C - half; bal[1:] = bal[0] * np.cumprod(growth)
    eq = np.concatenate([[C], bal * mark - half])
    peak = np.maximum.accumulate(eq)
    usd_diag[str(int(C))] = dict(maxdd_pct_usdt_marked_daily_close=float(100 * ((eq - peak) / peak).min()),
                                 final_usdt=float(eq[-1]), net_pct_usdt=float(100 * (eq[-1] / C - 1)))
usd_diag["usdc_min_daily_close"] = dict(date=str(px.idxmin()), close=float(px.min()))
usd_diag["usdc_min_intraday_low"] = dict(date=str(px_low.idxmin()), low=float(px_low.min()))
usd_diag["note"] = "USDC==1.0 assumed before 2023-03-11 (no Binance pair); USDT used as USD proxy"

# ---------- DIAGNOSTIC: $100 economics over a 1-year hold at last-365d realised rate ----------
g365 = float(np.prod(growth[m]))
one_year_100 = (100 - GAS_1X / 2) * g365 - GAS_1X / 2
breakeven_years_100 = float(np.log((100 + GAS_1X / 2) / (100 - GAS_1X / 2)) / np.log(1 + ttm_ann / 100))  # (100-2.5)g^y-2.5=100
breakeven_years_100_full = float(np.log((100 + GAS_1X / 2) / (100 - GAS_1X / 2)) / np.log(1 + gross_cagr))

# ---------- verdict (pre-registered, carry/yield branch, FULL because data starts after 2022) ----------
def verdict(r1, r2):
    bench_ret, bench_dd = 0.0, 0.0
    worse_both = (r1["net_pct"] <= bench_ret) and (abs(r1["maxdd_pct"]) >= abs(bench_dd))
    fail = r1["net_pct"] <= 0 or (r1["pf"] is not None and r1["pf"] < 1.0) or worse_both
    if fail:
        return "FAIL", "net<=0 or PF<1 or worse than cash on both"
    ratio = r1["cagr_pct"] / abs(r1["maxdd_pct"]) if r1["maxdd_pct"] != 0 else float("inf")
    bench_ratio = 0.0  # cash: 0 return; ratio defined as 0
    conds = dict(net_pos=bool(r1["net_pct"] > 0), ann_gt_4=bool(r1["cagr_pct"] > 4.0),
                 dd_lt_10=bool(abs(r1["maxdd_pct"]) < 10.0), beats_ratio=bool(ratio > bench_ratio),
                 pos_2x=bool(r2["net_pct"] > 0))
    if all(conds.values()):
        return "PASS_CANDIDATE", conds
    return "INCONCLUSIVE", conds  # not FAIL, not PASS: residual (yield criteria unmet)


verdicts = {C: verdict(*results[C]) for C in CAPITALS}

out = dict(
    id="C16", pool=POOL, data_start=str(df["ts"].iloc[0]), data_end=str(df["ts"].iloc[-1]),
    n_snapshots_used=len(df), n_snapshots_raw=n_raw, days=round(days_total, 2), years=round(years, 4),
    periods_note="Data start 2023-02-06 > 2022 -> FULL only (whole sample lies inside the OOS window)",
    gross_compound_return_pct=100 * (gross_mult - 1), gross_cagr_pct=100 * gross_cagr,
    lookahead_diag_gross_return_pct=100 * (gross_mult_la - 1),
    apy_stats=apy_stats, gross_ann_by_year_pct=by_year_ann, gross_ann_last365d_pct=ttm_ann,
    spike_gt15_share_of_gross_growth=spike_share, diag_gross_cagr_if_spike_days_earn_zero_pct=100 * gross_cagr_ex_spikes, max_single_day_apy_drop=max_drop, days_apy_below_1pct=low_list,
    low_available_liquidity_days=liq_list,
    diag_usdt_marked=usd_diag, diag_100usd_1y_hold_last365d_final=one_year_100,
    diag_100usd_breakeven_years_at_last365d_rate=breakeven_years_100,
    diag_100usd_breakeven_years_at_full_cagr=breakeven_years_100_full, snapshot_gaps_gt_1_4d=gaps,
    results={str(int(C)): dict(
        x1={k: v for k, v in results[C][0].items() if k != "eq"},
        x2={k: v for k, v in results[C][1].items() if k != "eq"},
        verdict=verdicts[C][0], verdict_conds=verdicts[C][1]) for C in CAPITALS},
    combined_verdict=dict(
        verdict=verdicts[10000.0][0],
        basis="research math = $10,000 sleeve (fixed gas negligible); $100 reported separately as feasibility",
        per_capital={str(int(C)): verdicts[C][0] for C in CAPITALS}),
    self_checks=dict(rate_observed_at_or_before_interval_start=True, cutoff_applied=str(CUTOFF),
                     dropped_after_cutoff=n_raw - len(df)),
    sha256={f: sha(os.path.join(DATA, f)) for f in sorted(os.listdir(DATA))},
)
json.dump(out, open(os.path.join(BASE, "result.json"), "w"), indent=2, default=str)
print(json.dumps(out, indent=2, default=str))
