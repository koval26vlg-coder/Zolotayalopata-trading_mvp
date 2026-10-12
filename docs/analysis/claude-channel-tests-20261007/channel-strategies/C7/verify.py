# Independent re-implementation of C7 TREND_PULLBACK_4H from SPEC2.md (frozen).
# Does NOT import or read ../run.py or ../result.json.
import json, hashlib, sys
import numpy as np
import pandas as pd

BASE = "C:/Users/koval/AppData/Local/Temp/claude/C--Users-koval------------/c3d42fa1-b83c-49f0-8567-13ebcd1f7317/scratchpad/st/C7"
DATA = BASE + "/data"
OUT = BASE + "/verify"

EXPECTED_SHA = {
    "BTCUSDT_4h.json": "0f4ca7b36651d2efc70e09c12b321473c7b3dcebeae04ad553b53152c4d6bdbc",
    "ETHUSDT_4h.json": "5ae26c322c24312ce49c25d8748efd7b4ba5c147751166b6771b180bbbacba38",
    "SOLUSDT_4h.json": "d019b46a477d1b7f82890728aed0d5e99f4f713988a7705c8376e5dbc986f0be",
    "exchangeInfo.json": "7204daddcd5f0554b5159e42f48c373506f74c64d7c2a3b3ad888d4f62278960",
}
for fn, h in EXPECTED_SHA.items():
    got = hashlib.sha256(open(f"{DATA}/{fn}", "rb").read()).hexdigest()
    assert got == h, (fn, got)

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CUTOFF_MS = int(pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC").value // 10**6)
COST = 0.0020           # 20 bps per side
RISK = 0.01
RR = 2.0
LOOKBACK_STOP = 10
WARMUP = 200            # bars of history required (incl. signal bar) before a signal is allowed
SLEEVE0 = 100.0 / 3.0

IS_START = pd.Timestamp("2017-08-17 00:00", tz="UTC")   # "data start"
IS_END = pd.Timestamp("2022-12-31 23:59:59.999", tz="UTC")
OOS_START = pd.Timestamp("2023-01-01 00:00", tz="UTC")
OOS_END = pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC")
PERIODS = {"IS": (IS_START, IS_END), "OOS": (OOS_START, OOS_END), "FULL": (IS_START, OOS_END)}


def load(sym):
    raw = json.load(open(f"{DATA}/{sym}_4h.json"))
    df = pd.DataFrame([r[:7] for r in raw], columns=["ot", "o", "h", "l", "c", "v", "ct"])
    for k in ["o", "h", "l", "c", "v"]:
        df[k] = df[k].astype(float)
    df = df[df["ct"] <= CUTOFF_MS].drop_duplicates("ot").sort_values("ot").reset_index(drop=True)
    df["t"] = pd.to_datetime(df["ot"], unit="ms", utc=True)
    df["tc"] = pd.to_datetime(df["ct"], unit="ms", utc=True)
    df["ema50"] = df["c"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["c"].ewm(span=200, adjust=False).mean()
    sig = (df["l"] <= df["ema50"]) & (df["c"] > df["ema50"]) & (df["c"] > df["ema200"])
    sig &= np.arange(len(df)) >= (WARMUP - 1)
    df["sig"] = sig.values
    return df


def sim(df, start, end, cost, sleeve0=SLEEVE0):
    """Run one sleeve over bars with open_time>=start and close_time<=end. Returns trades, per-bar equity, in-pos flags."""
    o, h, l, c = df["o"].values, df["h"].values, df["l"].values, df["c"].values
    sig = df["sig"].values
    mask = (df["t"] >= start) & (df["tc"] <= end)
    idx = np.where(mask.values)[0]
    if len(idx) == 0:
        return [], pd.Series(dtype=float), np.array([]), 0
    i0, i1 = idx[0], idx[-1]
    cash = sleeve0
    units = 0.0
    stop = tp = entry = 0.0
    ent_i = -1
    ent_cost = 0.0
    trades = []
    eq = np.empty(i1 - i0 + 1)
    inpos = np.zeros(i1 - i0 + 1, dtype=bool)
    skipped = 0
    for i in range(i0, i1 + 1):
        just_entered = False
        if units == 0.0 and i - 1 >= 0 and sig[i - 1] and i - LOOKBACK_STOP >= 0:
            st = l[i - LOOKBACK_STOP:i].min()     # bars i-10..i-1 = signal bar and 9 before it
            ep = o[i]
            if ep > st:
                r = ep - st
                u = min(RISK * cash / r, cash / (ep * (1 + cost)))
                ent_cost = u * ep * cost
                cash -= u * ep + ent_cost
                units, stop, entry, tp, ent_i = u, st, ep, ep + RR * r, i
                just_entered = True
            else:
                skipped += 1
        if units > 0:
            inpos[i - i0] = True
            xp = None
            reason = None
            if not just_entered and o[i] <= stop:
                xp, reason = o[i], "stop_gap"
            elif not just_entered and o[i] >= tp:
                xp, reason = o[i], "tp_gap"
            elif l[i] <= stop:          # stop first if both touched
                xp, reason = stop, "stop"
                both = h[i] >= tp
            elif h[i] >= tp:
                xp, reason = tp, "tp"
            if xp is None and i == i1:
                xp, reason = c[i], "period_end"
            if xp is not None:
                proceeds = units * xp
                xc = proceeds * cost
                cash += proceeds - xc
                pnl = units * (xp - entry) - ent_cost - xc
                trades.append(dict(entry_time=df["t"].iat[ent_i], exit_time=df["t"].iat[i], entry=entry, stop=stop,
                                   tp=tp, exit=xp, units=units, notional=units * entry, pnl=pnl, reason=reason,
                                   both_touched=bool(reason == "stop" and h[i] >= tp), bars=i - ent_i + 1,
                                   sleeve_eq_at_entry=units * entry + ent_cost + (cash - proceeds + xc)))
                units = 0.0
        eq[i - i0] = cash + units * c[i]
    s = pd.Series(eq, index=df["tc"].values[i0:i1 + 1])
    return trades, s, inpos, skipped


def daily_marks(s):
    # last mark per UTC day (bar closing at 23:59:59.999 belongs to that day)
    return s.groupby(s.index.floor("D")).last()


def bench_sleeve(df, start, end, cost, sleeve0=SLEEVE0):
    mask = (df["t"] >= start) & (df["tc"] <= end)
    d = df[mask]
    if len(d) == 0:
        return None
    u = sleeve0 / (d["o"].iat[0] * (1 + cost))
    eq = u * d["c"].values
    eq[-1] = eq[-1] * (1 - cost)
    return pd.Series(eq, index=d["tc"].values)


def combine(series_list, start):
    days = sorted(set().union(*[set(daily_marks(s).index) for s in series_list if s is not None and len(s)]))
    days = pd.DatetimeIndex(days)
    tot = pd.Series(0.0, index=days)
    for s in series_list:
        if s is None or len(s) == 0:
            tot += SLEEVE0
            continue
        dm = daily_marks(s).reindex(days).ffill().fillna(SLEEVE0)
        tot += dm
    start_day = start.floor("D") - pd.Timedelta(days=1)
    tot = pd.concat([pd.Series([100.0], index=[start_day]), tot])
    return tot


def maxdd(e):
    pk = e.cummax()
    return float(((e / pk) - 1).min() * 100)


def cagr(final, start, end):
    yrs = (end - start).total_seconds() / (365.25 * 86400)
    return ((final / 100.0) ** (1 / yrs) - 1) * 100


DFS = {s: load(s) for s in SYMS}


def run_period(name, cost):
    start, end = PERIODS[name]
    all_tr = []
    eqs = []
    expo = []
    skipped = 0
    per_asset = {}
    nbars_period = None
    for s in SYMS:
        tr, eq, inpos, sk = sim(DFS[s], start, end, cost)
        skipped += sk
        for t in tr:
            t["sym"] = s
        all_tr += tr
        eqs.append(eq)
        per_asset[s] = (eq.iloc[-1] - SLEEVE0) if len(eq) else 0.0
        expo.append(inpos)
    # exposure: time-based, per sleeve, denominator = period length in 4h bars (calendar), averaged over 3 sleeves
    total_bars = (end - start).total_seconds() / (4 * 3600)
    expo_pct = np.mean([x.sum() / total_bars for x in expo]) * 100
    tot = combine(eqs, start)
    final = tot.iloc[-1]
    tdf = pd.DataFrame(all_tr)
    wins = tdf.loc[tdf.pnl > 0, "pnl"].sum()
    losses = -tdf.loc[tdf.pnl <= 0, "pnl"].sum()
    # notional exposure: sum over trades of notional*bars / (sleeve equity) ... approximate with initial sleeve
    b = [bench_sleeve(DFS[s], start, end, cost) for s in SYMS]
    btot = combine(b, start)
    return dict(
        trades=len(tdf), win_rate=float((tdf.pnl > 0).mean() * 100), pf=float(wins / losses),
        net=float(final - 100), cagr=float(cagr(final, start, end)), mdd=maxdd(tot), expo=float(expo_pct),
        bench_net=float(btot.iloc[-1] - 100), bench_mdd=maxdd(btot), bench_cagr=float(cagr(btot.iloc[-1], start, end)),
        per_asset=per_asset, reasons=tdf.reason.value_counts().to_dict(), both=int(tdf.both_touched.sum()),
        skipped=skipped, tdf=tdf, tot=tot, btot=btot,
    )


if __name__ == "__main__":
    res = {}
    for p in ["IS", "OOS", "FULL"]:
        r1 = run_period(p, COST)
        r2 = run_period(p, 2 * COST)
        res[p] = (r1, r2)
        tdf = r1["tdf"]
        R = (tdf.exit - tdf.entry) / (tdf.entry - tdf.stop)
        under5 = (tdf.notional < 5).mean() * 100
        print(f"== {p}: trades={r1['trades']} win={r1['win_rate']:.2f} pf={r1['pf']:.3f} net={r1['net']:.2f} "
              f"cagr={r1['cagr']:.2f} mdd={r1['mdd']:.2f} expo={r1['expo']:.2f} | bench net={r1['bench_net']:.2f} "
              f"mdd={r1['bench_mdd']:.2f} cagr={r1['bench_cagr']:.2f} | 2x net={r2['net']:.2f} pf2x={r2['pf']:.3f}")
        print("   per-asset $:", {k: round(v, 2) for k, v in r1["per_asset"].items()}, "reasons:", r1["reasons"],
              "both:", r1["both"], "skipped(open<=stop):", r1["skipped"])
        print(f"   mean R gross={R.mean():.3f}  median notional/sleeve-eq={np.median(tdf.notional / tdf.sleeve_eq_at_entry):.3f}"
              f"  cap-bound share={(np.isclose(tdf.notional / tdf.sleeve_eq_at_entry, 1/(1+COST), atol=1e-6)).mean()*100:.1f}%"
              f"  trades with notional<$5: {under5:.1f}%  first entry {tdf.entry_time.min()}  ret/mdd={r1['net']/abs(r1['mdd']):.2f}"
              f" bench ret/mdd={r1['bench_net']/abs(r1['bench_mdd']):.2f}")
        if p == "FULL":
            tdf.to_csv(f"{OUT}/verify_trades_full.csv", index=False)
    json.dump({p: {k: v for k, v in res[p][0].items() if k not in ("tdf", "tot", "btot")} | {"net_2x": res[p][1]["net"], "pf_2x": res[p][1]["pf"]}
               for p in res}, open(f"{OUT}/verify_result.json", "w"), default=str, indent=1)
