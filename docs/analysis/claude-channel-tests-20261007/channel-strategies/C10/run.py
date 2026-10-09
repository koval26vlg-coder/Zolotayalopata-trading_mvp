# C10 SPOT_GRID_WEEKLY -- frozen rule from SPEC2.md (2026-10-07). No tuning.
# BTCUSDT 1h (Binance spot). Each Monday 00:00 UTC: rebalance to 50/50 at open (costs), 7 levels open*(1+k*1.5%), k=-3..3,
# 6 active grid slots of 1/6 sleeve each. Upward cross -> sell unit, downward cross -> buy unit; re-arm after opposite
# neighbour fills (classic slot grid). Costs per fill 20 bps (crypto spot). Mark at hourly closes.
# Benchmark: 50/50 BTC/USDT rebalanced weekly at the same Monday opens (no grid).
import hashlib, json, os, sys, time, urllib.request
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RAW = os.path.join(DATA, "binance_BTCUSDT_1h_klines_raw.json")
CUTOFF_CLOSE_MS = int(pd.Timestamp("2026-10-06 23:59:59.999", tz="UTC").value // 10**6)
IS_END = pd.Timestamp("2022-12-31 23:59:59", tz="UTC")
COST = 0.0020          # 20 bps per side, crypto spot
STEP = 0.015           # 1.5% level spacing
KS = list(range(-3, 4))
START_CAPITAL = 100.0


# ---------------------------------------------------------------- data
def download():
    urls = ["https://api.binance.com/api/v3/klines", "https://data-api.binance.vision/api/v3/klines"]
    last_err = None
    for base in urls:
        try:
            rows, start = [], 1502928000000  # 2017-08-17 00:00 UTC (listing)
            while True:
                u = f"{base}?symbol=BTCUSDT&interval=1h&startTime={start}&limit=1000"
                with urllib.request.urlopen(u, timeout=30) as r:
                    chunk = json.loads(r.read().decode())
                if not chunk:
                    break
                rows.extend(chunk)
                start = chunk[-1][0] + 3600_000
                if chunk[-1][6] >= CUTOFF_CLOSE_MS or len(chunk) < 1000:
                    break
                time.sleep(0.15)
            with open(RAW, "w") as f:
                json.dump({"source": base, "symbol": "BTCUSDT", "interval": "1h", "rows": rows}, f)
            return base
        except Exception as e:  # one alternative public source, then give up
            last_err = e
    raise RuntimeError(f"download failed: {last_err}")


def load():
    if not os.path.exists(RAW):
        download()
    with open(RAW) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw["rows"]).iloc[:, :7]
    df.columns = ["ot", "o", "h", "l", "c", "v", "ct"]
    for col in "ohlcv":
        df[col] = df[col].astype(float)
    df = df[df["ct"] <= CUTOFF_CLOSE_MS].copy()          # only bars closed by 2026-10-06 23:59 UTC
    df = df.drop_duplicates("ot").sort_values("ot").reset_index(drop=True)
    df["t"] = pd.to_datetime(df["ot"], unit="ms", utc=True)
    first_monday = df.loc[(df.t.dt.dayofweek == 0) & (df.t.dt.hour == 0), "t"].iloc[0]
    df = df[df.t >= first_monday].reset_index(drop=True)   # start trading at first Monday 00:00 UTC
    return df, raw["source"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- simulation
def simulate(df, cost=COST, path_mode="standard", same_bar_rearm=True, with_grid=True):
    """path_mode: 'standard' = bullish bar O-L-H-C, bearish O-H-L-C; 'reverse' = opposite order (sensitivity only).
    same_bar_rearm: if False, an order armed by a fill inside a bar becomes active only from the next bar (sensitivity)."""
    t = df["t"].values
    O, H, L, C = (df[x].values for x in "ohlc")
    week = (df["t"].dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time).values  # Monday 00:00 of bar's week
    n = len(df)
    btc, usdt = 0.0, START_CAPITAL
    eq = np.empty(n); wbtc = np.empty(n)
    fills, trips, rebal = [], [], []
    open_lots = {}
    slot_state = init_state = None
    levels = None; q = 0.0; wk_start_idx = -1; cur_week = None
    armed_bar = None

    def close_lot(j, price, ts, i_bar, reason):
        lot = open_lots.pop(j)
        if lot["side"] == "short":   # sold at lot price, buy back at price
            pnl = lot["q"] * (lot["px"] * (1 - cost) - price * (1 + cost))
        else:                         # bought at lot price, sell at price
            pnl = lot["q"] * (price * (1 - cost) - lot["px"] * (1 + cost))
        trips.append(dict(open_t=lot["t"], close_t=ts, side=lot["side"], entry=lot["px"], exit=price,
                          q=lot["q"], pnl=pnl, reason=reason, open_bar=lot["bar"], close_bar=i_bar))

    for i in range(n):
        if week[i] != cur_week:
            # ---- weekly reset at the open of the first bar of the new week
            px = O[i]
            for j in list(open_lots):
                close_lot(j, px, t[i], i, "weekly_reset")
            vb = btc * px
            if True:  # rebalance applies to strategy and benchmark alike
                if vb > usdt:
                    x = (vb - usdt) / (2 - cost); btc -= x / px; usdt += x * (1 - cost); side = "sell"
                else:
                    x = (usdt - vb) / (2 + cost); btc += x / px; usdt -= x * (1 + cost); side = "buy"
                rebal.append(dict(t=t[i], px=px, notional=x, side=side))
            cur_week = week[i]; wk_start_idx = i
            levels = np.array([px * (1 + k * STEP) for k in KS])   # uses only this bar's open (known at placement)
            q = btc / 3.0
            # slot j between levels[j] and levels[j+1]; j>=3 holds BTC (sell at levels[j+1]), j<3 holds USDT (buy at levels[j])
            slot_state = ["U", "U", "U", "B", "B", "B"]
            init_state = list(slot_state)
            armed_bar = [-1] * 6
            prev = px
        else:
            prev = C[i - 1]
        if with_grid:
            if path_mode == "standard":
                pts = [prev, O[i], L[i], H[i], C[i]] if C[i] >= O[i] else [prev, O[i], H[i], L[i], C[i]]
            else:
                pts = [prev, O[i], H[i], L[i], C[i]] if C[i] >= O[i] else [prev, O[i], L[i], H[i], C[i]]
            for a, b in zip(pts[:-1], pts[1:]):
                if b > a:
                    for li in range(7):                       # ascending
                        lv = levels[li]
                        if a < lv < b and li >= 1:
                            j = li - 1
                            if slot_state[j] == "B" and (same_bar_rearm or armed_bar[j] < i):
                                if btc >= q * (1 - 1e-9):
                                    btc -= q; usdt += q * lv * (1 - cost)
                                    fills.append(dict(t=t[i], bar=i, side="sell", px=lv, q=q, wk=wk_start_idx))
                                    slot_state[j] = "U"; armed_bar[j] = i
                                    if init_state[j] == "B":
                                        open_lots[j] = dict(side="short", px=lv, q=q, t=t[i], bar=i)
                                    else:
                                        close_lot(j, lv, t[i], i, "grid")
                elif b < a:
                    for li in range(6, -1, -1):               # descending
                        lv = levels[li]
                        if b < lv < a and li <= 5:
                            j = li
                            if slot_state[j] == "U" and (same_bar_rearm or armed_bar[j] < i):
                                if usdt >= q * lv * (1 + cost) * (1 - 1e-9):
                                    btc += q; usdt -= q * lv * (1 + cost)
                                    fills.append(dict(t=t[i], bar=i, side="buy", px=lv, q=q, wk=wk_start_idx))
                                    slot_state[j] = "B"; armed_bar[j] = i
                                    if init_state[j] == "U":
                                        open_lots[j] = dict(side="long", px=lv, q=q, t=t[i], bar=i)
                                    else:
                                        close_lot(j, lv, t[i], i, "grid")
        eq[i] = btc * C[i] + usdt
        wbtc[i] = btc * C[i] / eq[i]
    # end of data: mark-close remaining lots at last close (with cost, as if liquidated) for round-trip stats
    for j in list(open_lots):
        close_lot(j, C[-1], t[-1], n - 1, "end_mark")
    return dict(eq=pd.Series(eq, index=df["t"]), wbtc=pd.Series(wbtc, index=df["t"]),
                fills=pd.DataFrame(fills), trips=pd.DataFrame(trips), rebal=pd.DataFrame(rebal))


# ---------------------------------------------------------------- metrics
def period_slices(eq_index):
    first, last = eq_index[0], eq_index[-1]
    return {"IS": (first, IS_END), "OOS": (IS_END, last), "FULL": (first, last)}


def metrics(res, start, end, is_first_period, bench=False):
    eq = res["eq"]
    if is_first_period:
        e0 = START_CAPITAL; t0 = eq.index[0]
        seg = eq[(eq.index >= start) & (eq.index <= end)]
    else:
        prior = eq[eq.index <= start]
        e0 = prior.iloc[-1]; t0 = prior.index[-1]
        seg = eq[(eq.index > start) & (eq.index <= end)]
    curve = pd.concat([pd.Series([e0], index=[t0]), seg])
    net = curve.iloc[-1] / e0 - 1
    days = (curve.index[-1] - t0).total_seconds() / 86400 + 1 / 24
    cagr = (1 + net) ** (365.25 / days) - 1
    dd_h = (curve / curve.cummax() - 1).min()
    daily = curve.resample("1D").last().dropna()
    daily = pd.concat([pd.Series([e0], index=[t0]), daily])
    dd_d = (daily / daily.cummax() - 1).min()
    w = res["wbtc"]; w = w[(w.index > (start if not is_first_period else start - pd.Timedelta(seconds=1))) & (w.index <= end)]
    out = dict(net=net * 100, cagr=cagr * 100, dd_h=dd_h * 100, dd_d=dd_d * 100, expo=w.mean() * 100,
               start=str(t0), end=str(curve.index[-1]), e0=e0, e1=curve.iloc[-1])
    if not bench:
        f = res["fills"]; tr = res["trips"]
        ft = pd.to_datetime(f["t"], utc=True); ct = pd.to_datetime(tr["close_t"], utc=True)
        lo = start if not is_first_period else start - pd.Timedelta(seconds=1)
        fsel = f[(ft > lo) & (ft <= end)]
        tsel = tr[(ct > lo) & (ct <= end)]
        gw = tsel.loc[tsel.pnl > 0, "pnl"].sum(); gl = -tsel.loc[tsel.pnl <= 0, "pnl"].sum()
        out.update(fills=len(fsel), trips=len(tsel), win=(tsel.pnl > 0).mean() * 100 if len(tsel) else None,
                   pf=(gw / gl) if gl > 0 else None, trips_grid=int((tsel.reason == "grid").sum()),
                   trips_reset=int((tsel.reason != "grid").sum()),
                   reset_pnl=float(tsel.loc[tsel.reason != "grid", "pnl"].sum()),
                   grid_pnl=float(tsel.loc[tsel.reason == "grid", "pnl"].sum()))
    else:
        rb = res["rebal"]; rt = pd.to_datetime(rb["t"], utc=True)
        lo = start if not is_first_period else start - pd.Timedelta(seconds=1)
        out.update(rebalances=int(((rt > lo) & (rt <= end)).sum()))
    return out


# ---------------------------------------------------------------- self-checks (look-ahead / integrity)
def self_checks(df, res):
    chk = {}
    ot = df["ot"].values
    chk["monotonic_unique_ts"] = bool(np.all(np.diff(ot) > 0))
    chk["ohlc_consistent"] = bool(((df.h >= df[["o", "c"]].max(axis=1)) & (df.l <= df[["o", "c"]].min(axis=1))).all())
    gaps = np.diff(ot) // 3600_000 - 1
    chk["missing_hourly_bars"] = int(gaps[gaps > 0].sum())
    chk["last_bar_close_utc"] = str(pd.to_datetime(df["ct"].iloc[-1], unit="ms", utc=True))
    f = res["fills"]
    # every fill price must lie inside the price path segment of its own bar (bar range or prev-close gap)
    prevc = df["c"].shift(1).values
    lo = np.minimum(df["l"].values, np.nan_to_num(prevc, nan=np.inf))
    hi = np.maximum(df["h"].values, np.nan_to_num(prevc, nan=-np.inf))
    b = f["bar"].values
    chk["fills_within_bar_path"] = bool(np.all((f.px.values >= lo[b] - 1e-9) & (f.px.values <= hi[b] + 1e-9)))
    # levels of a week are derived from the week's first-bar open; fills only at bars >= that bar, same week
    chk["fills_not_before_level_bar"] = bool(np.all(f["bar"].values >= f["wk"].values))
    wk = df["t"].dt.tz_localize(None).dt.to_period("W-SUN").values
    chk["fills_same_week_as_levels"] = bool(np.all(wk[f["bar"].values] == wk[f["wk"].values]))
    # level bars are Mondays (or first available bar of the week)
    lvl_bars = np.unique(f["wk"].values)
    chk["level_bars_monday"] = float(np.mean(df["t"].iloc[lvl_bars].dt.dayofweek.values == 0))
    # truncation test: rerunning on data cut at T must reproduce equity up to T exactly (no future dependence)
    trunc_ok = True
    for frac in (0.37, 0.71):
        k = int(len(df) * frac)
        r2 = simulate(df.iloc[:k].reset_index(drop=True))
        trunc_ok &= bool(np.allclose(r2["eq"].values[: k - 1], res["eq"].values[: k - 1], rtol=0, atol=1e-9))
    chk["truncation_no_lookahead"] = trunc_ok
    tr = res["trips"]
    chk["roundtrip_close_after_open"] = bool(np.all(pd.to_datetime(tr.close_t) >= pd.to_datetime(tr.open_t)))
    chk["same_bar_roundtrips"] = int((tr.open_bar == tr.close_bar).sum())
    chk["grid_roundtrips_all_positive_by_construction"] = bool((tr.loc[tr.reason == "grid", "pnl"] > 0).all())
    return chk


def r(x, d=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


def main():
    df, source = load()
    print(f"bars={len(df)} first={df.t.iloc[0]} last={df.t.iloc[-1]} source={source}")
    base = simulate(df)
    x2 = simulate(df, cost=2 * COST)
    bench = simulate(df, with_grid=False)
    bench2 = simulate(df, cost=2 * COST, with_grid=False)
    sens_rev = simulate(df, path_mode="reverse")
    sens_norearm = simulate(df, same_bar_rearm=False)
    sl = period_slices(base["eq"].index)
    rows, detail = [], {}
    for p, (s, e) in sl.items():
        first = p in ("IS", "FULL")
        m = metrics(base, s, e, first); m2 = metrics(x2, s, e, first)
        mb = metrics(bench, s, e, first, bench=True); mb2 = metrics(bench2, s, e, first, bench=True)
        ms1 = metrics(sens_rev, s, e, first); ms2 = metrics(sens_norearm, s, e, first)
        detail[p] = dict(strategy=m, strategy_2x=m2, bench=mb, bench_2x=mb2, sens_reverse_path=ms1, sens_no_same_bar_rearm=ms2)
        ratio_s = m["net"] / abs(m["dd_h"]) if m["dd_h"] < 0 else None
        ratio_b = mb["net"] / abs(mb["dd_h"]) if mb["dd_h"] < 0 else None
        rows.append(dict(period=p, trades=m["fills"], win_rate_pct=r(m["win"]), pf=r(m["pf"], 3),
                         net_return_pct=r(m["net"]), cagr_pct=r(m["cagr"]), max_dd_pct=r(m["dd_h"]),
                         exposure_pct=r(m["expo"]), bench_net_return_pct=r(mb["net"]), bench_max_dd_pct=r(mb["dd_h"]),
                         net_return_2x_cost_pct=r(m2["net"]),
                         note=(f"{m['start'][:16]}..{m['end'][:16]}; trades=исполнения сетки ({m['fills']}); "
                               f"раунд-трипов {m['trips']} (сетка {m['trips_grid']}, закрыто ресетом {m['trips_reset']}); "
                               f"PnL сетки {m['grid_pnl']:.2f}, PnL ресетов {m['reset_pnl']:.2f} (на старт $100); "
                               f"бенч CAGR {mb['cagr']:.2f}%, бенч 2x {mb2['net']:.2f}%; MaxDD часовые метки "
                               f"(дневные: стр {m['dd_d']:.2f}%, бенч {mb['dd_d']:.2f}%); "
                               f"return/DD стр {ratio_s if ratio_s is None else round(ratio_s,3)} vs бенч "
                               f"{ratio_b if ratio_b is None else round(ratio_b,3)}; "
                               f"чувств.: обратный путь бара {ms1['net']:.2f}% PF {r(ms1['pf'],3)}, "
                               f"без перевзвода в том же баре {ms2['net']:.2f}% PF {r(ms2['pf'],3)}")))
    # ---- mechanical verdict on OOS
    o = detail["OOS"]; m, mb, m2 = o["strategy"], o["bench"], o["strategy_2x"]
    ratio_s = m["net"] / abs(m["dd_h"]); ratio_b = mb["net"] / abs(mb["dd_h"])
    fail_reasons = []
    if m["net"] <= 0: fail_reasons.append("OOS net <= 0")
    if m["pf"] is not None and m["pf"] < 1.0: fail_reasons.append("PF < 1.0")
    if m["net"] < mb["net"] and m["dd_h"] < mb["dd_h"]: fail_reasons.append("хуже бенчмарка и по доходности, и по MaxDD")
    if fail_reasons:
        verdict = "FAIL"
    elif m["trips"] < 30:
        verdict = "INCONCLUSIVE"
    elif m["net"] > 0 and (m["pf"] or 0) >= 1.2 and ratio_s > ratio_b and m2["net"] > 0:
        verdict = "PASS_CANDIDATE"
    else:
        verdict = "INCONCLUSIVE"
    chk = self_checks(df, base)
    out = dict(id="C10", verdict=verdict, fail_reasons=fail_reasons, oos_ratio_strategy=ratio_s, oos_ratio_bench=ratio_b,
               rows=rows, detail=detail, self_checks=chk, source=source,
               data_file=os.path.basename(RAW), sha256=sha256(RAW), bars=len(df),
               first_bar=str(df.t.iloc[0]), last_bar=str(df.t.iloc[-1]),
               rebalances_total=len(base["rebal"]), fills_total=len(base["fills"]), trips_total=len(base["trips"]))
    with open(os.path.join(BASE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(dict(verdict=verdict, fail=fail_reasons, ratio_s=ratio_s, ratio_b=ratio_b, checks=chk), ensure_ascii=False, default=str, indent=1))
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
