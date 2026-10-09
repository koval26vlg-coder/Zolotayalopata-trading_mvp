# C5 FEAR_GREED_CONTRARIAN -- frozen rule from SPEC2.md (2026-10-07)
# Buy 100% BTC at next day open when FGI <= 20; sell to USDT at next day open when FGI >= 80. Start in USDT.
# Benchmark: BTC buy&hold from first FGI date. Costs: crypto spot 20 bps per side; stress 2x.
# Timing convention (conservative): FGI value stamped date D (00:00 UTC) is treated as the day-D observation;
# action executes at the OPEN of the Binance daily bar D+1. Signal date < execution bar date (asserted).
# Primary period runs: each period (IS / OOS / FULL) simulated independently, starting in USDT at period start
# (signals from the FGI value dated the day before the period start may execute at the first open).
# Additional accounting view (reported in notes only): OOS slice of the continuous FULL run (state carried from IS).
import json, glob, hashlib, os
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
COST = 0.0020
CUTOFF = pd.Timestamp("2026-10-06")          # last daily bar (closed 2026-10-06 23:59 UTC)
IS_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")
BUY_LVL, SELL_LVL = 20, 80


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---------------- data ----------------
fng_raw = json.load(open(os.path.join(DATA, "fng.json")))["data"]
fgi_all = pd.Series({pd.to_datetime(int(x["timestamp"]), unit="s"): int(x["value"]) for x in fng_raw}).sort_index()
assert (fgi_all.index.hour == 0).all()
fgi = fgi_all[fgi_all.index <= CUTOFF]       # FGI stamped 2026-10-07 excluded (its execution bar is beyond cutoff)

parts = sorted(glob.glob(os.path.join(DATA, "btcusdt_1d_part*.json")))
rows = []
for p in parts:
    rows += json.load(open(p))
k = pd.DataFrame(rows).iloc[:, :7]
k.columns = ["ot", "open", "high", "low", "close", "vol", "ct"]
k = k.drop_duplicates("ot")
k.index = pd.to_datetime(k["ot"], unit="ms")
k = k[["open", "high", "low", "close"]].astype(float).sort_index()
k = k[k.index <= CUTOFF]
assert pd.to_datetime(k.index[-1]) == CUTOFF
assert (k.index == pd.date_range(k.index[0], k.index[-1], freq="D")).all(), "gap in BTC daily bars"

FIRST_FGI = fgi.index[0]                      # 2018-02-01


# ---------------- simulation ----------------
def simulate(start, end, cost, fgi_s=fgi, px=k, liquidate=True):
    days = px.loc[start:end].index
    cash, units, long_ = 1.0, 0.0, False
    eq, held, trades, cur = [], [], [], None
    for t in days:
        sig_date = t - pd.Timedelta(days=1)
        if sig_date in fgi_s.index:
            v = fgi_s[sig_date]
            o = px.at[t, "open"]
            if (not long_) and v <= BUY_LVL:
                assert sig_date < t
                units = cash * (1 - cost) / o
                cur = dict(signal_in=str(sig_date.date()), fgi_in=int(v), entry_date=str(t.date()), entry_px=o,
                           cash_in=cash)
                cash, long_ = 0.0, True
            elif long_ and v >= SELL_LVL:
                assert sig_date < t
                cash = units * o * (1 - cost)
                cur.update(signal_out=str(sig_date.date()), fgi_out=int(v), exit_date=str(t.date()), exit_px=o,
                           pnl=cash - cur["cash_in"], ret_pct=(cash / cur["cash_in"] - 1) * 100, forced=False)
                trades.append(cur); cur = None
                units, long_ = 0.0, False
        c = px.at[t, "close"]
        eq.append(cash + units * c)
        held.append(long_)
    eq = pd.Series(eq, index=days)
    if liquidate and long_:
        t = days[-1]; c = px.at[t, "close"]
        cash = units * c * (1 - cost)
        cur.update(signal_out=None, fgi_out=None, exit_date=str(t.date()) + " (close, forced end-of-period)",
                   exit_px=c, pnl=cash - cur["cash_in"], ret_pct=(cash / cur["cash_in"] - 1) * 100, forced=True)
        trades.append(cur)
        eq.iloc[-1] = cash
    return eq, pd.Series(held, index=days), trades


def bench(start, end, cost, px=k):
    days = px.loc[start:end].index
    units = (1 - cost) / px.at[days[0], "open"]
    eq = units * px.loc[days, "close"]
    eq.iloc[-1] = eq.iloc[-1] * (1 - cost)
    return eq


def metrics(eq, held=None, trades=None):
    curve = pd.concat([pd.Series([1.0]), pd.Series(eq.values)])
    dd = (curve / curve.cummax() - 1).min() * 100
    ndays = (eq.index[-1] - eq.index[0]).days + 1
    fin = eq.iloc[-1]
    out = dict(net_return_pct=(fin - 1) * 100, cagr_pct=(fin ** (365.25 / ndays) - 1) * 100, max_dd_pct=dd,
               days=ndays)
    if held is not None:
        out["exposure_pct"] = held.mean() * 100
    if trades is not None:
        pn = np.array([t["pnl"] for t in trades])
        out["trades"] = len(trades)
        out["forced_open_trades"] = sum(t["forced"] for t in trades)
        out["win_rate_pct"] = (pn > 0).mean() * 100 if len(pn) else None
        gw, gl = pn[pn > 0].sum(), -pn[pn < 0].sum()
        out["pf"] = (gw / gl) if gl > 0 else (None if gw == 0 else float("inf"))
    return out


periods = {
    "IS": (FIRST_FGI, IS_END),
    "OOS": (OOS_START, CUTOFF),
    "FULL": (FIRST_FGI, CUTOFF),
}

res = {}
for name, (s, e) in periods.items():
    eq, held, tr = simulate(s, e, COST)
    eq2, _, tr2 = simulate(s, e, 2 * COST)
    b = bench(s, e, COST)
    m = metrics(eq, held, tr)
    bm = metrics(b)
    m["net_return_2x_cost_pct"] = (eq2.iloc[-1] - 1) * 100
    m["bench_net_return_pct"] = bm["net_return_pct"]
    m["bench_max_dd_pct"] = bm["max_dd_pct"]
    m["bench_cagr_pct"] = bm["cagr_pct"]
    m["ret_dd_ratio"] = m["net_return_pct"] / abs(m["max_dd_pct"]) if m["max_dd_pct"] < 0 else None
    m["bench_ret_dd_ratio"] = bm["net_return_pct"] / abs(bm["max_dd_pct"])
    m["start"], m["end"] = str(s.date()), str(e.date())
    m["trade_list"] = tr
    res[name] = m

# continuous-state OOS slice (accounting view; not used for verdict)
eqF, heldF, trF = simulate(FIRST_FGI, CUTOFF, COST)
base = eqF.loc[IS_END]
sl = eqF.loc[OOS_START:] / base
cont = metrics(sl, heldF.loc[OOS_START:])
eqF2, _, _ = simulate(FIRST_FGI, CUTOFF, 2 * COST)
cont["net_return_2x_cost_pct"] = (eqF2.iloc[-1] / eqF2.loc[IS_END] - 1) * 100
cont["ret_dd_ratio"] = cont["net_return_pct"] / abs(cont["max_dd_pct"])
cont["bench_net_return_pct"] = res["OOS"]["bench_net_return_pct"]
cont["bench_max_dd_pct"] = res["OOS"]["bench_max_dd_pct"]
cont["bench_ret_dd_ratio"] = res["OOS"]["bench_ret_dd_ratio"]
cont["trades_closed_in_oos"] = [t for t in trF if t["exit_date"][:10] >= "2023-01-01"]
cont["note"] = ("OOS-срез непрерывного FULL-прогона: позиция, открытая в IS, переносится в OOS; "
                "база = equity на close 2022-12-31")
cont["position_at_IS_end"] = bool(heldF.loc[IS_END])

# ---------------- self-checks ----------------
checks = {}
# 1) every executed trade: signal date strictly before execution bar, FGI condition holds at the signal date
ok = True
for t in res["FULL"]["trade_list"]:
    if pd.Timestamp(t["signal_in"]) >= pd.Timestamp(t["entry_date"]): ok = False
    if fgi[pd.Timestamp(t["signal_in"])] > BUY_LVL: ok = False
    if (pd.Timestamp(t["entry_date"]) - pd.Timestamp(t["signal_in"])).days != 1: ok = False
    if not t["forced"]:
        if pd.Timestamp(t["signal_out"]) >= pd.Timestamp(t["exit_date"]): ok = False
        if fgi[pd.Timestamp(t["signal_out"])] < SELL_LVL: ok = False
checks["signal_date_lt_execution_bar_and_condition_true"] = ok
# 2) look-ahead invariance: scramble FGI and prices strictly after day X; equity through close of X must not change
rng = np.random.default_rng(7)
eq_ref, _, _ = simulate(FIRST_FGI, CUTOFF, COST, liquidate=False)
inv_ok = True
for X in rng.choice(eq_ref.index[30:-30], 25, replace=False):
    X = pd.Timestamp(X)
    f2 = fgi.copy(); m_ = f2.index >= X
    f2[m_] = rng.integers(0, 101, m_.sum())          # FGI dated X or later is only usable from open X+1 on
    p2 = k.copy(); mp = p2.index > X
    p2.loc[mp, ["open", "high", "low", "close"]] *= rng.uniform(0.5, 1.5, (mp.sum(), 1))
    e2, _, _ = simulate(FIRST_FGI, CUTOFF, COST, fgi_s=f2, px=p2, liquidate=False)
    if not np.allclose(e2.loc[:X].values, eq_ref.loc[:X].values, rtol=0, atol=1e-12):
        inv_ok = False
checks["lookahead_invariance_25_random_cutpoints"] = inv_ok
# 3) data cutoff
checks["last_btc_bar"] = str(k.index[-1].date())
checks["last_fgi_used"] = str(fgi.index[-1].date())
checks["fgi_2026_10_07_excluded"] = bool(pd.Timestamp("2026-10-07") not in fgi.index)
checks["fgi_missing_days"] = [str(d.date()) for d in pd.date_range(fgi.index[0], fgi.index[-1]).difference(fgi.index)]
# 4) pending signal at the end (FGI 2026-10-06 would execute 2026-10-07 open -- beyond data)
last_v = int(fgi.iloc[-1])
checks["fgi_2026_10_06_value"] = last_v
checks["intrabar_stop_rule"] = "не применимо: стопов/тейков нет, только исполнение по open следующего дня"
# 5) recompute FULL final equity from trade returns
prod = 1.0
for t in res["FULL"]["trade_list"]:
    prod *= 1 + t["ret_pct"] / 100
checks["full_equity_matches_trade_product"] = bool(abs(prod - (1 + res["FULL"]["net_return_pct"] / 100)) < 1e-9)
assert checks["signal_date_lt_execution_bar_and_condition_true"] and inv_ok and checks["full_equity_matches_trade_product"]


# ---------------- verdict (pre-registered, mechanical, on OOS) ----------------
def verdict(m):
    reasons = []
    TOL = 1e-6  # percentage-point tolerance: identical drawdowns (same BTC peak->trough while long) count as a tie
    worse_both = (m["net_return_pct"] < m["bench_net_return_pct"] - TOL) and (m["max_dd_pct"] < m["bench_max_dd_pct"] - TOL)
    pf = m["pf"]
    if m["net_return_pct"] <= 0: reasons.append("OOS net return <= 0")
    if pf is not None and pf < 1.0: reasons.append("PF < 1.0")
    if pf is None and m["trades"] > 0: reasons.append("PF не определён (нет прибыльных сделок)")
    if worse_both: reasons.append("хуже бенчмарка и по доходности, и по max DD")
    if m["trades"] == 0: reasons.append("0 сделок в OOS")
    if reasons:
        return "FAIL", reasons
    # INCONCLUSIVE trade-count clause is scoped to event/trade strategies; C5 is typed 'directional'
    passed = (m["net_return_pct"] > 0 and (pf is not None and pf >= 1.2)
              and m["ret_dd_ratio"] is not None and m["ret_dd_ratio"] > m["bench_ret_dd_ratio"]
              and m["net_return_2x_cost_pct"] > 0)
    if not passed:
        if m["ret_dd_ratio"] is None or m["ret_dd_ratio"] <= m["bench_ret_dd_ratio"]:
            reasons.append(f"PASS не выполнен: return/maxDD {m['ret_dd_ratio']:.2f} <= бенчмарк {m['bench_ret_dd_ratio']:.2f}")
        if abs(m["max_dd_pct"] - m["bench_max_dd_pct"]) <= TOL:
            reasons.append("FAIL-условие 'хуже по обоим' не сработало только из-за ничьей по max DD (та же просадка BTC, стратегия была в позиции)")
        if m["trades"] < 30:
            reasons.append(f"всего {m['trades']} сделок в OOS (из них принудительно закрытых в конце: {m['forced_open_trades']}) -- выборка мала")
    return ("PASS_CANDIDATE" if passed else "INCONCLUSIVE"), reasons


v, vr = verdict(res["OOS"])

out = dict(id="C5", verdict=v, verdict_reasons=vr, periods={kk: {x: y for x, y in vv.items()} for kk, vv in res.items()},
           oos_continuous_state=cont, self_checks=checks,
           data_sources=[
               dict(name="alternative.me Fear & Greed Index (daily)", url="https://api.alternative.me/fng/?limit=0&format=json",
                    file="data/fng.json", sha256=sha(os.path.join(DATA, "fng.json")), rows=int(len(fgi_all)),
                    start=str(fgi_all.index[0].date()), end=str(fgi_all.index[-1].date()),
                    rows_used=int(len(fgi)), end_used=str(fgi.index[-1].date())),
           ] + [dict(name=f"Binance BTCUSDT 1d klines ({os.path.basename(p)})",
                     url="https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&startTime=1514764800000&limit=1000 (paginated)",
                     file="data/" + os.path.basename(p), sha256=sha(p), rows=len(json.load(open(p))))
                for p in parts])
def clean(o):
    if isinstance(o, dict): return {a: clean(b) for a, b in o.items()}
    if isinstance(o, list): return [clean(b) for b in o]
    if isinstance(o, (float, np.floating)):
        o = float(o)
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.integer): return int(o)
    return o
for kk in res:
    if res[kk]["pf"] == float("inf"):
        out["periods"][kk]["pf_note"] = "PF = inf (нет убыточных сделок); в JSON записан null"
json.dump(clean(out), open(os.path.join(BASE, "result.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

# console summary
for kk, m in res.items():
    print(kk, {x: (round(y, 3) if isinstance(y, float) else y) for x, y in m.items() if x != "trade_list"})
print("OOS-cont", {x: (round(y, 3) if isinstance(y, float) else y) for x, y in cont.items()})
print("checks", checks)
print("VERDICT", v, vr)
for t in res["FULL"]["trade_list"]:
    print({x: (round(y, 2) if isinstance(y, float) else y) for x, y in t.items()})
print("OOS fresh trades:")
for t in res["OOS"]["trade_list"]:
    print({x: (round(y, 2) if isinstance(y, float) else y) for x, y in t.items()})
