# Independent re-implementation of C1 FUNDING_CARRY from SPEC2.md (verifier).
import json, os, hashlib
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, '..', 'data')
EXPECT = {
 'funding_BTCUSDT.json': '0233ed631f31ba460a1cc9a19909961e8e2ab1c1190a704c2a7a229588557d0f',
 'funding_ETHUSDT.json': '7ecaa2bc7108707cb3072d3193237c98bf06b82a5e7fe0936533c189f74a7eeb',
 'perp_klines_8h_BTCUSDT.json': 'd62f4778b0b47d52a1a509109bc10789d6fb1d03e31dbc28e18abbae56614524',
 'perp_klines_8h_ETHUSDT.json': '0f3f2f37616e6fd8e3b93dad83d72a7e742a623873ba90d3918e0bcea34b3c58',
 'spot_klines_8h_BTCUSDT.json': '480f42e091b58eb0c9a0afaa36cfef094786d3c7a42b5d7fe0a7110f9d39e1a4',
 'spot_klines_8h_ETHUSDT.json': 'b99a6671766ff03cea9d5c52e90266522ef7f18067324da54a5f9b7b790fec1d'}
for f, h in EXPECT.items():
    assert hashlib.sha256(open(os.path.join(D, f), 'rb').read()).hexdigest() == h, f

H8 = 8 * 3600 * 1000
ENTRY_UNITS = 10000      # 0.01% in 1e-8 units (rates have 8 decimals)
NWIN = 9                 # 3 days x 3 settlements per day


def rate_int(s):
    neg = s.startswith('-')
    s = s.lstrip('-')
    a, _, b = s.partition('.')
    b = (b + '00000000')[:8]
    v = int(a) * 10**8 + int(b)
    return -v if neg else v


def load(sym):
    fu = json.load(open(os.path.join(D, f'funding_{sym}.json')))
    ft = np.array([(x['fundingTime'] // 3600000) * 3600000 for x in fu], dtype=np.int64)
    fr = np.array([rate_int(x['fundingRate']) for x in fu], dtype=np.int64)
    assert (np.diff(ft) == H8).all()

    def kl(name):
        k = json.load(open(os.path.join(D, f'{name}_klines_8h_{sym}.json')))
        return pd.DataFrame({'o': [float(r[1]) for r in k], 'c': [float(r[4]) for r in k]},
                            index=np.array([r[0] for r in k], dtype=np.int64))
    p = kl('perp')
    s = kl('spot')
    df = p.join(s, lsuffix='_p', rsuffix='_s', how='inner')
    f = pd.DataFrame({'r': fr}, index=ft)
    f['sum9'] = f['r'].rolling(NWIN).sum()   # trailing 9 settlements incl. the one at T
    df = df.join(f, how='left')
    assert (np.diff(df.index.values) == H8).all()
    return df


def sim_sleeve(df, ws, we, cap0, cs, cp, delay=0):
    """Bars with open in [ws, we]. Funding settled at T (incl. rate at T, known at T) gives the signal;
    execution at open of the bar opening at T + delay*8h. Funding credited if entry < T <= exit."""
    bars = df.loc[(df.index >= ws) & (df.index <= we)]
    t_idx = bars.index.values
    po, pc, so, sc = bars.o_p.values, bars.c_p.values, bars.o_s.values, bars.c_s.values
    rr = bars.r.values
    sig_full = df['sum9']
    eq_real = cap0
    pos = False
    qs = qp = S0 = P0 = 0.0
    trades = []
    marks = np.empty(len(bars))
    inpos = np.zeros(len(bars), bool)
    cur = None
    for i, t in enumerate(t_idx):
        # 1) funding settlement at t for a position opened strictly before t
        if pos and not np.isnan(rr[i]):
            pref = pc[i - 1]                 # perp close of the bar ending at t
            fpay = qp * pref * rr[i] / 1e8   # short receives when rate > 0
            eq_real += fpay
            cur['fund'] += fpay
        # 2) decision at bar open t
        ts = t - delay * H8
        sv = sig_full.get(ts, np.nan)
        if not np.isnan(sv):
            if (not pos) and sv > NWIN * ENTRY_UNITS:
                N = eq_real / 2.0
                qs = N / so[i]; qp = N / po[i]; S0 = so[i]; P0 = po[i]
                c = N * cs + N * cp
                eq_real -= c
                pos = True
                cur = {'entry': int(t), 'fund': 0.0, 'cost': c, 'cap': eq_real + c, 'S0': S0, 'P0': P0, 'pmax': P0}
            elif pos and sv < 0:
                b = qs * (so[i] - S0) - qp * (po[i] - P0)
                c = qs * so[i] * cs + qp * po[i] * cp
                eq_real += b - c
                pos = False
                cur.update(exit=int(t), basis=b, cost=cur['cost'] + c)
                cur['pnl'] = cur['fund'] + b - cur['cost']
                trades.append(cur)
                cur = None
        inpos[i] = pos
        if pos:
            marks[i] = eq_real + qs * (sc[i] - S0) - qp * (pc[i] - P0)
            cur['pmax'] = max(cur['pmax'], pc[i])
        else:
            marks[i] = eq_real
    if pos:  # forced close at close of last bar of window
        i = len(bars) - 1
        b = qs * (sc[i] - S0) - qp * (pc[i] - P0)
        c = qs * sc[i] * cs + qp * pc[i] * cp
        eq_real += b - c
        cur.update(exit=int(t_idx[i]) + H8, basis=b, cost=cur['cost'] + c, forced=True)
        cur['pnl'] = cur['fund'] + b - cur['cost']
        trades.append(cur)
        marks[i] = eq_real
    return pd.Series(marks, index=t_idx), trades, inpos


def ms(ts):
    return int(pd.Timestamp(ts, tz='UTC').value // 10**6)


def run(dfs, ws, we, cs, cp, delay=0):
    eqs, trades, expo = [], [], []
    full_idx = np.arange(ws, we + 1, H8, dtype=np.int64)
    for sym, df in dfs.items():
        w0 = max(ws, int(df.index.min()))
        e, tr, ip = sim_sleeve(df, w0, we, 50.0, cs, cp, delay)
        e = e.reindex(full_idx).fillna(50.0)   # before the asset's data exists: cash
        eqs.append(e)
        for x in tr:
            x['sym'] = sym
        trades += tr
        expo.append(ip.sum() / len(full_idx))
    return sum(eqs), trades, float(np.mean(expo))


def metrics(eq, trades, expo, ws, we):
    years = ((we + H8) - ws) / (365.25 * 86400e3)
    R = eq.iloc[-1] / 100.0 - 1
    tt = pd.to_datetime(eq.index, unit='ms', utc=True)
    daily = eq[tt.hour == 16]                 # bar closing 23:59:59.999 UTC = daily mark
    d = pd.concat([pd.Series([100.0]), pd.Series(daily.values)])
    dd_d = (d / d.cummax() - 1).min()
    e8 = pd.concat([pd.Series([100.0]), pd.Series(eq.values)])
    dd_8 = (e8 / e8.cummax() - 1).min()
    pn = np.array([t['pnl'] for t in trades])
    gw = pn[pn > 0].sum()
    gl = -pn[pn < 0].sum()
    return dict(trades=len(trades), win_rate_pct=round(100 * (pn > 0).mean(), 2) if len(pn) else None,
                pf=(round(gw / gl, 2) if gl > 0 else None), net_return_pct=round(100 * R, 2),
                cagr_pct=round(100 * ((1 + R) ** (1 / years) - 1), 2), max_dd_pct=round(100 * dd_d, 2),
                max_dd_8h_pct=round(100 * dd_8, 2), exposure_pct=round(100 * expo, 2), years=round(years, 3))


if __name__ == '__main__':
    dfs = {s: load(s) for s in ['BTCUSDT', 'ETHUSDT']}
    CS, CP = 0.0020, 0.0010
    END = ms('2026-10-06 16:00')
    starts = {'per_asset': ms('2019-09-10 08:00'), 'common': ms('2019-11-27 00:00')}
    out = {}
    for sname, S in starts.items():
        W = {'IS': (S, ms('2022-12-31 16:00')), 'OOS': (ms('2023-01-01 00:00'), END), 'FULL': (S, END)}
        for per, (a, b) in W.items():
            if sname == 'common' or per != 'OOS' or True:
                eq, tr, ex = run(dfs, a, b, CS, CP)
                m = metrics(eq, tr, ex, a, b)
                eq2, tr2, ex2 = run(dfs, a, b, 2 * CS, 2 * CP)
                m['net_return_2x_cost_pct'] = round(100 * (eq2.iloc[-1] / 100 - 1), 2)
                m['cagr_2x_pct'] = metrics(eq2, tr2, ex2, a, b)['cagr_pct']
                eqd, trd, exd = run(dfs, a, b, CS, CP, delay=1)
                md = metrics(eqd, trd, exd, a, b)
                m['delay1_net'] = md['net_return_pct']; m['delay1_cagr'] = md['cagr_pct']; m['delay1_trades'] = md['trades']
                eqc, trc, exc = run(dfs, a, b, 0.0010, 0.0010)
                m['cost10_10_net'] = metrics(eqc, trc, exc, a, b)['net_return_pct']
                out[(sname, per)] = (m, tr, eq)
                print(sname, per, m)
    for key in out:
        m, tr, eq = out[key]
        if key[1] != 'FULL':
            continue
        print('\n== trades', key)
        for t in tr:
            print(t['sym'], pd.to_datetime(t['entry'], unit='ms'), pd.to_datetime(t['exit'], unit='ms'),
                  'fund %.3f basis %.3f cost %.3f pnl %.3f cap %.2f maxPerpRise %.1f%%' % (
                      t['fund'], t['basis'], t['cost'], t['pnl'], t['cap'], 100 * (t['pmax'] / t['P0'] - 1)),
                  'FORCED' if t.get('forced') else '')
        tt = pd.to_datetime(eq.index, unit='ms', utc=True)
        ye = eq.groupby(tt.year).last()
        prev = 100.0
        for y, v in ye.items():
            print(' year', y, 'ret %.2f%%' % (100 * (v / prev - 1)))
            prev = v
        print(' sums: fund %.2f basis %.2f cost %.2f' % (sum(t['fund'] for t in tr), sum(t['basis'] for t in tr), sum(t['cost'] for t in tr)))
    for sname in starts:
        m, tr, eq = out[(sname, 'FULL')]
        a = ms('2023-01-01 00:00')
        e0 = eq[eq.index < a].iloc[-1]
        R = eq.iloc[-1] / e0 - 1
        yrs = ((END + H8) - a) / (365.25 * 86400e3)
        sl = eq[eq.index >= a] / e0 * 100
        tt = pd.to_datetime(sl.index, unit='ms', utc=True)
        dl = pd.concat([pd.Series([100.0]), pd.Series(sl[tt.hour == 16].values)])
        dd = (dl / dl.cummax() - 1).min()
        print('\nOOS sliced from FULL', sname, 'ret %.2f%% cagr %.2f%% dd %.2f%%' % (100 * R, 100 * ((1 + R) ** (1 / yrs) - 1), 100 * dd))
        print(' positions spanning 2023-01-01:', [(t['sym'], str(pd.to_datetime(t['entry'], unit='ms'))) for t in tr if t['entry'] < a and t['exit'] >= a])
    for s, df in dfs.items():
        f = df.dropna(subset=['r'])
        tt = pd.to_datetime(f.index, unit='ms', utc=True)
        print(s, 'mean funding by year (%/8h):', (f.r.groupby(tt.year).mean() / 1e6).round(4).to_dict())
        fm = (f.r.astype(float) / 1e8).rolling(9).mean()
        print(s, 'settlements with 3d mean == 0.01% exactly:', int((f.sum9 == 90000).sum()),
              '; float>0.0001 count', int((fm > 0.0001).sum()), 'int count', int((f.sum9 > 90000).sum()))
    json.dump({f'{k[0]}|{k[1]}': v[0] for k, v in out.items()}, open(os.path.join(HERE, 'verify_result.json'), 'w'), indent=1, default=float)
