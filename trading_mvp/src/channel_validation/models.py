from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
import statistics

from .data import day, ts, select_universe


def ema(values, period):
    out, history, previous = [], [], None
    for value in values:
        if value is None:
            history, previous = [], None
            out.append(None)
            continue
        history.append(float(value))
        if previous is None and len(history) >= period:
            previous = sum(history[-period:])/period
        elif previous is not None:
            previous += 2/(period+1)*(value-previous)
        out.append(previous)
    return out


def atr(rows, period=14):
    out, trs, previous = [], [], None
    for i, r in enumerate(rows):
        tr = r['high']-r['low']
        if i:
            tr = max(tr, abs(r['high']-rows[i-1]['close']), abs(r['low']-rows[i-1]['close']))
        trs.append(tr)
        if len(trs) == period:
            previous = sum(trs)/period
        elif len(trs) > period:
            previous = ((period-1)*previous+tr)/period
        out.append(previous)
    return out


def confirmed_pivots(rows, left=2, right=2):
    lows, highs = [], []
    low = high = None
    for now in range(len(rows)):
        center = now-right
        if center >= left:
            neighbors = [rows[k] for k in range(center-left, center+right+1) if k != center]
            if all(rows[center]['low'] < x['low'] for x in neighbors):
                low = center, rows[center]['low']
            if all(rows[center]['high'] > x['high'] for x in neighbors):
                high = center, rows[center]['high']
        lows.append(low)
        highs.append(high)
    return lows, highs


def bar_exit(row, stop, target, side):
    if side not in (-1, 1):
        raise ValueError('Invalid direction')
    if side == 1:
        if row['low'] <= stop:
            return min(stop, row['open']), 'STOP'
        if target is not None and row['high'] >= target:
            return target, 'TARGET'
    else:
        if row['high'] >= stop:
            return max(stop, row['open']), 'STOP'
        if target is not None and row['low'] <= target:
            return target, 'TARGET'
    return None


def option_pnl(legs):
    pnl = 0.0
    for leg in legs:
        if leg['multiplier'] <= 0 or leg['quantity'] < 0 or leg['side'] not in (-1, 1):
            raise ValueError('Invalid option leg')
        buy = leg['entry_ask'] if leg['side'] == 1 else leg['exit_ask']
        sell = leg['exit_bid'] if leg['side'] == 1 else leg['entry_bid']
        if buy < 0 or sell < 0 or leg['entry_fee'] < 0 or leg['exit_fee'] < 0:
            raise ValueError('Invalid option prices/fees')
        pnl += (sell-buy)*leg['quantity']*leg['multiplier']
        pnl -= (leg['entry_fee']+leg['exit_fee'])*leg['quantity']
    return pnl


def pair_pnl(long_entry, short_entry, long_exit, short_exit, quantity, fee_rate,
             funding_events, entry_ts, exit_ts):
    if min(long_entry, short_entry, long_exit, short_exit) <= 0 or quantity < 0 or fee_rate < 0:
        raise ValueError('Invalid pair economics')
    # Funding events exactly at entry cannot be captured by a later fill.
    funding = sum(rate*short_entry*quantity for when, rate in funding_events if entry_ts < when <= exit_ts)
    return quantity*(long_exit-long_entry+short_entry-short_exit) + funding - quantity*fee_rate*(long_entry+short_entry+long_exit+short_exit)


def grid_fill(side, level, quote, quantity=0):
    if side == 'buy':
        return 'ask' in quote and quote['ask'] <= level and quote.get('ask_size', 0) >= quantity
    if side == 'sell':
        return 'bid' in quote and quote['bid'] >= level and quote.get('bid_size', 0) >= quantity
    raise ValueError('Invalid grid side')


def book_imbalance(row):
    bid, ask = row['bid_notional_top10'], row['ask_notional_top10']
    if bid < 0 or ask < 0 or bid+ask == 0:
        raise ValueError('Missing observable two-sided depth')
    return (bid-ask)/(bid+ask)


def causal_funding_forecast(rows, at, symbol, venue):
    known = [r for r in rows if r['symbol'] == symbol and r.get('venue') == venue
             and ts(r['available_at']) <= at and ts(r['settlement_ts']) <= at]
    if not known:
        return None
    last = max(known, key=lambda r: ts(r['settlement_ts']))
    if at-ts(last['settlement_ts']) > 2*last['period_seconds']:
        return None
    return last['rate']*86400/last['period_seconds']


def choose_option(chain, underlying, at, ratio, dte=30):
    candidates = [r for r in chain if r['underlying'] == underlying and r['option_type'] == 'put'
                  and ts(r['ts']) == at and ts(r['available_at']) <= at and ts(r['expiry_ts']) > at+7*86400]
    if not candidates:
        return None
    expiry = min({ts(r['expiry_ts']) for r in candidates}, key=lambda x: (abs((x-at)/86400-dte), x))
    spot = candidates[0].get('underlying_spot')
    if not spot or spot <= 0:
        raise ValueError('Option chain missing contemporaneous underlying price')
    return min((r for r in candidates if ts(r['expiry_ts']) == expiry),
               key=lambda r: (abs(r['strike']/spot-ratio), r['strike'], r['symbol']))


def wallet_ranking(swaps, at):
    purchases = defaultdict(float)
    for r in swaps:
        if at-30*86400 <= ts(r['ts']) < at and ts(r['available_at']) <= at and r['side'] == 'buy':
            purchases[r['wallet']] += r['quote_usd']
    return [a for a, _ in sorted(purchases.items(), key=lambda x: (-x[1], x[0]))[:10]]


def lending_pnl(deposit, entry_index, exit_index, entry_price, exit_price, gas, withdrawable):
    if min(entry_index, exit_index, entry_price, exit_price) <= 0 or deposit < 0 or gas < 0:
        raise ValueError('Invalid lending observation')
    final = deposit/entry_price*exit_index/entry_index*exit_price
    if withdrawable < final:
        raise ValueError('Withdrawal not executable; position remains open')
    return final-deposit-gas


def prepare(rows):
    closes = [r['close'] for r in rows]
    lows, highs = confirmed_pivots(rows)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    macd = [a-b if a is not None and b is not None else None for a, b in zip(e12, e26)]
    return dict(atr=atr(rows), e50=ema(closes, 50), e200=ema(closes, 200), e220=ema(closes, 220),
                lows=lows, highs=highs, macd=macd, macd_signal=ema(macd, 9))


def candle_signal(key, rows, f, i, benchmark=None):
    if i < 1 or f['atr'][i] is None or f['atr'][i] <= 0:
        return None
    r, p = rows[i], rows[i-1]
    if key == 'relative_strength':
        if i < 24 or benchmark is None or ts(r['ts'])-ts(rows[i-24]['ts']) != 86400:
            return None
        t = ts(r['end_ts'])
        if t not in benchmark or t-86400 not in benchmark:
            return None
        b = benchmark[t]/benchmark[t-86400]-1
        ret = r['close']/rows[i-24]['close']-1
        return ret if b <= -0.03 and ret >= 0 else None
    if key == 'trend_pullback':
        if f['e200'][i] is None:
            return None
        return 1.0 if f['e50'][i] > f['e200'][i] and r['low'] <= f['e50'][i] < r['close'] else None
    if key == 'structure_break':
        # Break a previously known level, not a level confirmed by this same bar.
        low, high = f['lows'][i-1], f['highs'][i-1]
        if not low or not high:
            return None
        old_lows = [x for x in f['lows'][:i] if x and x[0] < low[0]]
        old_highs = [x for x in f['highs'][:i] if x and x[0] < high[0]]
        if old_lows and old_highs and low[1] > old_lows[-1][1] and high[1] > old_highs[-1][1]:
            return 1.0 if p['close'] <= high[1] < r['close'] else None
        return None
    if key == 'normalized_line':
        low = f['lows'][i-1]
        if not low:
            return None
        confirmed = low[0]+2
        a = f['atr'][confirmed]
        if a is None or i <= confirmed:
            return None
        before = low[1]+0.1*a*(i-1-low[0])
        current = low[1]+0.1*a*(i-low[0])
        return 1.0 if p['close'] <= before and r['close'] > current else None
    if key == 'gold_macd':
        if f['e220'][i] is None or f['macd_signal'][i-1] is None:
            return None
        return 1.0 if (r['close'] > f['e220'][i] and f['macd'][i-1] <= f['macd_signal'][i-1]
                       and f['macd'][i] > f['macd_signal'][i]) else None
    raise ValueError(f'Not a candle model: {key}')


def candle_replay(model, bars, universes, plan, *, stress=False, fee_bps=None, check=lambda: None):
    key = model['id']
    if key not in ('relative_strength', 'trend_pullback', 'structure_break', 'normalized_line'):
        raise ValueError('Use instrument-specific adapter for non-crypto candles')
    by_symbol = defaultdict(list)
    for r in bars:
        by_symbol[r['symbol']].append(r)
    frames = {s: prepare(rows) for s, rows in by_symbol.items()}
    known_through = {}
    for s, rows in by_symbol.items():
        last_available, prefix = 0, []
        for row in rows:
            last_available = max(last_available, ts(row['available_at']))
            prefix.append(last_available)
        known_through[s] = prefix
    benchmark = {ts(r['end_ts']): r['close'] for r in by_symbol.get('BTC', [])}
    benchmark_availability = {ts(r['end_ts']): ts(r['available_at']) for r in by_symbol.get('BTC', [])}
    timeline = defaultdict(list)
    for s, rows in by_symbol.items():
        for i, r in enumerate(rows):
            timeline[ts(r['ts'])].append((s, i, r))
    cash = plan['portfolio']['initial_cash']
    positions, marks, trades, equity = {}, {}, [], {}
    fee = (fee_bps if fee_bps is not None else plan['execution']['default_fee_bps'])/10000
    adverse = plan['execution']['fallback_adverse_bps_per_order']/10000 * (2 if stress else 1)
    params = model['parameters']
    start, end = ts(plan['periods']['development'][0]+'T00:00:00Z'), ts(plan['periods']['final'][1]+'T00:00:00Z')

    def close(s, price, when, why):
        nonlocal cash
        p = positions.pop(s)
        proceeds = p['quantity']*price*(1-adverse)*(1-fee)
        cash += proceeds
        trades.append(dict(symbol=s, entry_ts=p['entry_ts'], exit_ts=when, capital=p['capital'],
                           pnl=proceeds-p['capital'], reason=why, turnover=p['capital']+proceeds))

    for when, group in sorted(timeline.items()):
        check()
        if when < start or when >= end:
            continue
        # Positions cannot silently pass through missing bars or delisting.
        for s, p in list(positions.items()):
            expected = p['next_expected_ts']
            if expected < when or (expected == when and not any(x[0] == s for x in group)):
                raise ValueError('Open position has a data gap / delisting without terminal valuation')
        for s, i, r in group:
            if s in positions:
                p = positions[s]
                if when >= p['deadline']:
                    close(s, r['open'], when, 'TIME')
        candidates = []
        snapshots = [u for u in universes if ts(u['available_at']) <= when and ts(u['ts']) <= when]
        universe = set()
        if snapshots:
            snap = max(snapshots, key=lambda u: ts(u['ts']))
            if day(snap['ts'])[:7] == day(when)[:7]:
                universe = set(select_universe(snap, when))
        if not snapshots or day(snap['ts'])[:7] != day(when)[:7]:
            raise ValueError('Monthly point-in-time universe missing; missing months are not flat returns')
        for s, i, r in group:
            if not i or s in positions or s not in universe:
                continue
            prev = by_symbol[s][i-1]
            if ts(prev['end_ts']) != when or known_through[s][i-1] > when:
                continue
            if key == 'relative_strength' and any(benchmark_availability.get(t, math.inf) > when
                                                  for t in (when, when-86400)):
                continue
            score = candle_signal(key, by_symbol[s], frames[s], i-1, benchmark)
            if score is not None:
                candidates.append((score, s, i, r))
        candidates.sort(key=lambda x: (-x[0], x[1]))
        if key == 'relative_strength':
            candidates = candidates[:3]
        for score, s, i, r in candidates:
            a = frames[s]['atr'][i-1]
            account = cash+sum(p['quantity']*marks.get(sym, p['entry_price']) for sym, p in positions.items())
            entry = r['open']*(1+adverse)
            budget = min(cash, account*0.1)
            planned_stop = entry-params['stop_atr']*a
            if planned_stop <= 0:
                continue
            planned_loss = entry*(1+fee)-planned_stop*(1-adverse)*(1-fee)
            quantity = min(account*0.0025/planned_loss, budget/(entry*(1+fee)))
            if quantity <= 0:
                continue
            capital = quantity*entry*(1+fee)
            cash -= capital
            positions[s] = dict(entry_ts=when, entry_price=entry, quantity=quantity, capital=capital,
                                stop=entry-params['stop_atr']*a,
                                target=entry+params['target_atr']*a if 'target_atr' in params else None,
                                deadline=when+params['hold_hours']*3600,
                                next_expected_ts=ts(r['end_ts']))
        # Intrabar exits occur AFTER every entry at this timestamp. Proceeds
        # from a future high/low cannot finance another symbol's opening fill.
        for s, i, r in group:
            if s in positions:
                result = bar_exit(r, positions[s]['stop'], positions[s]['target'], 1)
                if result:
                    close(s, result[0], ts(r['end_ts']), result[1])
        for s, i, r in group:
            marks[s] = r['close']
            if s in positions:
                positions[s]['next_expected_ts'] = ts(r['end_ts'])
        at = max(ts(r['end_ts']) for _, _, r in group)
        equity[day(at-0.001)] = cash+sum(p['quantity']*marks.get(s, p['entry_price'])*(1-adverse)*(1-fee)
                                        for s, p in positions.items())
    return dict(trades=trades, daily_equity=equity, open_positions=positions,
                execution_quality='CANDLE_PROXY_NOT_EXECUTABLE', stress=stress)
