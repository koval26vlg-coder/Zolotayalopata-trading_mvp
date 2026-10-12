"""Cash-reserved opportunity replay with mandatory observed daily valuation.

An opportunity's future exit is never spendable at entry. Its planned capital is
scaled down using only known equity; fixed costs are not scaled down with size.
"""
from datetime import datetime, timezone
import math

from .data import day, ts
from .adapters import MissingEvidence


def replay_opportunities(opportunities, exposures, plan, start, end, *, stress=False, check=lambda: None):
    if exposures:
        raise MissingEvidence('Open/unexecutable positions require terminal valuation; no completed-equity fiction')
    first, last = ts(start+'T00:00:00Z'), ts(end+'T00:00:00Z')
    relevant = sorted([t for t in opportunities if first <= t['entry_ts'] < last],
                      key=lambda t: (t['entry_ts'], t['symbol']))
    cash = plan['portfolio']['initial_cash']
    active, trades, daily = [], [], {}
    points = {first, last}
    for t in relevant:
        if t['exit_ts'] <= t['entry_ts'] or t['capital'] <= 0:
            raise ValueError('Invalid opportunity timing/capital')
        points.add(t['entry_ts'])
        if t['exit_ts'] <= last:
            points.add(t['exit_ts'])
    points.update(range(int(first)+86400, int(last)+1, 86400))

    def pnl(t, at):
        if at >= t['exit_ts']:
            return t['stress_pnl'] if stress else t['pnl']
        marks = [m for m in t['marks'] if m[0] <= at]
        if not marks:
            raise MissingEvidence('Missing observed position mark at portfolio timestamp')
        mark = max(marks, key=lambda m: m[0])
        if at-mark[0] > t.get('max_mark_age_seconds', 3600):
            raise MissingEvidence('Position valuation too stale for daily/entry accounting')
        if len(mark) not in (3, 4):
            raise MissingEvidence('Both normal and stressed liquidation marks required')
        return mark[2 if stress else 1]

    def scaled(t, at, scale):
        if at < t['exit_ts'] and t.get('fixed_cost_usd', 0):
            mark = max((m for m in t['marks'] if m[0] <= at), default=None)
            if mark is None or len(mark) != 4:
                raise MissingEvidence('Missing contemporaneous fixed-cost mark')
            fixed = mark[3]
        else:
            fixed = t.get('fixed_cost_usd', 0)
        return (pnl(t, at)+fixed)*scale-fixed

    for at in sorted(points):
        check()
        for position in list(active):
            t, scale = position
            if t['exit_ts'] <= at:
                realized = scaled(t, at, scale)
                cash += t['capital']*scale+realized
                trades.append(dict(symbol=t['symbol'], entry_ts=t['entry_ts'], exit_ts=t['exit_ts'],
                                   pnl=realized, capital=t['capital']*scale, turnover=t['turnover']*scale,
                                   reason=t['reason'], size_scale=scale))
                active.remove(position)
        equity = cash+sum(t['capital']*s+scaled(t, at, s) for t, s in active)
        for t in [r for r in relevant if r['entry_ts'] == at]:
            if equity <= 0 or cash <= 0:
                break
            budget = min(cash, .1*equity)
            scale = min(1.0, budget/t['capital'])
            step = t.get('size_scale_step', 0)
            if step:
                scale = math.floor(scale/step)*step
            if scale <= 0 or t['capital']*scale <= t.get('entry_fixed_cost_usd', 0):
                continue
            # Only completely represented instruments may enter a portfolio.
            pnl(t, at)
            cash -= t['capital']*scale
            active.append((t, scale))
        if at > first and at % 86400 == 0:
            value = cash+sum(t['capital']*s+scaled(t, at, s) for t, s in active)
            daily[day(at-.001)] = value
    return dict(trades=trades, daily_equity=daily,
                open_positions=[dict(symbol=t['symbol'], entry_ts=t['entry_ts']) for t, _ in active],
                execution_quality='NORMALIZED_EVIDENCE_NOT_INDEPENDENTLY_CERTIFIED', stress=stress)
