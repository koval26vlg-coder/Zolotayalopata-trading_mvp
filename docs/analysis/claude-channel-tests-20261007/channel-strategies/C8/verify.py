"""
Independent verifier for C8 IMPULSE_PULLBACK_BREAKOUT_4H (SPEC2.md, frozen).
Written from the spec only (run.py/result.json NOT read before the comparison).

Interpretation fixed before running:
- Data: Binance spot 4h klines BTC/ETH/SOL; keep bars with close_time <= 2026-10-06 23:59:59.999 UTC.
- ATR(14) = Wilder (RMA) of True Range (first TR = high-low; seed = SMA of first 14 TR).
- Impulse at bar t (closed): close_t - min(low[t-5..t]) >= 3*ATR_t. H = max(high[t-5..t]), L0 = min(low[t-5..t]).
  Impulse size = H - L0 (retracement measured low-based from H).
- Setup window = bars t+1..t+12. Bar by bar (at close of bar j): PL = min(low[t+1..j]).
    * If PL < H - 0.618*(H-L0) or close_j < L0 -> cancel.
    * Else if close_j > H: if PL <= H - 0.382*(H-L0) -> signal (entry at open j+1); else cancel (breakout w/o pullback).
    * If j == t+12 without signal -> expire.
  After a cancel/expire/exit on bar j, the impulse test is run on bar j itself (state free again).
- One setup or position per asset at a time; new impulses ignored while a setup/position/pending entry exists.
- Entry at open of bar j+1. Stop = PL, R = entry - stop (skip if R <= 0), TP = entry + 3R.
- Size: qty = 1% of sleeve equity / R, notional capped at 100% sleeve equity.
- Exit check from the entry bar on: if open <= stop -> exit at open; elif low <= stop -> stop (stop first);
  elif open >= TP -> open; elif high >= TP -> TP. Period end -> exit at last close.
- Costs 20 bps per side on notional (stress 40 bps).
- Sleeves: 1/3 each, independent compounding, SOL sleeve in cash before its first bar.
- IS/OOS/FULL = separate runs with fresh capital; indicators computed on full history (causal).
- Max DD on daily marks (equity at last 4h close of each UTC day). Benchmark: 1/3 B&H each, cost on entry and exit,
  SOL third bought at its first open within the period.
"""
import numpy as np, pandas as pd, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
DATA = os.path.join(BASE, 'data')
SYMS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
EXPECTED = {
    'BTCUSDT': '79a5b3317ebabc175c0393e2c7ea23db882454f58a0152f86204eab0429a71a5',
    'ETHUSDT': 'd5e6f3e023c2c2085226a5e1f7277ef5c1252dcac70e36993ee60cfd987f1386',
    'SOLUSDT': 'ed6cfb27858c53294d33b330afec64654fd4d12a09872ab502bbaa6faa5eb348',
}
CUTOFF_MS = int(pd.Timestamp('2026-10-06 23:59:59.999', tz='UTC').value // 10**6)
IS_END = pd.Timestamp('2022-12-31 23:59:59.999', tz='UTC')
OOS_START = pd.Timestamp('2023-01-01', tz='UTC')
PERIODS = {
    'IS': (None, IS_END),
    'OOS': (OOS_START, None),
    'FULL': (None, None),
}
VARIANT = os.environ.get('C8_VARIANT', 'base')  # diagnostics only, not reported as results


def load(sym):
    p = os.path.join(DATA, f'{sym}_4h_raw.csv')
    h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    assert h == EXPECTED[sym], (sym, h)
    d = pd.read_csv(p)
    d = d[d.close_time <= CUTOFF_MS].copy()
    d['t'] = pd.to_datetime(d.open_time, unit='ms', utc=True)
    d['tc'] = pd.to_datetime(d.close_time, unit='ms', utc=True)
    d = d.sort_values('t').reset_index(drop=True)
    return d


def atr_wilder(h, l, c, n=14):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.where(np.isnan(pc), h - l, np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)]))
    a = np.full(len(tr), np.nan)
    a[n - 1] = tr[:n].mean()
    for i in range(n, len(tr)):
        a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def simulate(d, atr, i0, i1, eq0, cost):
    """Simulate one asset on bar index range [i0, i1] inclusive. Returns trades, equity per bar (at close)."""
    o, h, l, c = (d[k].values.astype(float) for k in ['open', 'high', 'low', 'close'])
    cash = eq0
    qty = 0.0
    pos = None
    setup = None
    pending = None
    trades = []
    eq = np.empty(i1 - i0 + 1)
    for j in range(i0, i1 + 1):
        # 1) execute pending entry at open of j
        if pending is not None:
            stop = pending['stop']
            entry = o[j]
            R = entry - stop
            if R > 0:
                equity = cash
                q = 0.01 * equity / R
                if q * entry > equity:
                    q = equity / entry
                fee = q * entry * cost
                cash -= q * entry + fee
                qty = q
                pos = dict(entry_i=j, entry=entry, stop=stop, tp=entry + 3 * R, q=q, fee_in=fee,
                           sig_i=pending['sig_i'], imp_i=pending['imp_i'], notional=q * entry, eq_before=equity)
            pending = None
        # 2) exits on bar j
        if pos is not None:
            px = None; why = None
            if o[j] <= pos['stop']:
                px, why = o[j], 'stop_gap'
            elif l[j] <= pos['stop']:
                px, why = pos['stop'], 'stop'
            elif o[j] >= pos['tp']:
                px, why = o[j], 'tp_gap'
            elif h[j] >= pos['tp']:
                px, why = pos['tp'], 'tp'
            elif j == i1:
                px, why = c[j], 'period_end'
            if px is not None:
                both = (l[j] <= pos['stop']) and (h[j] >= pos['tp'])
                fee = pos['q'] * px * cost
                cash += pos['q'] * px - fee
                pnl = pos['q'] * (px - pos['entry']) - pos['fee_in'] - fee
                trades.append(dict(entry_t=d.t[pos['entry_i']], exit_t=d.t[j], sig_t=d.t[pos['sig_i']],
                                   imp_t=d.t[pos['imp_i']], entry=pos['entry'], stop=pos['stop'], tp=pos['tp'],
                                   exit=px, why=why, pnl=pnl, notional=pos['notional'], both_touched=both,
                                   bars=j - pos['entry_i'] + 1, frac=pos['notional'] / pos['eq_before']))
                qty = 0.0
                pos = None
        # 3) setup tracking at close of j
        if setup is not None and pos is None and pending is None:
            s = setup
            s['PL'] = min(s['PL'], l[j])
            rng = s['H'] - s['L0']
            if s['PL'] < s['H'] - 0.618 * rng or c[j] < s['L0']:
                setup = None
            elif c[j] > s['H']:
                if s['PL'] <= s['H'] - 0.382 * rng:
                    if j < i1:
                        pending = dict(stop=s['PL'], sig_i=j, imp_i=s['t'])
                    setup = None
                else:
                    if VARIANT != 'keep_waiting':
                        setup = None
            if setup is not None and j >= s['t'] + 12:
                setup = None
        # 4) new impulse detection at close of j (state must be free)
        if setup is None and pos is None and pending is None and j >= 5 and not np.isnan(atr[j]):
            lo = l[j - 5:j + 1].min()
            if c[j] - lo >= 3 * atr[j]:
                setup = dict(t=j, H=h[j - 5:j + 1].max(), L0=lo, PL=np.inf)
        eq[j - i0] = cash + qty * c[j]
    return trades, eq


def metrics_from(eq_series, trades, eq0, start, end):
    daily = eq_series.groupby(eq_series.index.floor('D')).last()
    dd = (daily / daily.cummax() - 1).min() * 100
    dd4h = (eq_series / eq_series.cummax() - 1).min() * 100
    net = (eq_series.iloc[-1] / eq0 - 1) * 100
    days = (end - start).total_seconds() / 86400
    cagr = ((eq_series.iloc[-1] / eq0) ** (365.25 / days) - 1) * 100
    pn = np.array([t['pnl'] for t in trades]) if trades else np.array([])
    gw = pn[pn > 0].sum(); gl = -pn[pn < 0].sum()
    return dict(trades=len(pn), win_rate_pct=(pn > 0).mean() * 100 if len(pn) else None,
                pf=gw / gl if gl > 0 else None, net_return_pct=net, cagr_pct=cagr, max_dd_pct=dd,
                max_dd_4h_pct=dd4h)


def run_period(data, atrs, name, cost):
    p0, p1 = PERIODS[name]
    res = {}
    for s in SYMS:
        d = data[s]
        m = np.ones(len(d), bool)
        if p0 is not None: m &= (d.t >= p0).values
        if p1 is not None: m &= (d.tc <= p1).values
        res[s] = np.where(m)[0]
    bt = data['BTCUSDT']
    ib = res['BTCUSDT']
    start = bt.t[ib[0]]; end = bt.tc[ib[-1]]
    eq0 = 1.0 / 3
    sleeves = {}
    all_trades = {}
    for s in SYMS:
        d = data[s]; idx = res[s]
        tr, eq = simulate(d, atrs[s], idx[0], idx[-1], eq0, cost)
        sleeves[s] = pd.Series(eq, index=pd.DatetimeIndex(d.tc[idx]))
        all_trades[s] = tr
    tl = pd.DatetimeIndex(bt.tc[ib])
    tot = pd.Series(0.0, index=tl)
    for s in SYMS:
        ser = sleeves[s]
        ser = ser[~ser.index.duplicated()]
        al = ser.reindex(tl.union(ser.index)).ffill().reindex(tl).fillna(eq0)
        tot += al
    trades = sum(all_trades.values(), [])
    m = metrics_from(tot, trades, 1.0, start, end)
    notional_sum = np.zeros(len(tl))
    anyin = np.zeros(len(tl), bool)
    for s in SYMS:
        for t in all_trades[s]:
            mk = (tl > t['entry_t']) & (tl < t['exit_t'] + pd.Timedelta(hours=4))
            notional_sum[mk] += t['notional']
            anyin |= mk
    m['exposure_pct'] = float(np.mean(notional_sum / tot.values) * 100)
    m['time_in_mkt_pct'] = float(anyin.mean() * 100)
    beq = pd.Series(0.0, index=tl)
    for s in SYMS:
        d = data[s]; idx = res[s]
        o0 = d.open.values[idx[0]]
        q = eq0 * (1 - cost) / o0
        ser = pd.Series(q * d.close.values[idx], index=pd.DatetimeIndex(d.tc[idx]))
        ser.iloc[-1] = ser.iloc[-1] * (1 - cost)
        ser = ser[~ser.index.duplicated()]
        al = ser.reindex(tl.union(ser.index)).ffill().reindex(tl).fillna(eq0)
        beq += al
    bm = metrics_from(beq, [], 1.0, start, end)
    m['bench_net_return_pct'] = bm['net_return_pct']
    m['bench_max_dd_pct'] = bm['max_dd_pct']
    m['bench_cagr_pct'] = bm['cagr_pct']
    m['start'] = str(start); m['end'] = str(end)
    m['per_asset'] = {s: dict(n=len(all_trades[s]), ret=(sleeves[s].iloc[-1] / eq0 - 1) * 100) for s in SYMS}
    m['exits'] = pd.Series([t['why'] for t in trades]).value_counts().to_dict() if trades else {}
    m['both_touched'] = int(sum(t['both_touched'] for t in trades))
    m['max_frac'] = max([t['frac'] for t in trades]) if trades else None
    m['mean_frac'] = float(np.mean([t['frac'] for t in trades])) if trades else None
    m['mean_bars'] = float(np.mean([t['bars'] for t in trades])) if trades else None
    return m, all_trades, tot, beq


def main():
    data = {s: load(s) for s in SYMS}
    atrs = {s: atr_wilder(data[s].high.values.astype(float), data[s].low.values.astype(float),
                          data[s].close.values.astype(float)) for s in SYMS}
    out = {}
    for name in ['IS', 'OOS', 'FULL']:
        m, tr, tot, beq = run_period(data, atrs, name, 0.002)
        m2, *_ = run_period(data, atrs, name, 0.004)
        m['net_return_2x_cost_pct'] = m2['net_return_pct']
        m['pf_2x'] = m2['pf']
        out[name] = m
        rows = []
        for s in SYMS:
            for t in tr[s]:
                rows.append(dict(sym=s, **t))
        for r in rows:  # look-ahead self-check
            assert r['imp_t'] < r['sig_t'] < r['entry_t'] <= r['exit_t']
        if VARIANT == 'base':
            pd.DataFrame(rows).sort_values('entry_t').to_csv(os.path.join(HERE, f'vtrades_{name}.csv'), index=False)
    print(json.dumps(out, indent=1, default=str))
    if VARIANT == 'base':
        json.dump(out, open(os.path.join(HERE, 'verify_result.json'), 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
