"""Specialized signal/economics adapters for verified normalized historical data.

They never fetch data, invent option premiums, interpolate books or place orders.
Missing exit liquidity is an open exposure, not a zero-return completed trade.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
import math
import statistics

from .data import day, ts, select_universe
from .models import (atr, book_imbalance, causal_funding_forecast, choose_option,
                     pair_pnl, option_pnl, grid_fill, wallet_ranking, lending_pnl,
                     prepare, candle_signal, bar_exit)


class MissingEvidence(ValueError):
    pass


def groups(rows, key='symbol'):
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


def observed(rows, at):
    found = [r for r in rows if ts(r['ts']) <= at and ts(r['available_at']) <= at]
    return max(found, key=lambda r: ts(r['ts'])) if found else None


def first_after(rows, at, max_delay=60):
    found = next((r for r in rows if ts(r['ts']) >= at and ts(r['available_at']) <= ts(r['ts'])), None)
    return found if found and ts(found['ts'])-at <= max_delay else None


def quote_cost(row):
    if 'fee_bps' not in row or row['fee_bps'] < 0 or not row.get('fee_source'):
        raise MissingEvidence('Dated fee evidence required, no inherited crypto-spot schedule')
    return row['fee_bps']/10000


def long_roundtrip(entry, exit, capital=1000):
    fee1, fee2 = quote_cost(entry), quote_cost(exit)
    half1, half2 = (entry['ask']-entry['bid'])/2, (exit['ask']-exit['bid'])/2
    slip1, slip2 = entry.get('impact_per_unit', 0), exit.get('impact_per_unit', 0)
    q = capital/((entry['ask']+half1+2*slip1)*(1+fee1))
    if entry.get('ask_size', 0) < q or exit.get('bid_size', 0) < q:
        raise MissingEvidence('Insufficient executable size')
    normal = q*((exit['bid']-slip2)*(1-fee2)-(entry['ask']+slip1)*(1+fee1))
    stress = q*((exit['bid']-half2-2*slip2)*(1-fee2)-(entry['ask']+half1+2*slip1)*(1+fee1))
    return normal, stress, q


def long_marks(entry, rows, quantity, *, gas=False):
    out = []
    for r in rows:
        if ts(r['ts']) < ts(entry['ts']) or ts(r['available_at']) > ts(r['ts']):
            continue
        f1, f2 = quote_cost(entry), quote_cost(r)
        a, b = entry.get('impact_per_unit', 0), r.get('impact_per_unit', 0)
        h1, h2 = (entry['ask']-entry['bid'])/2, (r['ask']-r['bid'])/2
        fixed = entry['gas_usd']+r['gas_usd'] if gas else 0
        normal = quantity*((r['bid']-b)*(1-f2)-(entry['ask']+a)*(1+f1))-fixed
        stress = quantity*((r['bid']-h2-2*b)*(1-f2)-(entry['ask']+h1+2*a)*(1+f1))-fixed
        out.append((ts(r['ts']), normal, stress, fixed))
    return out


def opportunity(symbol, entry, exit, normal, stress, capital=1000, marks=None):
    return dict(symbol=symbol, entry_ts=ts(entry['ts']), exit_ts=ts(exit['ts']), pnl=normal,
                stress_pnl=stress, capital=capital, turnover=2*capital,
                marks=marks or [], reason='FIXED_RULE')


def in_crypto_universe(data, symbol, at):
    snapshot = observed(data.get('pit_universe', []), at)
    if snapshot is None or day(snapshot['ts'])[:7] != day(at)[:7]:
        raise MissingEvidence('Missing current monthly as-of universe')
    return symbol in select_universe(snapshot, at)


def pair_economics(entry, end, quantity, funding, key, stress=False):
    """Base-normalized linear contracts only; each leg has its own fee schedule."""
    if not entry.get('base_units_verified') or not end.get('base_units_verified'):
        raise MissingEvidence('Contract multiplier/base-unit normalization is unverified')
    prices = {}
    for label, row in (('entry', entry), ('exit', end)):
        if not row.get('fee_source'):
            raise MissingEvidence('Dated per-leg fee evidence missing')
        for leg in ('long', 'short'):
            if row.get(leg+'_fee_bps', -1) < 0 or row.get(leg+'_impact', -1) < 0:
                raise MissingEvidence('Per-leg fee/impact model missing')
            buy = (label == 'entry') == (leg == 'long')
            half = (row[leg+'_ask']-row[leg+'_bid'])/2 if stress else 0
            impact = row[leg+'_impact']*(2 if stress else 1)
            price = row[leg+('_ask' if buy else '_bid')]+(1 if buy else -1)*(half+impact)
            prices[label, leg] = price
    pnl = quantity*(prices['exit', 'long']-prices['entry', 'long']+prices['entry', 'short']-prices['exit', 'short'])
    for (label, leg), price in prices.items():
        row = entry if label == 'entry' else end
        pnl -= quantity*price*row[leg+'_fee_bps']/10000
    for event in funding:
        if event['symbol'] != entry['symbol'] or not ts(entry['ts']) < ts(event['settlement_ts']) <= ts(end['ts']):
            continue
        side = 1 if event.get('venue') == entry['short_venue'] and entry['short_market'] == 'perp' else -1 if event.get('venue') == entry['long_venue'] and entry['long_market'] == 'perp' else 0
        if side:
            if not event.get('mark_price', 0) > 0:
                raise MissingEvidence('Actual funding settlement notional missing')
            pnl += side*quantity*event['mark_price']*event['rate']
    return pnl


def orderflow(model, data, check):
    tape = groups(data.get('tape', []))
    minute = groups(data.get('bars_1m', []))
    trades, open_exposure = [], []
    for symbol, rows in groups(data['books']).items():
        ready = -1
        for i, r in enumerate(rows[:-1]):
            check()
            at = ts(r['ts'])
            if not in_crypto_universe(data, symbol, at):
                continue
            if at < ready or ts(r['available_at']) > at or book_imbalance(r) <= 0.6:
                continue
            if model['id'] == 'book_continue':
                window = [t for t in tape.get(symbol, []) if at-30 <= ts(t['ts']) <= at and ts(t['available_at']) <= at]
                volume = sum(t['quantity'] for t in window)
                if not volume or sum(t['quantity'] for t in window if t['aggressor'] == 'buy')/volume <= 0.6:
                    continue
            else:
                bars = [b for b in minute.get(symbol, []) if ts(b['available_at']) <= at and ts(b['end_ts']) <= at]
                if len(bars) < 19 or atr(bars)[-1] is None:
                    continue
                if ts(bars[-1]['end_ts'])-ts(bars[-6]['end_ts']) != 300 or bars[-6]['close']-bars[-1]['close'] <= 3*atr(bars)[-1]:
                    continue
            entry = first_after(rows[i+1:], at+0.000001, 5)
            if not entry:
                raise MissingEvidence('No next executable book after signal')
            end = first_after(rows[i+1:], ts(entry['ts'])+60, 5)
            if not end:
                open_exposure.append(dict(symbol=symbol, entry_ts=ts(entry['ts']), reason='MISSING_EXIT_BOOK'))
                break
            n, s, q = long_roundtrip(entry, end)
            marks = long_marks(entry, [x for x in rows[i+1:] if ts(x['ts']) <= ts(end['ts'])], q)
            trades.append(opportunity(symbol, entry, end, n, s, marks=marks))
            ready = ts(end['ts'])
    return trades, open_exposure


def paired(model, data, check):
    key = model['id']
    trades, exposures = [], []
    funding = data.get('funding', [])
    routes = defaultdict(list)
    for row in data['paired_quotes']:
        routes[(row['symbol'], row['long_venue'], row['short_venue'], row['long_market'], row['short_market'])].append(row)
    for route, rows in routes.items():
        symbol = route[0]
        ready = -1
        for i, r in enumerate(rows[:-1]):
            check()
            at = ts(r['ts'])
            if at < ready or ts(r['available_at']) > at:
                continue
            expected_markets = ('perp', 'perp') if key == 'funding_cross' else ('spot', 'spot') if key == 'spot_dislocation' else ('spot', 'perp')
            if (r['long_market'], r['short_market']) != expected_markets:
                raise MissingEvidence('Wrong instrument type for paired model')
            venues = {r['long_venue'], r['short_venue']}
            if venues != ({'gate', 'mexc'} if model['market'] == 'gate_mexc' else {'gate'}):
                raise MissingEvidence('Wrong venue route')
            pair_economics(r, r, 0, [], key)
            fee = max(r['long_fee_bps'], r['short_fee_bps'])/10000
            cost = 2*(r['long_fee_bps']+r['short_fee_bps'])/10000 + (r['long_ask']-r['long_bid'])/r['long_ask'] + (r['short_ask']-r['short_bid'])/r['short_bid'] + 2*(r['long_impact']/r['long_ask']+r['short_impact']/r['short_bid'])
            premium = r['short_bid']/r['long_ask']-1
            if key in ('funding_carry', 'funding_cross'):
                rate = causal_funding_forecast(funding, at, symbol, r['short_venue'])
                paid = causal_funding_forecast(funding, at, symbol, r['long_venue']) if key == 'funding_cross' else 0
                if rate is None or paid is None or rate-paid <= cost+0.001:
                    continue
            elif key == 'spot_dislocation':
                if r['long_market'] != 'spot' or r['short_market'] != 'spot' or premium <= cost+0.0005:
                    continue
                inv = observed([x for x in data['inventory'] if x['symbol'] == symbol and x['venue'] == r['short_venue']], at)
                if inv is None:
                    raise MissingEvidence('Prefunded base inventory missing')
                cash_inv = observed([x for x in data['inventory'] if x['symbol'] == symbol and x['venue'] == r['long_venue']], at)
                if cash_inv is None:
                    raise MissingEvidence('Prefunded cash inventory missing')
            else:
                prior = [x['short_bid']/x['long_ask']-1 for x in rows[:i]
                         if at-86400 <= ts(x['ts']) < at and ts(x['available_at']) <= at]
                if len(prior) < 24 or statistics.pstdev(prior) == 0:
                    continue
                if premium <= cost or (premium-statistics.mean(prior))/statistics.pstdev(prior) <= 2:
                    continue
            entry = first_after(rows[i+1:], at+0.000001, 60)
            if entry is None:
                raise MissingEvidence('Pair lacks next synchronized executable quote')
            q = 1000/(entry['long_ask']+entry['short_ask'])/(1+fee)
            if entry['long_size'] < q or entry['short_size'] < q:
                continue
            if key == 'spot_dislocation' and (inv['base_quantity'] < q or cash_inv['cash'] < q*entry['long_ask']*(1+fee)):
                continue
            end = None
            for x in rows[i+1:]:
                xt = ts(x['ts'])
                if xt <= ts(entry['ts']) or ts(x['available_at']) > xt:
                    continue
                if key != 'spot_dislocation' and xt > ts(entry['ts'])+86400+60:
                    break
                if key == 'spot_dislocation':
                    done = x['long_bid']-x['short_ask'] >= fee*(x['long_bid']+x['short_ask'])
                elif key == 'basis_convergence':
                    history = [y['short_bid']/y['long_ask']-1 for y in rows
                               if xt-86400 <= ts(y['ts']) < xt and ts(y['available_at']) <= xt]
                    if len(history) < 24 or statistics.pstdev(history) == 0:
                        if xt < ts(entry['ts'])+86400:
                            continue
                        z = 2
                    else:
                        z = (x['short_ask']/x['long_bid']-1-statistics.mean(history))/statistics.pstdev(history)
                    done = z < 0.5 or xt >= ts(entry['ts'])+86400
                else:
                    done = xt >= ts(entry['ts'])+86400
                if done:
                    end = x
                    break
            if end is None:
                exposures.append(dict(symbol=symbol, reason='NO_EXECUTABLE_PAIR_EXIT'))
                break
            if end['long_size'] < q or end['short_size'] < q:
                exposures.append(dict(symbol=symbol, reason='PARTIAL_PAIR_EXIT'))
                break
            n = pair_economics(entry, end, q, funding, key)
            s = pair_economics(entry, end, q, funding, key, True)
            marks = [(ts(x['ts']), pair_economics(entry, x, q, funding, key), pair_economics(entry, x, q, funding, key, True))
                     for x in rows if ts(entry['ts']) <= ts(x['ts']) <= ts(end['ts']) and ts(x['available_at']) <= ts(x['ts'])]
            trades.append(opportunity(symbol, entry, end, n, s, marks=marks))
            ready = ts(end['ts'])
    return trades, exposures


def options(model, data, check):
    chain = data['option_chain']
    if any(x['settlement_currency'] != 'USD' or x.get('normalized_currency') != 'USD' for x in chain):
        raise MissingEvidence('Options require audited conversion of native premiums/settlement into USD')
    trades, exposures = [], []
    for at in sorted({ts(x['ts']) for x in chain}):
        check()
        dt = datetime.fromtimestamp(at, timezone.utc)
        if dt.weekday() != 0 or dt.hour != 0 or dt.minute != 0 or dt.second != 0:
            continue
        for underlying in ('BTC', 'ETH'):
            first = choose_option(chain, underlying, at, 0.9 if model['id'] == 'cash_put' else 1)
            if first is None:
                continue
            entries = [(first, -1 if model['id'] == 'cash_put' else 1)]
            if model['id'] == 'put_spread':
                second = choose_option([x for x in chain if x['expiry_ts'] == first['expiry_ts']], underlying, at, 0.9)
                if second is None or second['strike'] >= first['strike']:
                    continue
                entries.append((second, -1))
            legs, spread_penalty = [], 0
            premium = sum(side*(r['ask'] if side == 1 else r['bid'])*r['multiplier'] for r, side in entries)
            reserve = first['strike']*first['multiplier'] if model['id'] == 'cash_put' else premium
            if reserve <= 0:
                raise MissingEvidence('Invalid option debit/cash reserve')
            quantity = math.floor(1000/(reserve+sum(quote_cost(r)*r['underlying_spot']*r['multiplier'] for r, _ in entries)))
            if quantity < 1:
                continue
            for entry, side in entries:
                end = first_after([x for x in chain if x['symbol'] == entry['symbol']], at+7*86400, 60)
                if end is None or min(entry['ask_size'] if side == 1 else entry['bid_size'], end['bid_size'] if side == 1 else end['ask_size']) < quantity:
                    exposures.append(dict(symbol=underlying, reason='OPTION_EXIT_OR_SIZE_MISSING'))
                    legs = []
                    break
                legs.append(dict(side=side, quantity=quantity, multiplier=entry['multiplier'],
                                 entry_ask=entry['ask'], entry_bid=entry['bid'], exit_bid=end['bid'], exit_ask=end['ask'],
                                 entry_fee=quote_cost(entry)*entry['underlying_spot']*entry['multiplier'],
                                 exit_fee=quote_cost(end)*end['underlying_spot']*end['multiplier']))
                spread_penalty += quantity*entry['multiplier']*((entry['ask']-entry['bid'])+(end['ask']-end['bid']))/2
            if legs:
                n = option_pnl(legs)
                marks = []
                for mt in sorted({ts(x['ts']) for x in chain if at <= ts(x['ts']) <= ts(end['ts'])}):
                    marked, penalty = [], 0
                    for (entry, side), leg in zip(entries, legs):
                        mark = observed([x for x in chain if x['symbol'] == entry['symbol']], mt)
                        if mark is None or mt-ts(mark['ts']) > 60:
                            break
                        marked.append(dict(leg, exit_bid=mark['bid'], exit_ask=mark['ask'],
                                           exit_fee=quote_cost(mark)*mark['underlying_spot']*mark['multiplier']))
                        penalty += quantity*entry['multiplier']*((entry['ask']-entry['bid'])+(mark['ask']-mark['bid']))/2
                    if len(marked) == len(entries):
                        value = option_pnl(marked)
                        marks.append((mt, value, value-penalty))
                trade = opportunity(underlying, first, end, n, n-spread_penalty, marks=marks)
                trade['size_scale_step'] = 1/quantity
                trades.append(trade)
    return trades, exposures


def grid(model, data, check):
    trades, exposures = [], []
    daily = groups(data['bars_1d'])
    for symbol, books in groups(data['books']).items():
        bars = daily.get(symbol, [])
        weeks = defaultdict(list)
        for b in books:
            dt = datetime.fromtimestamp(ts(b['ts']), timezone.utc)
            weeks[(dt.isocalendar().year, dt.isocalendar().week)].append(b)
        for quotes in weeks.values():
            check()
            start = ts(quotes[0]['ts'])
            dt = datetime.fromtimestamp(start, timezone.utc)
            if dt.weekday() != 0 or dt.hour or dt.minute:
                continue
            if not in_crypto_universe(data, symbol, start):
                continue
            known = [r for r in bars if ts(r['available_at']) <= start and ts(r['end_ts']) <= start]
            if len(known) < 14:
                continue
            a, center = atr(known)[-1], known[-1]['close']
            if a <= 0 or center <= 3*a:
                continue
            levels = [center+(i-3)*a for i in range(7)]
            cash, held, end, penalty = 1000.0, {}, quotes[0], 0.0
            initial_fee = quote_cost(end)
            amount = 500/(end['ask']*(1+initial_fee))
            if end['ask_size'] < amount or not levels[0] <= end['bid'] <= end['ask'] <= levels[-1]:
                continue
            cash -= amount*end['ask']*(1+initial_fee)
            held = {idx: amount/3 for idx in (3, 4, 5)}
            penalty += amount*(end['ask']-end['bid'])/2
            buy_enabled = {0, 1, 2}
            marks = []
            for q in quotes:
                check()
                end = q
                fee = quote_cost(q)
                bid_remaining, ask_remaining = q['bid_size'], q['ask_size']
                if q['bid'] < levels[0] or q['ask'] > levels[-1] or ts(q['ts']) >= start+7*86400:
                    break
                # Inventory bought on this quote cannot be sold on the same quote.
                for idx, amount in list(held.items()):
                    if grid_fill('sell', levels[idx+1], q, amount) and bid_remaining >= amount:
                        cash += amount*q['bid']*(1-fee)
                        penalty += amount*(q['ask']-q['bid'])/2
                        del held[idx]
                        buy_enabled.add(idx)
                        bid_remaining -= amount
                for idx in sorted(buy_enabled):
                    amount = (1000/6)/(levels[idx]*(1+fee))
                    if idx not in held and cash >= amount*q['ask']*(1+fee) and grid_fill('buy', levels[idx], q, amount) and ask_remaining >= amount:
                        cash -= amount*q['ask']*(1+fee)
                        penalty += amount*(q['ask']-q['bid'])/2
                        held[idx] = amount
                        ask_remaining -= amount
                marked = cash+sum(held.values())*q['bid']*(1-fee)-1000
                marks.append((ts(q['ts']), marked, marked-penalty-sum(held.values())*(q['ask']-q['bid'])/2))
            amount = sum(held.values())
            if end['bid_size'] < amount or (ts(end['ts']) < start+7*86400-60 and levels[0] <= end['bid'] and end['ask'] <= levels[-1]):
                exposures.append(dict(symbol=symbol, reason='OPEN_GRID_INVENTORY_OR_TRUNCATED_WEEK'))
                continue
            cash += amount*end['bid']*(1-quote_cost(end))
            penalty += amount*(end['ask']-end['bid'])/2
            trades.append(opportunity(symbol, quotes[0], end, cash-1000, cash-1000-penalty, marks=marks))
    return trades, exposures


def sessions(model, data, check):
    bars = groups(data['bars_5m'])
    trades, exposures = [], []
    for session in data['calendar']:
        check()
        op, cl = ts(session['open_ts']), ts(session['close_ts'])
        if ts(session['available_at']) > op:
            raise MissingEvidence('Session calendar not known before opening')
        for symbol, history in bars.items():
            if session.get('instrument') not in (symbol, '*'):
                continue
            rows = [r for r in history if op <= ts(r['ts']) and ts(r['end_ts']) <= cl]
            minutes = model['parameters']['range_minutes']
            initial = [r for r in rows if ts(r['end_ts']) <= op+minutes*60]
            if len(initial) != minutes//5 or not rows or ts(rows[-1]['end_ts']) != cl:
                continue
            hi, lo = max(r['high'] for r in initial), min(r['low'] for r in initial)
            previous = session.get('previous_regular_close')
            if model['id'] != 'dax_orb':
                universe = observed(data['pit_equity_universe'], op)
                if universe is None or symbol not in universe['members']:
                    continue
                if not previous or ts(session.get('previous_close_available_at', op+1)) > op or not session.get('corporate_actions_verified'):
                    raise MissingEvidence('Previous regular-session close / corporate actions unverified')
            gap = rows[0]['open']/previous-1 if previous else 0
            if model['id'] != 'dax_orb' and abs(gap) < 0.02:
                continue
            for i, r in enumerate(rows[:-1]):
                if ts(r['ts']) < op+minutes*60:
                    continue
                side = 1 if r['close'] > hi else -1 if r['close'] < lo else 0
                if not side:
                    continue
                if model['id'] == 'gap_continue' and side*gap <= 0:
                    continue
                if model['id'] == 'gap_fade' and side*gap >= 0:
                    continue
                entry = rows[i+1]
                if max(ts(x['available_at']) for x in rows[:i+1]) > ts(entry['ts']):
                    continue
                stop = lo if side == 1 else hi
                target = previous if model['id'] == 'gap_fade' else None
                end, price = rows[-1], rows[-1]['close']
                for x in rows[i+1:]:
                    hit = bar_exit(x, stop, target, side)
                    if hit:
                        price, _ = hit
                        end = x
                        break
                specs = observed([x for x in data.get('contract_specs', []) if x['symbol'] == symbol], op)
                if model['id'] == 'dax_orb' and specs is None:
                    raise MissingEvidence('DAX instrument/multiplier not specified')
                multiplier = specs['multiplier'] if specs else 1
                if specs and (specs['price_currency'] != 'USD' or specs['settlement_currency'] != 'USD'):
                    raise MissingEvidence('Instrument needs audited contemporaneous USD conversion')
                fee = quote_cost(entry)
                if abs(entry['open']-stop) <= 0 or side*(entry['open']-stop) <= 0:
                    break
                planned_loss = (abs(entry['open']-stop)+(entry['open']+stop)*(fee+.002))*multiplier
                quantity = min(25/planned_loss, 1000/(entry['open']*(1+fee+.002))/multiplier)
                lot = specs.get('lot_size', 1) if specs else 1
                quantity = math.floor(quantity/lot)*lot
                if not quantity:
                    break
                if side == -1 and model['id'] != 'dax_orb' and not entry.get('borrow_cost_evidence'):
                    raise MissingEvidence('Short equity borrowability / costs missing')
                gross = quantity*multiplier*(price-entry['open'])*side
                costs = quantity*multiplier*(price+entry['open'])*(fee+0.001)
                if side == -1 and model['id'] != 'dax_orb':
                    costs += quantity*entry['open']*entry['borrow_bps']/10000
                marks = []
                for mt, value in [(ts(entry['ts']), entry['open'])]+[(ts(x['end_ts']), x['close']) for x in rows[i+1:] if ts(x['end_ts']) <= ts(end['end_ts'])]:
                    cost = quantity*multiplier*(value+entry['open'])*(fee+.001)
                    if side == -1 and model['id'] != 'dax_orb':
                        cost += quantity*entry['open']*entry['borrow_bps']/10000
                    marked = quantity*multiplier*(value-entry['open'])*side-cost
                    marks.append((mt, marked, marked-quantity*multiplier*(value+entry['open'])*.001))
                trade = opportunity(symbol, entry, dict(ts=end['end_ts']), gross-costs,
                                    gross-costs-quantity*multiplier*(price+entry['open'])*0.001, marks=marks)
                trade['size_scale_step'] = lot/quantity
                trades.append(trade)
                break
    return trades, exposures


def gold(model, data, check):
    trades, exposures = [], []
    for symbol, rows in groups(data['bars_4h']).items():
        f, ready = prepare(rows), -1
        sessions_for_symbol = [s for s in data['calendar'] if s.get('instrument') in (symbol, '*')]
        for i in range(1, len(rows)):
            check()
            entry = rows[i]
            at = ts(entry['ts'])
            if at < ready or max(ts(x['available_at']) for x in rows[:i]) > at or candle_signal('gold_macd', rows, f, i-1) is None:
                continue
            schedule = sorted((s for s in sessions_for_symbol if ts(s['close_ts']) > at and ts(s['available_at']) <= at), key=lambda s: ts(s['close_ts']))
            if len(schedule) < 20:
                raise MissingEvidence('20 known trading-session closes required')
            deadline = ts(schedule[19]['close_ts'])
            spec = observed([s for s in data['contract_specs'] if s['symbol'] == symbol], at)
            if spec is None or spec['price_currency'] != 'USD' or spec['settlement_currency'] != 'USD':
                raise MissingEvidence('Gold instrument / multiplier / USD conversion missing')
            mult, lot = spec['multiplier'], spec.get('lot_size', 1)
            price, a = entry['open'], f['atr'][i-1]
            fee = quote_cost(entry)
            planned_loss = (2*a+(2*price-2*a)*(fee+.002))*mult
            if price-2*a <= 0:
                continue
            quantity = math.floor(min(25/planned_loss, 1000/(price*mult*(1+fee+.002)))/lot)*lot
            if not quantity:
                continue
            end, exit_price = None, None
            for row in rows[i:]:
                if ts(row['end_ts']) > deadline:
                    raise MissingEvidence('No gold valuation at exact session deadline')
                hit = bar_exit(row, price-2*a, price+6*a, 1)
                if hit or ts(row['end_ts']) >= deadline:
                    end, exit_price = row, hit[0] if hit else row['close']
                    break
            if end is None:
                exposures.append(dict(symbol=symbol, entry_ts=at, reason='OPEN_GOLD_POSITION'))
                break
            costs = quantity*mult*(price+exit_price)*(quote_cost(entry)+.001)
            n = quantity*mult*(exit_price-price)-costs
            marks = []
            for mt, value in [(at, price)]+[(ts(x['end_ts']), x['close']) for x in rows[i:] if ts(x['end_ts']) <= ts(end['end_ts'])]:
                marked = quantity*mult*(value-price)-quantity*mult*(value+price)*(quote_cost(entry)+.001)
                marks.append((mt, marked, marked-quantity*mult*(value+price)*.001))
            trade = opportunity(symbol, entry, dict(ts=end['end_ts']), n, n-quantity*mult*(price+exit_price)*.001, marks=marks)
            trade['size_scale_step'] = lot/quantity
            trade['max_mark_age_seconds'] = 14400
            trades.append(trade)
            ready = ts(end['end_ts'])
    return trades, exposures


def lending(model, data, check):
    rows = sorted(data['lending_index'], key=lambda x: ts(x['ts']))
    trades, exposures, ready = [], [], -1
    for entry in rows:
        check()
        at = ts(entry['ts'])
        if at < ready or ts(entry['available_at']) > at:
            continue
        if entry['reserve'] != 'USDC' or entry['protocol'] != 'aave_v3' or entry['chain'] != 'ethereum':
            raise MissingEvidence('Wrong lending reserve/protocol')
        end = first_after(rows, at+30*86400, 60)
        if end is None:
            break
        prices = [r for r in data['token_quotes'] if r['symbol'] == 'USDC' and r['chain'] == 'ethereum']
        p1 = observed(prices, at)
        p2 = observed(prices, ts(end['ts']))
        liquidity = observed([r for r in data['withdrawal_liquidity'] if r['reserve'] == 'USDC'], ts(end['ts']))
        g1 = observed([r for r in data['gas'] if r['operation'] == 'aave_deposit'], at)
        g2 = observed([r for r in data['gas'] if r['operation'] == 'aave_withdraw'], ts(end['ts']))
        if any(x is None for x in (p1, p2, liquidity, g1, g2)) or liquidity['paused']:
            raise MissingEvidence('Missing stablecoin price/gas/withdrawal evidence')
        try:
            n = lending_pnl(1000-g1['cost_usd'], entry['index'], end['index'], p1['ask'], p2['bid'],
                            g2['cost_usd'], liquidity['withdrawable_usd'])-g1['cost_usd']
        except ValueError:
            exposures.append(dict(symbol='USDC', reason='WITHDRAWAL_BLOCKED'))
            break
        penalty = 1000*((p1['ask']-p1['bid'])+(p2['ask']-p2['bid']))/2
        marks = []
        for index in rows:
            mt = ts(index['ts'])
            if not at <= mt <= ts(end['ts']) or ts(index['available_at']) > mt:
                continue
            price = observed(prices, mt)
            gas = observed([r for r in data['gas'] if r['operation'] == 'aave_withdraw'], mt)
            if price is None or gas is None:
                continue
            marked = (1000-g1['cost_usd'])/p1['ask']*index['index']/entry['index']*price['bid']-1000-gas['cost_usd']
            spread = 1000*((p1['ask']-p1['bid'])+(price['ask']-price['bid']))/2
            marks.append((mt, marked, marked-spread, g1['cost_usd']+gas['cost_usd']))
        trade = opportunity('USDC', entry, end, n, n-penalty, marks=marks)
        trade['fixed_cost_usd'] = g1['cost_usd']+g2['cost_usd']
        trade['entry_fixed_cost_usd'] = g1['cost_usd']
        trade['max_mark_age_seconds'] = 86400
        trades.append(trade)
        ready = ts(end['ts'])
    return trades, exposures


def wallets(model, data, check):
    swaps, quotes = data['dex_swaps'], groups(data['execution_quotes'], 'token')
    rankings, trades, exposures, ready = {}, [], [], {}
    for r in swaps:
        check()
        at = ts(r['ts'])
        dt = datetime.fromtimestamp(at, timezone.utc)
        month = dt.replace(day=1, hour=0, minute=0, second=0).timestamp()
        if month not in rankings:
            eligible = observed(data['token_universe'], month)
            if eligible is None:
                raise MissingEvidence('Month-start Ethereum universe missing')
            rankings[month] = wallet_ranking([s for s in swaps if s['token'] in eligible['members'] and s['chain'] == 'ethereum'], month)
        if r['chain'] != 'ethereum' or r['side'] != 'buy' or r['wallet'] not in rankings[month] or at < ready.get(r['token'], -1):
            continue
        universe = observed(data['token_universe'], at)
        if not universe or r['token'] not in universe['members']:
            continue
        entries = [x for x in quotes.get(r['token'], []) if x['block_number'] >= r['block_number']+1 and ts(x['ts']) > at
                   and ts(x['ts']) >= ts(r['available_at']) and ts(x['available_at']) <= ts(x['ts'])]
        if not entries:
            raise MissingEvidence('Next-block executable DEX quote missing')
        entry = entries[0]
        end = first_after(quotes[r['token']], ts(entry['ts'])+86400, 60)
        if end is None or not end['sellable']:
            exposures.append(dict(symbol=r['token'], reason='TOKEN_EXIT_NOT_EXECUTABLE'))
            ready[r['token']] = math.inf
            continue
        n, s, q = long_roundtrip(entry, end, 1000-entry['gas_usd'])
        gas = entry['gas_usd']+end['gas_usd']
        marks = long_marks(entry, [x for x in quotes[r['token']] if ts(x['ts']) <= ts(end['ts'])], q, gas=True)
        trade = opportunity(r['token'], entry, end, n-gas, s-gas, marks=marks)
        trade['fixed_cost_usd'] = gas
        trade['entry_fixed_cost_usd'] = entry['gas_usd']
        trades.append(trade)
        ready[r['token']] = ts(end['ts'])
    return trades, exposures


def run_specialized(model, data, check=lambda: None):
    key = model['id']
    if key in ('book_continue', 'book_reclaim'):
        return orderflow(model, data, check)
    if key in ('funding_carry', 'funding_cross', 'spot_dislocation', 'basis_convergence'):
        return paired(model, data, check)
    if key in ('long_put', 'cash_put', 'put_spread'):
        return options(model, data, check)
    if key == 'fixed_grid':
        return grid(model, data, check)
    if key in ('dax_orb', 'gap_continue', 'gap_fade'):
        return sessions(model, data, check)
    if key == 'gold_macd':
        return gold(model, data, check)
    if key == 'aave_lending':
        return lending(model, data, check)
    if key == 'wallet_follow':
        return wallets(model, data, check)
    raise MissingEvidence('Instrument-specific daily mark adapter is not certified for this model')
