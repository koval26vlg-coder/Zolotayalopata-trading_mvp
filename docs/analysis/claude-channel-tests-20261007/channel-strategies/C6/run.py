# C6 RELATIVE_STRENGTH_IN_SELLOFF  -- frozen rule from SPEC2.md (no tuning)
# Event: BTC 7d return <= -10% at a daily close and no open trade.
# Rank frozen universe by (coin 7d - BTC 7d); buy top-3 equal weight at next day open, hold 14 days, exit at open.
# Controls: bottom-3 same timing, BTC same timing. Benchmark: equal-weight universe buy&hold.
import json, hashlib, os, math
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UNIV = ["ETH", "BNB", "XRP", "ADA", "DOGE", "LTC", "LINK", "BCH", "TRX", "XLM", "EOS", "ATOM", "XTZ",
        "ETC", "NEO", "VET", "ZEC", "DASH", "IOTA", "ONT"]
COST = 0.0020          # crypto spot, per side (fee + slippage)
START = pd.Timestamp("2020-01-01")   # universe is defined point-in-time on 2020-01-01
IS_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2026-10-06")     # last daily bar closed on/before 2026-10-06 23:59 UTC
THRESH = -0.10
HOLD = 14
TOPN = 3


def load(sym):
    raw = json.load(open(os.path.join(DATA, f"{sym}USDT_1d.json")))
    df = pd.DataFrame(raw).iloc[:, :7]
    df.columns = ["ot", "open", "high", "low", "close", "vol", "ct"]
    df["date"] = pd.to_datetime(df["ot"], unit="ms").dt.normalize()
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    # only bars whose close time is <= 2026-10-06 23:59:59.999 UTC
    df = df[pd.to_datetime(df["ct"], unit="ms") <= pd.Timestamp("2026-10-06 23:59:59.999")]
    assert not df["date"].duplicated().any(), sym
    return df.set_index("date")[["open", "close"]]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---------------- data ----------------
btc = load("BTC")
coins = {}
for c in UNIV:
    d = load(c)
    if c == "EOS":
        # EOS -> Vaulta (A) 1:1 swap on Binance 2025-05-26/28; A first open == EOS last close (checked below)
        a = load("A")
        assert abs(a["open"].iloc[0] - d["close"].iloc[-1]) / d["close"].iloc[-1] < 0.01, "EOS/A stitch gap"
        d = pd.concat([d, a])
        assert not d.index.duplicated().any()
    coins[c] = d

# universe check: daily kline present on 2020-01-01
for c in UNIV:
    assert pd.Timestamp("2020-01-01") in coins[c].index, f"{c} not listed on 2020-01-01"

idx = pd.date_range(btc.index.min(), END, freq="D")
O = pd.DataFrame({c: coins[c]["open"].reindex(idx) for c in UNIV})
C = pd.DataFrame({c: coins[c]["close"].reindex(idx) for c in UNIV})
bO = btc["open"].reindex(idx)
bC = btc["close"].reindex(idx)
missing = {c: int(C[c].loc[START:END].isna().sum()) for c in UNIV}
missing["BTC"] = int(bC.loc[START:END].isna().sum())
assert missing["BTC"] == 0

# 7d returns using only closes at t and t-7 (shift by 7 calendar rows; index is a full daily calendar)
btc_r7 = bC / bC.shift(7) - 1
coin_r7 = C / C.shift(7) - 1
rel = coin_r7.sub(btc_r7, axis=0)
Cf = C.ffill()  # marks only (forward-fill through exchange halts)


def next_open(series, day):
    """first available open on or after `day` (handles halts); returns (date, price) or (None, None)"""
    s = series.loc[day:END].dropna()
    if len(s) == 0:
        return None, None
    return s.index[0], float(s.iloc[0])


def rank_at(t, rel_df=None):
    r = (rel if rel_df is None else rel_df).loc[t].dropna()
    # descending relative strength, deterministic tie-break by name
    return sorted(r.index, key=lambda c: (-r[c], c))


# ---------------- event detection + trades (FULL path, continuous) ----------------
def build_trades(start, end, cost):
    trades = []
    busy_until = None  # date of exit open; trade is open at closes < exit date
    days = pd.date_range(start - pd.Timedelta(days=1), end, freq="D")  # signal may be on day before period start
    for t in days:
        if t + pd.Timedelta(days=1) > end:
            break
        if busy_until is not None and t < busy_until:
            continue
        r = btc_r7.loc[t]
        if not (pd.notna(r) and r <= THRESH):
            continue
        order = rank_at(t)
        entry_day = t + pd.Timedelta(days=1)
        exit_day = entry_day + pd.Timedelta(days=HOLD)
        legs = {"top": order[:TOPN], "bottom": order[-TOPN:][::-1]}
        tr = {"signal": t, "entry": entry_day, "exit_sched": exit_day, "btc_r7": float(r),
              "n_ranked": len(order), "top": legs["top"], "bottom": legs["bottom"],
              "rel_top": [float(rel.loc[t, c]) for c in legs["top"]]}
        trades.append(tr)
        busy_until = exit_day
    return trades


def simulate(start, end, cost, which="top"):
    """returns daily equity (close marks), list of trade dicts with pnl, exposure days"""
    trades = build_trades(start, end, cost)
    eq = pd.Series(np.nan, index=pd.date_range(start, end, freq="D"))
    cash = 1.0
    pos = None  # dict of units per asset
    out = []
    tmap = {tr["entry"]: tr for tr in trades}
    exposed = 0
    for d in eq.index:
        # exit at open
        if pos is not None and d == pos["exit"]:
            proceeds = 0.0
            for a, u in pos["units"].items():
                px = pos["xpx"][a]
                proceeds += u * px * (1 - cost)
            pos["tr"]["pnl"] = proceeds - pos["cap"]
            pos["tr"]["ret"] = proceeds / pos["cap"] - 1
            pos["tr"]["exit"] = d
            out.append(pos["tr"])
            cash = proceeds
            pos = None
        # entry at open
        if pos is None and d in tmap:
            tr = dict(tmap[d])
            assets = [which] if which == "BTC" else tr[which]
            cap = cash
            units, xpx = {}, {}
            exit_day = tr["exit_sched"]
            forced = exit_day > end
            for a in assets:
                o_ser = bO if a == "BTC" else O[a]
                c_ser = bC if a == "BTC" else C[a]
                ed, ep = next_open(o_ser, d)
                assert ed == d, f"no entry open for {a} on {d}"
                units[a] = (cap / len(assets)) * (1 - cost) / ep
                if not forced:
                    xd, xp = next_open(o_ser, exit_day)
                    assert xd is not None and xd == exit_day, f"exit open missing {a} {exit_day}"
                    xpx[a] = xp
            if forced:
                exit_day = end + pd.Timedelta(days=1)  # close at last close of period (marked below)
                for a in assets:
                    c_ser = bC if a == "BTC" else Cf[a]
                    xpx[a] = float(c_ser.loc[end])
            tr["forced_close_at_period_end"] = forced
            pos = {"units": units, "cap": cap, "exit": exit_day, "xpx": xpx, "tr": tr}
            cash = 0.0
        # mark at close
        if pos is not None:
            v = sum(u * float((bC if a == "BTC" else Cf[a]).loc[d]) for a, u in pos["units"].items())
            eq.loc[d] = v
            exposed += 1
        else:
            eq.loc[d] = cash
    if pos is not None:  # forced close at period end close
        proceeds = sum(u * pos["xpx"][a] * (1 - cost) for a, u in pos["units"].items())
        pos["tr"]["pnl"] = proceeds - pos["cap"]
        pos["tr"]["ret"] = proceeds / pos["cap"] - 1
        pos["tr"]["exit"] = end
        out.append(pos["tr"])
        eq.iloc[-1] = proceeds
    return eq, out, exposed


def bench_ew(start, end, cost):
    first = O.loc[start]
    assert first.notna().all()
    units = (1.0 / len(UNIV)) * (1 - cost) / first
    eq = (Cf.loc[start:end] * units).sum(axis=1)
    eq.iloc[-1] = eq.iloc[-1] * (1 - cost)  # liquidation at end
    return eq


def bench_btc(start, end, cost):
    u = (1 - cost) / bO.loc[start]
    eq = bC.loc[start:end] * u
    eq.iloc[-1] *= (1 - cost)
    return eq


def mdd(eq):
    return float((eq / eq.cummax() - 1).min() * 100)


def stats(eq, trades, exposed, start, end):
    ndays = (end - start).days + 1
    net = float(eq.iloc[-1] / 1.0 - 1)
    cagr = (eq.iloc[-1]) ** (365.25 / ndays) - 1
    pnls = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    gw = pnls[pnls > 0].sum() if len(pnls) else 0.0
    gl = -pnls[pnls < 0].sum() if len(pnls) else 0.0
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else None)
    return {"trades": len(trades), "win_rate_pct": (float((pnls > 0).mean() * 100) if len(pnls) else None),
            "pf": (None if pf is None else (round(pf, 3) if math.isfinite(pf) else 999.0)),
            "net_return_pct": round(net * 100, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(mdd(eq), 2), "exposure_pct": round(exposed / ndays * 100, 2)}


PERIODS = {"IS": (START, IS_END), "OOS": (OOS_START, END), "FULL": (START, END)}

# ---------------- self-checks against look-ahead ----------------
checks = {}
full_trades = build_trades(START, END, COST)
# 1) signal bar strictly before execution bar; non-overlap; event only when flat
prev_exit = None
for tr in full_trades:
    assert tr["signal"] < tr["entry"], "signal must precede entry"
    assert tr["entry"] - tr["signal"] == pd.Timedelta(days=1)
    if prev_exit is not None:
        assert tr["signal"] >= prev_exit, "event while trade open"
    prev_exit = tr["exit_sched"]
checks["signal_before_entry_all"] = True
checks["no_overlapping_trades"] = True
# 2) truncation test: recompute each signal & ranking using data truncated at the signal close
for tr in full_trades:
    t = tr["signal"]
    Ct, bCt = C.loc[:t], bC.loc[:t]
    br = bCt.iloc[-1] / bCt.iloc[-8] - 1
    assert abs(br - tr["btc_r7"]) < 1e-12 and br <= THRESH
    relt = (Ct.iloc[-1] / Ct.iloc[-8] - 1) - br
    relt = relt.dropna()
    order_t = sorted(relt.index, key=lambda c: (-relt[c], c))
    assert order_t[:TOPN] == tr["top"] and order_t[-TOPN:][::-1] == tr["bottom"], f"ranking look-ahead at {t}"
checks["truncated_data_reproduces_signals_and_ranks"] = True
# 3) future-poisoning test: corrupt all prices after each signal and verify identical selection
rng = np.random.default_rng(0)
for tr in full_trades[:]:
    t = tr["signal"]
    Cp = C.copy(); bCp = bC.copy()
    fut = Cp.index > t
    Cp.loc[fut] = Cp.loc[fut].values * rng.uniform(0.2, 5.0, size=Cp.loc[fut].shape)
    bCp.loc[fut] = bCp.loc[fut].values * rng.uniform(0.2, 5.0, size=fut.sum())
    relp = (Cp / Cp.shift(7) - 1).sub(bCp / bCp.shift(7) - 1, axis=0)
    assert rank_at(t, relp)[:TOPN] == tr["top"]
checks["future_poisoning_invariant"] = True
checks["intrabar_stop_first"] = "N/A: no stops/targets in C6 (time exit at open only)"
checks["universe_all_listed_2020_01_01"] = True
checks["missing_daily_closes_in_window"] = missing
checks["eos_stitch"] = "EOSUSDT to 2025-05-26 (halted 03:00 UTC) + AUSDT (Vaulta, 1:1 swap) from 2025-05-28; A first open 0.7799 == EOS last close 0.7799; 2025-05-27 no bar (marks forward-filled, excluded from ranking if needed)"

# ---------------- run ----------------
results = {}
trade_log = []
for name, (s, e) in PERIODS.items():
    row = {}
    for which in ["top", "bottom", "BTC"]:
        eq, trs, ex = simulate(s, e, COST, which)
        eq2, trs2, _ = simulate(s, e, 2 * COST, which)
        st = stats(eq, trs, ex, s, e)
        st["net_return_2x_cost_pct"] = round((eq2.iloc[-1] - 1) * 100, 2)
        st["legs"] = len(trs) * (1 if which == "BTC" else TOPN)
        st["forced_close_trades"] = sum(1 for x in trs if x.get("forced_close_at_period_end"))
        row[which] = st
        if which == "top" and name == "FULL":
            for x in trs:
                trade_log.append({"signal": str(x["signal"].date()), "entry": str(x["entry"].date()),
                                  "exit": str(x["exit"].date()), "btc_r7_pct": round(x["btc_r7"] * 100, 2),
                                  "top3": x["top"], "bottom3": x["bottom"], "n_ranked": x["n_ranked"],
                                  "ret_pct": round(x["ret"] * 100, 2)})
    be = bench_ew(s, e, COST)
    bb = bench_btc(s, e, COST)
    ndays = (e - s).days + 1
    row["bench_ew"] = {"net_return_pct": round((be.iloc[-1] - 1) * 100, 2),
                       "cagr_pct": round((be.iloc[-1] ** (365.25 / ndays) - 1) * 100, 2),
                       "max_dd_pct": round(mdd(be), 2)}
    row["bench_btc_bh"] = {"net_return_pct": round((bb.iloc[-1] - 1) * 100, 2), "max_dd_pct": round(mdd(bb), 2)}
    results[name] = row

# per-trade log merge for bottom/BTC same timing
botFULL = simulate(START, END, COST, "bottom")[1]
btcFULL = simulate(START, END, COST, "BTC")[1]
for i, x in enumerate(trade_log):
    x["bottom3_ret_pct"] = round(botFULL[i]["ret"] * 100, 2)
    x["btc_ret_pct"] = round(btcFULL[i]["ret"] * 100, 2)

# straddle check across IS/OOS boundary
straddle = [x for x in trade_log if x["entry"] <= "2022-12-31" < x["exit"]]
checks["trades_straddling_IS_OOS"] = straddle


# ---------------- pre-registered verdict (OOS, mechanical) ----------------
def verdict(r):
    s, b = r["top"], r["bench_ew"]
    ratio = lambda net, dd: net / abs(dd) if dd != 0 else float("inf")
    worse_both = (s["net_return_pct"] < b["net_return_pct"]) and (s["max_dd_pct"] < b["max_dd_pct"])
    if s["net_return_pct"] <= 0 or (s["pf"] is not None and s["pf"] < 1.0) or worse_both:
        why = []
        if s["net_return_pct"] <= 0: why.append("OOS net <= 0")
        if s["pf"] is not None and s["pf"] < 1.0: why.append("PF < 1.0")
        if worse_both: why.append("worse than benchmark on both return and maxDD")
        return "FAIL", why
    if s["trades"] < 30:
        return "INCONCLUSIVE", [f"OOS trades {s['trades']} < 30"]
    if (s["pf"] >= 1.2 and ratio(s["net_return_pct"], s["max_dd_pct"]) > ratio(b["net_return_pct"], b["max_dd_pct"])
            and s["net_return_2x_cost_pct"] > 0):
        return "PASS_CANDIDATE", ["all PASS criteria met"]
    return "INCONCLUSIVE", ["positive but PASS criteria not all met"]


v, why = verdict(results["OOS"])
out = {"id": "C6", "verdict": v, "verdict_why": why, "results": results, "checks": checks, "trades": trade_log,
       "cost_per_side": COST, "periods": {k: [str(a.date()), str(b.date())] for k, (a, b) in PERIODS.items()},
       "data_sources": [{"name": f, "sha256": sha(os.path.join(DATA, f))} for f in sorted(os.listdir(DATA))]}
json.dump(out, open(os.path.join(HERE, "result.json"), "w"), indent=1, default=str)
print(json.dumps({k: results[k] for k in results}, indent=1))
print("VERDICT", v, why)
print("checks", {k: v for k, v in checks.items() if k != "missing_daily_closes_in_window"})
print("missing", missing)
print(pd.DataFrame(trade_log).to_string())
