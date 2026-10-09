# Independent re-implementation of C3 CROSS_VENUE_FUNDING from SPEC2.md (verifier).
# Does not read run.py / result.json.
import json, hashlib, os, sys
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
H8 = 8 * 3600 * 1000
H4 = 4 * 3600 * 1000

EXPECTED = {
    'binance_funding_BTCUSDT.json': '8bf8c585058ff10baf73afc564ca9a8dd028e023ebe2d2aefc04faa25b016633',
    'bybit_funding_BTCUSDT.json': '7b875eb8638a77212fdc10b682289a251a0cd6c224a722a0877066aa4d4593c9',
    'binance_perp_klines_8h_BTCUSDT.json': '407adbf8f5ba72f41927c2ba81c3590e371df29e99910c6e4abab5e949d7b5a2',
    'bybit_perp_klines_4h_BTCUSDT.json': '8ddd7ba1fc8f6fbfc22d3e57d2ec7bc420af49a7e87287516414acff7bcd2091',
}
for n, h in EXPECTED.items():
    got = hashlib.sha256(open(os.path.join(D, n), 'rb').read()).hexdigest()
    assert got == h, (n, got)

def ld(n):
    return json.load(open(os.path.join(D, n)))

# ---- funding: map every settlement to the 8h window (T-8h, T] labelled T, sum within window
def window_label(ms):
    ms = np.asarray(ms, dtype='int64')
    ms = (ms + 30_000) // 60_000 * 60_000          # round to minute (Binance has ms jitter)
    return -(-ms // H8) * H8                        # ceil to 8h boundary

bf = pd.DataFrame(ld('binance_funding_BTCUSDT.json'))
bf['T'] = window_label(bf.fundingTime.astype('int64'))
bf['r'] = bf.fundingRate.astype(float)
fb = bf.groupby('T').r.sum()
assert bf.groupby('T').size().max() == 1

yf = pd.DataFrame(ld('bybit_funding_BTCUSDT.json'))
yf['T'] = window_label(yf.fundingRateTimestamp.astype('int64'))
yf['r'] = yf.fundingRate.astype(float)
fy = yf.groupby('T').r.sum()
assert yf.groupby('T').size().max() == 1

# ---- prices
kb = pd.DataFrame(ld('binance_perp_klines_8h_BTCUSDT.json'))
kb = pd.DataFrame({'t': kb[0].astype('int64'), 'o': kb[1].astype(float), 'c': kb[4].astype(float)}).set_index('t').sort_index()
ky = pd.DataFrame(ld('bybit_perp_klines_4h_BTCUSDT.json'))
ky = pd.DataFrame({'t': ky[0].astype('int64'), 'o': ky[1].astype(float), 'c': ky[4].astype(float)}).set_index('t').sort_index()

# price "at close" at time T = close of bar ending at T ; execution price at T = open of bar starting at T
cb = kb.c.copy(); cb.index = cb.index + H8          # binance close at T
ob = kb.o                                            # binance open at T
cy = ky.c.copy(); cy.index = cy.index + H4          # bybit close at T (4h bar ending at T)
oy = ky.o                                            # bybit open at T

# ---- signal: 7-day (21 x 8h) trailing mean of spread Bybit - Binance using settlements <= T
grid = np.arange(max(fy.index.min(), fb.index.min()), min(fy.index.max(), fb.index.max()) + H8, H8)
s = (fy.reindex(grid) - fb.reindex(grid))
assert s.isna().sum() == 0
m = s.rolling(21, min_periods=21).mean()
first_sig = m.dropna().index[0]

ENTER, FLAT = 0.0001, 0.00003

def target(pos, mv):
    if mv > ENTER:
        return 1
    if mv < -ENTER:
        return -1
    if abs(mv) < FLAT:
        return 0
    return pos

def ts(ms):
    return pd.Timestamp(ms, unit='ms')

def run(start, end, cost_leg):
    """start: first decision time (flat before). end: final time point (close of last bar); forced exit at close_at[end]."""
    E = 1.0
    pos = 0
    qb = qy = 0.0     # BTC qty of binance / bybit leg (positive numbers)
    lastb = lasty = None
    trades = []
    cur = None
    eq_marks = [(start, E)]
    in_pos_bars = 0
    nbars = 0
    comp = {'fund': 0.0, 'price': 0.0, 'cost': 0.0}
    T = start
    while T <= end:
        if T > start:
            nbars += 1
            if pos != 0:
                in_pos_bars += 1
                # dir: pos=+1 -> long binance (+1), short bybit (-1)
                db, dy = pos, -pos
                pb, py = cb[T], cy[T]
                pr = qb * (pb - lastb) * db + qy * (py - lasty) * dy
                # funding: positive rate -> longs pay shorts ; leg pnl = -dir * rate * qty * price
                fu = -db * fb[T] * qb * pb - dy * fy[T] * qy * py
                E += pr + fu
                cur['price'] += pr; cur['fund'] += fu
                comp['price'] += pr; comp['fund'] += fu
                lastb, lasty = pb, py
            if ts(T).hour == 0:
                eq_marks.append((T, E))
        if T == end:
            if pos != 0:
                c = cost_leg * (qb * lastb + qy * lasty)
                E -= c; cur['cost'] += c; comp['cost'] -= c
                cur['exit'] = T; trades.append(cur); cur = None; pos = 0
            break
        tgt = target(pos, m[T])
        if tgt != pos:
            pob, poy = ob[T], oy[T]
            if pos != 0:
                db, dy = pos, -pos
                pr = qb * (pob - lastb) * db + qy * (poy - lasty) * dy
                E += pr; cur['price'] += pr; comp['price'] += pr
                c = cost_leg * (qb * pob + qy * poy)
                E -= c; cur['cost'] += c; comp['cost'] -= c
                cur['exit'] = T; trades.append(cur); cur = None
                pos = 0
            if tgt != 0:
                N = 0.5 * E
                qb, qy = N / pob, N / poy
                c = cost_leg * 2 * N
                E -= c; comp['cost'] -= c
                cur = {'entry': T, 'dir': tgt, 'fund': 0.0, 'price': 0.0, 'cost': c}
                lastb, lasty = pob, poy
                pos = tgt
        T += H8
    eq_marks.append((end, E))
    eq = pd.Series([e for _, e in eq_marks], index=[ts(t) for t, _ in eq_marks])
    eq = eq[~eq.index.duplicated(keep='last')]
    dd = (eq / eq.cummax() - 1).min()
    pnl = np.array([t['fund'] + t['price'] - t['cost'] for t in trades])
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl < 0].sum()
    yrs = (end - start) / (365.25 * 24 * 3600 * 1000)
    R = E - 1
    return {
        'trades': len(trades),
        'win_rate_pct': 100 * (pnl > 0).mean() if len(pnl) else None,
        'pf': (wins / losses) if losses > 0 else (None if wins == 0 else float('inf')),
        'net_return_pct': 100 * R,
        'cagr_pct': 100 * ((1 + R) ** (1 / yrs) - 1),
        'max_dd_pct': 100 * dd,
        'exposure_pct': 100 * in_pos_bars / nbars,
        'comp_pct': {k: 100 * v for k, v in comp.items()},
        'n_long_short': (sum(t['dir'] == 1 for t in trades), sum(t['dir'] == -1 for t in trades)),
        'trade_list': [(str(ts(t['entry'])), str(ts(t['exit'])), t['dir'], round(100 * (t['fund'] + t['price'] - t['cost']), 4)) for t in trades],
    }

OOS0 = int(pd.Timestamp('2023-01-01').value // 10**6)
END_A = int(pd.Timestamp('2026-10-07 00:00').value // 10**6)   # close of last bar [10-06 16:00, 10-07 00:00)
END_B = int(pd.Timestamp('2026-10-06 16:00').value // 10**6)   # alt: stop at 10-06 16:00 (as other agent)

out = {}
for lab, a, b in [('IS', first_sig, OOS0), ('OOS', OOS0, END_A), ('FULL', first_sig, END_A),
                  ('OOS_endB', OOS0, END_B), ('FULL_endB', first_sig, END_B)]:
    r1 = run(a, b, 0.001)
    r2 = run(a, b, 0.002)
    r1['net_return_2x_cost_pct'] = r2['net_return_pct']
    r1['start'] = str(ts(a)); r1['end'] = str(ts(b))
    out[lab] = r1

# spread stats
sp = s.copy(); sp.index = [ts(t) for t in sp.index]
mm = m.copy(); mm.index = [ts(t) for t in mm.index]
stats = {
    'first_signal': str(ts(first_sig)),
    'spread_std_IS_pct': 100 * sp[:'2022-12-31'].std(),
    'spread_std_OOS_pct': 100 * sp['2023-01-01':'2026-10-06'].std(),
    'spread_mean_OOS_pct': 100 * sp['2023-01-01':'2026-10-06'].mean(),
    'frac_OOS_abs_m_gt_0.01pct': float((mm['2023-01-01':'2026-10-06'].abs() > ENTER).mean()),
    'frac_IS_abs_m_gt_0.01pct': float((mm[:'2022-12-31'].abs() > ENTER).mean()),
}
for k, v in out.items():
    tl = v.pop('trade_list')
    print('==', k, json.dumps(v, default=float))
    if k in ('OOS', 'IS'):
        for t in tl:
            print('   ', t)
print(json.dumps(stats, default=float, indent=1))
json.dump({'rows': out, 'stats': stats}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verify_out.json'), 'w'), default=float, indent=1)

# ---- robustness checks (not spec variants; only to probe look-ahead / reading of sizing)
if '--sens' in sys.argv:
    import types
    base_m = m.copy()
    # (a) signal lagged one extra bar: use settlements <= T-8h, still execute at open T
    m = base_m.shift(1)
    for lab, a, b in [('IS_lag1', first_sig + H8, OOS0), ('OOS_lag1', OOS0, END_A)]:
        r = run(a, b, 0.001); r.pop('trade_list')
        print(lab, {k: r[k] for k in ('trades', 'net_return_pct', 'pf', 'max_dd_pct')})
    m = base_m
    # (b) look-ahead perturbation: scramble spreads after 2022-06-01, check pre-cutoff trades unchanged
    cut = int(pd.Timestamp('2022-06-01').value // 10**6)
    rng = np.random.default_rng(0)
    s2 = s.copy(); idx = s2.index >= cut
    s2[idx] = rng.normal(0, 0.0005, idx.sum())
    m = s2.rolling(21, min_periods=21).mean()
    rp = run(first_sig, OOS0, 0.001)
    m = base_m
    r0 = run(first_sig, OOS0, 0.001)
    pre0 = [t for t in r0['trade_list'] if pd.Timestamp(t[1]) < pd.Timestamp('2022-06-01')]
    prep = [t for t in rp['trade_list'] if pd.Timestamp(t[1]) < pd.Timestamp('2022-06-01')]
    print('perturbation: pre-cutoff trades identical =', pre0 == prep, len(pre0))
    # (c) 8h-mark drawdown
    print('note: 25%-per-leg reading scales P&L ~x0.5, sign unchanged')
