from __future__ import annotations

from datetime import date, timedelta
import math
import random

from .data import day


def holm(pvalues, family_size=20):
    if len(pvalues) > family_size or any(not 0 <= p <= 1 for p in pvalues.values()):
        raise ValueError('Invalid fixed hypothesis family')
    adjusted, previous = {}, 0.0
    for i, (key, p) in enumerate(sorted(pvalues.items(), key=lambda x: (x[1], x[0]))):
        previous = min(1.0, max(previous, p*(family_size-i)))
        adjusted[key] = previous
    return adjusted


def bootstrap_pvalue(values, replicates=5000, block=7, seed=20261006):
    if len(values) < 28 or not all(math.isfinite(x) for x in values):
        return None
    n = len(values)
    mean = sum(values)/n
    if mean <= 0:
        return 1.0
    centered = [v-mean for v in values]
    sums = [sum(centered[(i+j) % n] for j in range(block)) for i in range(n)]
    full, remainder = divmod(n, block)
    tails = [sum(centered[(i+j) % n] for j in range(remainder)) for i in range(n)]
    rng, exceed = random.Random(seed), 0
    for _ in range(replicates):
        total = sum(sums[rng.randrange(n)] for _ in range(full))
        if remainder:
            total += tails[rng.randrange(n)]
        exceed += total/n >= mean
    return (exceed+1)/(replicates+1)


def temporal_group_ids(trades):
    groups, end, entry_day = 0, -1, None
    ids = {}
    for index, t in sorted(enumerate(trades), key=lambda pair: (pair[1]['entry_ts'], pair[1]['exit_ts'], pair[0])):
        d = day(t['entry_ts'])
        if t['entry_ts'] > end and d != entry_day:
            groups += 1
            end = t['exit_ts']
        else:
            end = max(end, t['exit_ts'])
        entry_day = d
        ids[index] = groups
    return ids


def temporal_groups(trades):
    return len(set(temporal_group_ids(trades).values()))


def summarize(trades, daily_equity, initial=10000):
    positive = sum(max(t['pnl'], 0) for t in trades)
    negative = -sum(min(t['pnl'], 0) for t in trades)
    net = sum(t['pnl'] for t in trades)
    bases, events = {}, {}
    groups = temporal_group_ids(trades)
    for index, t in enumerate(trades):
        bases[t['symbol']] = bases.get(t['symbol'], 0)+max(t['pnl'], 0)
        events[groups[index]] = events.get(groups[index], 0)+max(t['pnl'], 0)
    peak, dd, previous, deltas = initial, 0, initial, []
    ordered = sorted(daily_equity.items())
    complete_calendar = bool(ordered)
    for i, (d, v) in enumerate(ordered):
        if not math.isfinite(v):
            raise ValueError('Nonfinite equity')
        if i and date.fromisoformat(d)-date.fromisoformat(ordered[i-1][0]) != timedelta(days=1):
            complete_calendar = False
        deltas.append(v-previous)
        previous = v
        peak = max(peak, v)
        dd = max(dd, (peak-v)/peak if peak > 0 else 1)
    pvalue = bootstrap_pvalue(deltas) if complete_calendar else None
    return dict(trades=len(trades), temporal_groups=temporal_groups(trades),
                expectancy=net/len(trades) if trades else None, realized_net=net if trades else None,
                mtm_net=ordered[-1][1]-initial if ordered else None,
                profit_factor=positive/negative if negative else None,
                profit_factor_unbounded=bool(positive and not negative),
                win_rate=sum(t['pnl'] > 0 for t in trades)/len(trades) if trades else None,
                max_daily_drawdown=dd if ordered else None, calendar_days=len(ordered),
                calendar_complete=complete_calendar, bootstrap_p=pvalue,
                turnover=sum(t.get('turnover', 0) for t in trades),
                single_event_positive_share=max(events.values(), default=0)/positive if positive else None,
                single_base_positive_share=max(bases.values(), default=0)/positive if positive else None)


def period_metrics(replay, start, end, initial=10000):
    # Keep marked equity at boundaries; realized trades crossing a split are
    # reported separately and cannot masquerade as independent OOS events.
    rows = {d: v for d, v in replay['daily_equity'].items() if start <= d < end}
    before = [v for d, v in sorted(replay['daily_equity'].items()) if d < start]
    baseline = before[-1] if before else initial
    normalized = {d: initial+(v-baseline) for d, v in rows.items()}
    trades = [t for t in replay['trades'] if start <= day(t['entry_ts']) and day(t['exit_ts']) < end]
    r = summarize(trades, normalized, initial)
    r['split_crossing_trades'] = sum(day(t['entry_ts']) < start <= day(t['exit_ts']) < end for t in replay['trades'])
    return r


def walk_forward(replay):
    first, last = date(2025, 1, 1), date(2026, 1, 1)
    days = (last-first).days
    return [period_metrics(replay, (first+timedelta(days=days*i//5)).isoformat(),
                           (first+timedelta(days=days*(i+1)//5)).isoformat()) for i in range(5)]


def candidate_status(result, adjusted_p, plan):
    if result.get('open_positions'):
        return 'INCONCLUSIVE_OPEN_EXPOSURE'
    if result.get('partial_periods'):
        return 'INCONCLUSIVE_PARTIAL_COVERAGE'
    if result.get('exposure') != 'UNSEEN_CERTIFIED' or result.get('execution_quality') != 'EXECUTABLE_CERTIFIED':
        return 'EXPLORATORY_ONLY'
    m, s = result['oos'], plan['statistics']
    if (m['trades'] < s['min_oos_trades'] or m['temporal_groups'] < s['min_temporal_groups']
            or m['calendar_days'] < s['min_oos_calendar_days'] or not m['calendar_complete']):
        return 'INSUFFICIENT_DATA'
    if any((m[k] is None or m[k] > 0.25) for k in ('single_event_positive_share', 'single_base_positive_share')):
        return 'INCONCLUSIVE_CONCENTRATION'
    passed = (m['mtm_net'] > 0 and m['expectancy'] > 0 and
              (m['profit_factor_unbounded'] or (m['profit_factor'] or 0) >= s['min_pf']) and
              sum((f['mtm_net'] or 0) > 0 for f in result['folds']) >= s['positive_wf_folds'] and
              result['stress_oos']['mtm_net'] is not None and result['stress_oos']['mtm_net'] >= 0 and
              m['max_daily_drawdown'] <= s['max_drawdown'] and adjusted_p is not None and adjusted_p <= s['alpha'])
    return 'HISTORICAL_CANDIDATE_NOT_LIVE' if passed else 'REJECT_FIXED_MODEL'
