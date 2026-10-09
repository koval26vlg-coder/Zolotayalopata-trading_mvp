"""Independent re-implementation of SPEC2 C10 SPOT_GRID_WEEKLY (verifier).

Model (own reading of SPEC2):
- BTCUSDT 1h Binance spot, bars with open >= Mon 2017-08-21 00:00 UTC and close <= 2026-10-06 23:59:59 UTC.
- Each Monday 00:00 UTC bar: at its open P0 rebalance to 50/50 (cost c on traded notional), then
  7 levels L_k = P0*(1+k*0.015), k=-3..3 -> 6 cells (between adjacent levels).
  Cells above P0 start holding BTC (sell at upper level), cells below start holding USDT (buy at lower level).
  Unit = fixed BTC quantity q = (E_after_rebalance/6)/P0 (primary) or fixed quote E/6 (sensitivity).
  A cell in BTC state sells q at its upper level when the price path rises strictly above it;
  then it is in USDT state and buys q at its lower level when the path falls strictly below it
  (== "one fill per level per direction, re-arm after opposite neighbour fills").
  Fills at the level price, cost c per fill. Inventory checks (global B/U).
- Intra-bar path: prev_close -> open -> (bull: L,H | bear: H,L) -> close  (primary, "shorter path");
  sensitivity: reversed.
- Marks at every hourly close. Benchmark: same weekly 50/50 rebalance, no grid.
- PF / win rate on long BTC lots per cell: opened by grid buy (or initial allocation at P0, no fee),
  closed by grid sell or at next Monday open (reset, fee charged for PF accounting only).
"""
import json, hashlib, math, sys
import numpy as np
import pandas as pd

DATA = r"C:/Users/koval/AppData/Local/Temp/claude/C--Users-koval------------/c3d42fa1-b83c-49f0-8567-13ebcd1f7317/scratchpad/st/C10/data/binance_BTCUSDT_1h_klines_raw.json"
START_MS = 1503273600000           # Mon 2017-08-21 00:00 UTC
END_CLOSE_MS = 1791331199999       # 2026-10-06 23:59:59.999 UTC
OOS_MS = 1672531200000             # 2023-01-01 00:00 UTC
WEEK_MS = 604800000
STEP = 0.015


def load():
    raw = open(DATA, 'rb').read()
    sha = hashlib.sha256(raw).hexdigest()
    d = json.loads(raw)
    rows = [r for r in d['rows'] if r[0] >= START_MS and r[6] <= END_CLOSE_MS]
    df = pd.DataFrame({'t': [r[0] for r in rows], 'o': [float(r[1]) for r in rows], 'h': [float(r[2]) for r in rows],
                       'l': [float(r[3]) for r in rows], 'c': [float(r[4]) for r in rows]})
    assert df.t.is_monotonic_increasing and df.t.is_unique
    assert (df.h >= df[['o', 'c']].max(axis=1)).all() and (df.l <= df[['o', 'c']].min(axis=1)).all()
    df['week'] = (df.t - START_MS) // WEEK_MS
    df['wstart'] = df.week.ne(df.week.shift())
    # every week start must be exactly Monday 00:00
    assert ((df.t[df.wstart] - START_MS) % WEEK_MS == 0).all()
    return df, sha


def rebalance(B, U, P, c):
    """Rebalance to 50/50 value at price P; cost c on traded notional. returns B,U,cost"""
    vb = B * P
    if U > vb:   # buy BTC worth x
        x = (U - vb) / (2 + c)
        return B + x / P, U - x * (1 + c), x * c
    else:
        x = (vb - U) / (2 - c)
        return B - x / P, U + x * (1 - c), x * c


def run(df, c=0.002, path='short', strict=True, sizing='qty', bench=False, start_ms=None, record=False, same_bar_rearm=True):
    t = df.t.values; o = df.o.values; h = df.h.values; l = df.l.values; cl = df.c.values; ws = df.wstart.values
    n = len(t)
    i0 = 0 if start_ms is None else int(np.searchsorted(t, start_ms))
    while not ws[i0]:
        i0 += 1
    B, U = 0.0, 100.0
    eq = np.full(n, np.nan); btcw = np.full(n, np.nan)
    fills = []            # (t, side, price, qty, week)
    rts = []              # (t_close, pnl, kind)
    levels = None; state = None; qty = None; basis = None
    prev_close = None
    lastbar = [-1] * 6
    for i in range(i0, n):
        if ws[i]:
            P0 = o[i]
            # reset: close open lots (PF accounting only) at P0 with fee
            if state is not None and not bench:
                for j in range(6):
                    if state[j] == 1:
                        q = qty[j]
                        rts.append((t[i], q * P0 * (1 - c) - basis[j], 'reset'))
            B, U, _ = rebalance(B, U, P0, c)
            if not bench:
                E = B * P0 + U
                levels = [P0 * (1 + k * STEP) for k in range(-3, 4)]   # index 0..6
                # cell j between levels[j] and levels[j+1]; j=0..5 ; j>=3 above P0 -> BTC
                state = [0, 0, 0, 1, 1, 1]
                unit_usdt = E / 6.0
                qty = [0.0] * 6; basis = [0.0] * 6
                for j in range(3, 6):
                    qty[j] = (unit_usdt / P0) if sizing == 'qty' else (unit_usdt / P0)
                    basis[j] = qty[j] * P0          # initial allocation, no entry fee
                for j in range(0, 3):
                    qty[j] = unit_usdt / P0 if sizing == 'qty' else 0.0
            pts = [o[i]]
        else:
            pts = [prev_close, o[i]]
        if not bench:
            bull = cl[i] >= o[i]
            if path == 'short':
                mid = [l[i], h[i]] if bull else [h[i], l[i]]
            else:
                mid = [h[i], l[i]] if bull else [l[i], h[i]]
            pts = pts + mid + [cl[i]]
            for a, b in zip(pts[:-1], pts[1:]):
                if b > a:   # up: sell cells in BTC state whose upper level is passed, ascending
                    for j in range(6):
                        if state[j] == 1 and (same_bar_rearm or lastbar[j] != i):
                            L = levels[j + 1]
                            if (L < b) if strict else (L <= b):
                                q = qty[j]
                                if B + 1e-15 >= q:
                                    B -= q; U += q * L * (1 - c)
                                    rts.append((t[i], q * L * (1 - c) - basis[j], 'grid'))
                                    fills.append((t[i], -1, L, q, j))
                                    state[j] = 0; lastbar[j] = i
                                    if sizing == 'quote':
                                        qty[j] = 0.0
                elif b < a:  # down: buy cells in USDT state whose lower level is passed, descending
                    for j in range(5, -1, -1):
                        if state[j] == 0 and (same_bar_rearm or lastbar[j] != i):
                            L = levels[j]
                            if (L > b) if strict else (L >= b):
                                if sizing == 'qty':
                                    q = qty[j]
                                else:
                                    q = (E / 6.0) / L
                                cost = q * L * (1 + c)
                                if U + 1e-12 >= cost:
                                    U -= cost; B += q
                                    basis[j] = cost; qty[j] = q
                                    fills.append((t[i], 1, L, q, j))
                                    state[j] = 1; lastbar[j] = i
        prev_close = cl[i]
        eq[i] = U + B * cl[i]
        btcw[i] = B * cl[i] / eq[i]
    return dict(eq=eq, btcw=btcw, fills=fills, rts=rts, i0=i0)


def maxdd(x):
    x = np.asarray(x, float)
    peak = np.maximum.accumulate(x)
    return float((x / peak - 1).min() * 100)


def metrics(df, res, lo_ms, hi_ms, start_mark=None):
    t = df.t.values
    eq = res['eq']
    m = (t >= lo_ms) & (t < hi_ms) & ~np.isnan(eq)
    idx = np.where(m)[0]
    # start mark: equity at last close before lo (or initial 100)
    prev = np.where((t < lo_ms) & ~np.isnan(eq))[0]
    E0 = eq[prev[-1]] if len(prev) else 100.0
    series = np.concatenate([[E0], eq[idx]])
    ret = series[-1] / E0 - 1
    t0 = (t[prev[-1]] + 3600000) if len(prev) else t[idx[0]]
    t1 = t[idx[-1]] + 3600000
    yrs = (t1 - t0) / (365.25 * 86400000)
    cagr = (1 + ret) ** (1 / yrs) - 1 if ret > -1 else -1
    # daily marks: last bar of each UTC day
    days = pd.Series(eq[idx], index=pd.to_datetime(t[idx], unit='ms')).resample('1D').last().dropna().values
    dd_d = maxdd(np.concatenate([[E0], days]))
    dd_h = maxdd(series)
    fills = [f for f in res['fills'] if lo_ms <= f[0] < hi_ms]
    rts = [r for r in res['rts'] if lo_ms <= r[0] < hi_ms]
    pnl = np.array([r[1] for r in rts]) if rts else np.array([])
    gw = pnl[pnl > 0].sum() if len(pnl) else 0.0
    gl = -pnl[pnl < 0].sum() if len(pnl) else 0.0
    pf = gw / gl if gl > 0 else float('inf')
    wr = (pnl > 0).mean() * 100 if len(pnl) else float('nan')
    expo = float(np.nanmean(res['btcw'][idx]) * 100)
    return dict(ret=ret * 100, cagr=cagr * 100, dd_h=dd_h, dd_d=dd_d, fills=len(fills), rts=len(rts),
                rts_grid=sum(1 for r in rts if r[2] == 'grid'), rts_reset=sum(1 for r in rts if r[2] == 'reset'),
                pf=pf, wr=wr, expo=expo)


PERIODS = {'IS': (START_MS, OOS_MS), 'OOS': (OOS_MS, END_CLOSE_MS + 1), 'FULL': (START_MS, END_CLOSE_MS + 1)}


def table(df, res):
    return {p: metrics(df, res, a, b) for p, (a, b) in PERIODS.items()}


def fmt(d):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


if __name__ == '__main__':
    df, sha = load()
    print('sha256', sha, 'rows', len(df), pd.to_datetime(df.t.iloc[0], unit='ms'), pd.to_datetime(df.t.iloc[-1], unit='ms'))
    base = run(df)
    bench = run(df, bench=True)
    base2 = run(df, c=0.004)
    bench2 = run(df, c=0.004, bench=True)
    out = {}
    for name, r in [('grid', base), ('bench', bench), ('grid_2x', base2), ('bench_2x', bench2)]:
        out[name] = table(df, r)
        for p, m in out[name].items():
            print(name, p, fmt(m))
    # sensitivities
    sens = {}
    for nm, kw in [('rev_path', dict(path='rev')), ('touch', dict(strict=False)), ('quote_sizing', dict(sizing='quote'))]:
        r = run(df, **kw)
        sens[nm] = table(df, r)
        for p, m in sens[nm].items():
            print('SENS', nm, p, fmt(m))
    # fresh-start OOS (start at first Monday of 2023)
    rf = run(df, start_ms=OOS_MS)
    bf = run(df, start_ms=OOS_MS, bench=True)
    print('FRESH OOS grid', fmt(metrics(df, rf, OOS_MS, END_CLOSE_MS + 1)))
    print('FRESH OOS bench', fmt(metrics(df, bf, OOS_MS, END_CLOSE_MS + 1)))
    # look-ahead truncation test: run on truncated data, equity must match bit-for-bit
    for frac in (0.4, 0.75):
        k = int(len(df) * frac)
        rt = run(df.iloc[:k].reset_index(drop=True))
        same = np.array_equal(rt['eq'][:k], base['eq'][:k], equal_nan=True)
        print('truncation', frac, 'identical equity:', same)
    # fill sanity: each fill price inside its bar [low, high] or within prev_close..open gap
    tmap = dict(zip(df.t.values, range(len(df))))
    bad = 0
    for f in base['fills']:
        i = tmap[f[0]]
        lo = min(df.l.values[i], df.c.values[i - 1] if i > 0 else df.l.values[i])
        hi = max(df.h.values[i], df.c.values[i - 1] if i > 0 else df.h.values[i])
        if not (lo - 1e-9 <= f[2] <= hi + 1e-9):
            bad += 1
    print('fills outside bar range:', bad, 'of', len(base['fills']))
    # weekly decomposition vs bench
    t = df.t.values
    wk = df.week.values
    eg = pd.Series(base['eq']).groupby(wk).last(); eb = pd.Series(bench['eq']).groupby(wk).last()
    rg = eg.pct_change(); rb = eb.pct_change()
    wmove = df.groupby('week').apply(lambda g: (g.h.max() / g.o.iloc[0] - 1, g.l.min() / g.o.iloc[0] - 1, g.c.iloc[-1] / g.o.iloc[0] - 1))
    absmv = pd.Series([abs(x[2]) for x in wmove.values], index=wmove.index)
    diff = (rg - rb).dropna()
    bins = pd.cut(absmv.loc[diff.index] * 100, [0, 3, 7, 10, 20, 100])
    print('weekly grid-bench diff by |week move| %:')
    print(diff.groupby(bins).agg(['count', 'mean']).round(4))
    print('mean weekly diff', round(diff.mean() * 100, 3))
    json.dump({'sha': sha, 'out': out, 'sens': sens}, open(r"C:/Users/koval/AppData/Local/Temp/claude/C--Users-koval------------/c3d42fa1-b83c-49f0-8567-13ebcd1f7317/scratchpad/st/C10/verify/verify_out.json", 'w'), default=float, indent=1)


def pair_rts(df, res, c=0.002):
    """Definition B: per cell and week, consecutive fills pair into round trips (buy->sell or sell->buy);
    an unpaired fill at week end is closed at next Monday open with fee c."""
    W = df.week.values; t = df.t.values; o = df.o.values
    wk_open = {int(w): (int(tt), float(oo)) for w, tt, oo in zip(W[df.wstart.values], t[df.wstart.values], o[df.wstart.values])}
    tmap = dict(zip(t, W))
    open_ = {}
    out = []
    cur_w = None
    def flush(w):
        nxt = wk_open.get(w + 1)
        for j, (side, L, q) in list(open_.items()):
            if nxt is None:
                continue  # open at data end: not closed
            tn, P = nxt
            pnl = (q * P * (1 - c) - q * L * (1 + c)) if side == 1 else (q * L * (1 - c) - q * P * (1 + c))
            out.append((tn, pnl, 'reset'))
        open_.clear()
    for f in res['fills']:
        w = int(tmap[f[0]])
        if cur_w is not None and w != cur_w:
            for ww in range(cur_w, w):
                flush(ww)
        cur_w = w
        tt, side, L, q, j = f
        if j in open_:
            s0, L0, q0 = open_.pop(j)
            pnl = (q * L * (1 - c) - q0 * L0 * (1 + c)) if s0 == 1 else (q0 * L0 * (1 - c) - q * L * (1 + c))
            out.append((tt, pnl, 'grid'))
        else:
            open_[j] = (side, L, q)
    if cur_w is not None:
        flush(cur_w)
    return out


def pfwr(rts, lo, hi):
    p = np.array([r[1] for r in rts if lo <= r[0] < hi])
    gw = p[p > 0].sum(); gl = -p[p < 0].sum()
    return dict(n=len(p), n_grid=sum(1 for r in rts if lo <= r[0] < hi and r[2] == 'grid'),
                n_reset=sum(1 for r in rts if lo <= r[0] < hi and r[2] == 'reset'),
                pf=round(gw / gl, 4) if gl > 0 else None, wr=round((p > 0).mean() * 100, 2))


if __name__ == '__main__':
    for nm, kw in [('base', {}), ('rev_path', dict(path='rev')), ('no_same_bar_rearm', dict(same_bar_rearm=False))]:
        r = run(df, **kw)
        B_ = pair_rts(df, r)
        for p, (a, b) in PERIODS.items():
            mm = metrics(df, r, a, b)
            print('PF-A(long lots)', nm, p, 'ret', round(mm['ret'],3), 'fills', mm['fills'], pfwr(r['rts'], a, b), '| PF-B(pairs)', pfwr(B_, a, b))
