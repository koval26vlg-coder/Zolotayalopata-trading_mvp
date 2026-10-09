# C15A US_GAP_CONTINUATION / C15B US_GAP_FADE  -- frozen per SPEC2.md (2026-10-07)
# Data: Yahoo chart API daily (split-adjusted OHLC, adjclose for benchmark total return), saved in data/*.json
import json, glob, os, hashlib, datetime as dt
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
T = "AAPL MSFT AMZN GOOGL META NVDA TSLA JPM BAC XOM CVX JNJ PFE KO PEP WMT HD DIS INTC CSCO ORCL NFLX ADBE CRM AMD QCOM T VZ MRK BA".split()
COST = 0.0005          # US stocks 5 bps per side (fee + slippage)
GAP_TH = 0.02
LAST = pd.Timestamp("2026-10-06")
IS_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")
p1 = int(dt.datetime(2010, 1, 1, tzinfo=dt.timezone.utc).timestamp())
p2 = int(dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc).timestamp())

# ---------------- load ----------------
frames, sources = {}, []
for t in T:
    fn = os.path.join(DATA, f"{t}.json")
    raw = open(fn, "rb").read()
    js = json.loads(raw)
    r = js["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    ts = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
    df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                       "adj": r["indicators"]["adjclose"][0]["adjclose"]},
                      index=pd.DatetimeIndex(ts.tz_localize(None).normalize(), name="date"))
    df = df.dropna(subset=["open", "close"])
    df = df[(df["open"] > 0) & (df["close"] > 0)]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index <= LAST]
    frames[t] = df
    sources.append({"name": f"Yahoo chart API daily {t}",
                    "url": f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit&includeAdjustedClose=true",
                    "start": str(df.index[0].date()), "end": str(df.index[-1].date()), "rows": int(len(df)),
                    "sha256": hashlib.sha256(raw).hexdigest()})

# ---------------- signals (only close_{t-1} and open_t) ----------------
def make_signals(frames):
    rows = []
    for t, df in frames.items():
        prev_close = df["close"].shift(1)
        prev_date = pd.Series(df.index, index=df.index).shift(1)
        gap = df["open"] / prev_close - 1.0
        sig = gap >= GAP_TH
        s = df[sig].copy()
        s["ticker"] = t
        s["gap"] = gap[sig]
        s["prev_close"] = prev_close[sig]
        s["prev_date"] = prev_date[sig]
        rows.append(s)
    out = pd.concat(rows).reset_index().rename(columns={"index": "date"})
    return out

sig = make_signals(frames)

# ---- self-check 1: signal bar (t-1 close) strictly before execution bar (t) ----
chk_sig_before_exec = bool((sig["prev_date"] < sig["date"]).all())
# ---- self-check 2: signal set invariant to day-t high/low/close (no look-ahead into the trade day) ----
perturbed = {}
rng = np.random.default_rng(0)
for t, df in frames.items():
    d = df.copy()
    # destroy same-day info that is NOT allowed in the signal; keep open_t and close_{t-1} structure
    # (close_t is needed as close_{t-1} for day t+1, so we perturb only high/low and test close separately)
    d["high"] = d["high"] * rng.uniform(0.5, 2.0, len(d))
    d["low"] = d["low"] * rng.uniform(0.5, 2.0, len(d))
    perturbed[t] = d
sig_p = make_signals(perturbed)
chk_invariant_hl = bool(len(sig_p) == len(sig) and (sig_p[["date", "ticker"]].values == sig[["date", "ticker"]].values).all())
# close_t perturbation: changing close on the last day of each series must not change signals on that day
chk_close_same_day = True
for t, df in frames.items():
    d = df.copy(); d.iloc[-1, d.columns.get_loc("close")] *= 3.0
    a = make_signals({t: df}); b = make_signals({t: d})
    if len(a) != len(b) or not (a["date"].values == b["date"].values).all():
        chk_close_same_day = False

# ---------------- trade returns ----------------
def trade_returns(s, side, c):
    o, cl = s["open"].values, s["close"].values
    if side == "long":   # buy open*(1+c), sell close*(1-c)
        return (cl * (1 - c)) / (o * (1 + c)) - 1.0
    else:                # short open*(1-c), cover close*(1+c); P&L per $ of entry notional
        return (o * (1 - c) - cl * (1 + c)) / (o * (1 - c))

all_days = sorted(set().union(*[set(df.index) for df in frames.values()]))
all_days = pd.DatetimeIndex(all_days)

def run(side, c, start, end):
    s = sig[(sig["date"] >= start) & (sig["date"] <= end)].copy()
    s["ret"] = trade_returns(s, side, c)
    days = all_days[(all_days >= start) & (all_days <= end)]
    day_ret = s.groupby("date")["ret"].mean()           # equal weight across same-day signals
    n_day = s.groupby("date")["ret"].size()
    r = day_ret.reindex(days).fillna(0.0)
    eq = (1 + r).cumprod()
    # dollar P&L per trade: equity at start of day / n_signals_that_day * ret
    eq_prev = eq.shift(1).fillna(1.0)
    s["pnl"] = s.apply(lambda x: eq_prev[x["date"]] / n_day[x["date"]] * x["ret"], axis=1) if len(s) else []
    gw = s.loc[s["pnl"] > 0, "pnl"].sum(); gl = -s.loc[s["pnl"] < 0, "pnl"].sum()
    yrs = (days[-1] - days[0]).days / 365.25
    dd = (eq / eq.cummax() - 1).min()
    return dict(trades=int(len(s)), win_rate_pct=float((s["ret"] > 0).mean() * 100) if len(s) else None,
                pf=float(gw / gl) if gl > 0 else None, net_return_pct=float((eq.iloc[-1] - 1) * 100),
                cagr_pct=float((eq.iloc[-1] ** (1 / yrs) - 1) * 100), max_dd_pct=float(dd * 100),
                exposure_pct=float((r.index.isin(day_ret.index)).mean() * 100),
                signal_days=int(len(day_ret)), avg_trade_net_bps=float(s["ret"].mean() * 1e4) if len(s) else None,
                avg_names_per_signal_day=float(n_day.mean()) if len(n_day) else None,
                start=str(days[0].date()), end=str(days[-1].date())), eq

def bench(start, end, c=COST):
    days = all_days[(all_days >= start) & (all_days <= end)]
    d0 = days[0]
    names = [t for t, df in frames.items() if d0 in df.index]
    rel = pd.concat([frames[t]["adj"].reindex(days).ffill() / frames[t]["adj"].loc[d0] for t in names], axis=1)
    eq = rel.mean(axis=1) * (1 - c)                        # buy at first close with cost
    eq.iloc[-1] = eq.iloc[-1] * (1 - c)                     # sell at last close with cost
    yrs = (days[-1] - days[0]).days / 365.25
    dd = (eq / eq.cummax() - 1).min()
    return dict(net_return_pct=float((eq.iloc[-1] - 1) * 100), cagr_pct=float((eq.iloc[-1] ** (1 / yrs) - 1) * 100),
                max_dd_pct=float(dd * 100), n_names=len(names), excluded=[t for t in T if t not in names])

periods = {"IS": (all_days[0], IS_END), "OOS": (OOS_START, LAST), "FULL": (all_days[0], LAST)}
res, rows = {}, []
for lab, side in (("A", "long"), ("B", "short")):
    res[lab] = {}
    for p, (a, b) in periods.items():
        m, eq = run(side, COST, a, b)
        m2, _ = run(side, 2 * COST, a, b)
        m0, _ = run(side, 0.0, a, b)
        bm = bench(a, b)
        m["net_return_2x_cost_pct"] = m2["net_return_pct"]
        m["pf_2x_cost"] = m2["pf"]
        m["net_return_zero_cost_pct"] = m0["net_return_pct"]
        m["bench"] = bm
        res[lab][p] = m
        rows.append(dict(period=f"{lab}-{p}", trades=m["trades"], win_rate_pct=round(m["win_rate_pct"], 2),
                         pf=round(m["pf"], 3), net_return_pct=round(m["net_return_pct"], 2), cagr_pct=round(m["cagr_pct"], 2),
                         max_dd_pct=round(m["max_dd_pct"], 2), exposure_pct=round(m["exposure_pct"], 2),
                         bench_net_return_pct=round(bm["net_return_pct"], 2), bench_max_dd_pct=round(bm["max_dd_pct"], 2),
                         net_return_2x_cost_pct=round(m["net_return_2x_cost_pct"], 2),
                         note=f"{m['start']}..{m['end']}; avg trade net {m['avg_trade_net_bps']:.1f} bps; "
                              f"0-cost net {m['net_return_zero_cost_pct']:.1f}%; PF@2x {m['pf_2x_cost']:.3f}; "
                              f"bench EW B&H adjclose {bm['n_names']} names (excl {','.join(bm['excluded']) or '-'}), bench CAGR {bm['cagr_pct']:.2f}%"))

# ---------------- verdict (mechanical, OOS) ----------------
def verdict(m):
    bm = m["bench"]
    if m["net_return_pct"] <= 0 or (m["pf"] is not None and m["pf"] < 1.0) or \
       (m["net_return_pct"] < bm["net_return_pct"] and m["max_dd_pct"] < bm["max_dd_pct"]):
        return "FAIL"
    if m["trades"] < 30:
        return "INCONCLUSIVE"
    ratio = m["net_return_pct"] / abs(m["max_dd_pct"]) if m["max_dd_pct"] < 0 else np.inf
    bratio = bm["net_return_pct"] / abs(bm["max_dd_pct"])
    if m["pf"] >= 1.2 and ratio > bratio and m["net_return_2x_cost_pct"] > 0:
        return "PASS_CANDIDATE"
    return "INCONCLUSIVE"

ver = {lab: verdict(res[lab]["OOS"]) for lab in ("A", "B")}

# extreme gap sanity list
big = sig.sort_values("gap", ascending=False).head(10)[["date", "ticker", "gap", "prev_close", "open", "close"]]

diag = {}
for p, (a, b) in periods.items():
    s = sig[(sig["date"] >= a) & (sig["date"] <= b)].copy()
    for side in ("long", "short"):
        s["r"] = trade_returns(s, side, COST)
        d = s.groupby("date")["r"].mean()
        diag[f"{side}-{p}"] = dict(signal_days=int(len(d)), mean_day_net_pct=float(d.mean() * 100),
                                   std_day_pct=float(d.std() * 100),
                                   one_name_day_share=float((s.groupby("date").size() == 1).mean()))
notes = dict(survivorship="Universe = current US megacaps chosen with hindsight (survivorship/selection bias in favour of longs).",
             borrow="C15B ignores borrow cost/locate (intraday short of megacaps; overnight borrow fee not incurred).",
             benchmark="Equal-weight buy&hold on Yahoo adjclose (total return), names with data on period start day; 5 bps in/out.",
             fills="Entry at daily open price, exit at daily close; real opening-auction/closing-auction fills assumed.",
             unresolved_verdict_rule="If not FAIL and not all PASS criteria -> INCONCLUSIVE.")
out = dict(id="C15", rows=rows, verdicts=ver, metrics=res, day_level_diag=diag, notes=notes, data_sources=sources,
           self_checks=dict(signal_bar_before_execution_bar=chk_sig_before_exec,
                            signals_invariant_to_same_day_high_low=chk_invariant_hl,
                            signals_invariant_to_same_day_close=chk_close_same_day,
                            intrabar_stop_rule="not applicable: no stop, exit at same-day close",
                            note="gap uses open_t and close_{t-1}; entry fills at open_t (idealised: fill at opening print)"),
           largest_gaps=[dict(date=str(x.date.date()), ticker=x.ticker, gap_pct=round(x.gap * 100, 2),
                              prev_close=round(x.prev_close, 4), open=round(x.open, 4), close=round(x.close, 4)) for x in big.itertuples()])
json.dump(out, open(os.path.join(HERE, "result.json"), "w"), indent=1, default=str)
for r in rows: print(r)
print("verdicts", ver)
print("self-checks", out["self_checks"])
print(big.to_string())
