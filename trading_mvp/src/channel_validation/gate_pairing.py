"""Offline, conditional source-order join diagnostics; never an execution feed."""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from .contract import OUTPUT_ROOT, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_paired_local import MAX_DECODED, MAX_LINE, MAX_ROWS, normalize_line, window
from .gate_paired_local import preflight as local_preflight

RUN_ID = 'history_gate_pairing_v18_20261009'
PARENT = OUTPUT_ROOT/'continuation-v17'
PARENT_HASHES = {
    'evidence-index.json': 'e5c16bcb1840ef63f2c24d3f987cd355f87fbccbce62e827e8f5320a73ca8372',
    'local-census.json': '80e2189fde2c690a69bb286ddb2d8ca2065cf0e4b9b74c3f66f50fc560e7394f',
    'local-completion.json': '3d36109c8904d0ab85d0beef203c251c088321cf00f9c7470bcb52d9759b3625',
}
MARKETS = ('spot', 'futures_usdt')
POLICY = dict(
    source_order='Never sort, interpolate or rewrite input records',
    frontier='Synthetic max(current timestamps seen, window start), not historical arrival time',
    duplicate='Exact normalized record hash; do not refresh or restore quote',
    late='current below source frontier: keep prior state, do not apply late record',
    same_time_conflict='Different record at accepted current: invalidate until strictly newer record',
    invalid='Unknown-time error invalidates at preceding frontier; earliest conservative diagnostic boundary',
    exchange_update='Missing or regressing update invalidates; newer current must not disguise old update',
    tie='Process all same-frontier source events before emitting at most one frame',
    age='Separate current and exchange update age at state-changing frames; not time weighted',
    eof='No extrapolated events; retained leg may age as other stream advances; no certified freshness',
    freshness_acceptance_threshold_us=None,
    historical_observation_time_verified=False, eligible_for_evaluation=False,
)


def archive_events(spec, stats, *, max_decoded_bytes, max_rows, check):
    path = Path(spec['path'])
    if path.stat().st_size != spec['bytes'] or file_hash(path) != spec['sha256']:
        raise ValueError('Archive input hash/size mismatch')
    start, end = window(spec)
    frontier, accepted_time, update_floor = start, None, None
    seen = set()
    counts = Counter()
    decoded_hash = hashlib.sha256()
    event_hash = hashlib.sha256()
    stats.update(physical_lines=0, blank_lines=0, decoded_bytes=0, gzip_crc_verified=False,
                 anomaly_examples=[], dispositions={})
    with gzip.open(path, 'rb') as stream:
        while True:
            if stats['physical_lines'] % 1000 == 0:
                check()
            raw = stream.readline(min(MAX_LINE+1, max_decoded_bytes-stats['decoded_bytes']+1))
            if not raw:
                break
            if (len(raw) > MAX_LINE or stats['decoded_bytes']+len(raw) > max_decoded_bytes or
                    stats['physical_lines'] >= max_rows):
                raise ValueError('Pairing byte/line/row budget exceeded')
            stats['physical_lines'] += 1
            stats['decoded_bytes'] += len(raw)
            decoded_hash.update(raw)
            if not raw.strip():
                stats['blank_lines'] += 1
                continue
            row, digest = None, None
            try:
                row = normalize_line(raw, spec)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                disposition = 'INVALID_RECORD_INVALIDATED'
            if row is not None:
                at, update = row['event_time_us'], row['exchange_update_us']
                if not start <= at < end:
                    raise ValueError('Book outside frozen source window')
                digest = canonical_hash(row)
                if digest in seen:
                    disposition = 'DUPLICATE_NOT_APPLIED'
                elif at < frontier:
                    disposition = 'LATE_NOT_APPLIED'
                elif at == accepted_time:
                    disposition = 'TIME_CONFLICT_INVALIDATED'
                elif update is None:
                    disposition = 'MISSING_UPDATE_INVALIDATED'
                elif update_floor is not None and update < update_floor:
                    disposition = 'UPDATE_REGRESSION_INVALIDATED'
                else:
                    disposition = 'ACCEPTED'
                    accepted_time, update_floor = at, update
                seen.add(digest)
                frontier = max(frontier, at)
            event = dict(line=stats['physical_lines'], frontier_us=frontier, disposition=disposition,
                         source_row_hash=digest, raw_line_sha256=hashlib.sha256(raw).hexdigest())
            counts[disposition] += 1
            event_hash.update((canonical_hash(event)+'\n').encode())
            if disposition != 'ACCEPTED' and len(stats['anomaly_examples']) < 12:
                stats['anomaly_examples'].append(dict(event))
            if disposition == 'ACCEPTED':
                event['row'] = row
            yield event
    check()
    if path.stat().st_size != spec['bytes'] or file_hash(path) != spec['sha256']:
        raise ValueError('Archive changed during pairing')
    stats.update(gzip_crc_verified=True, dispositions=dict(sorted(counts.items())),
                 decoded_sha256=decoded_hash.hexdigest(), event_sequence_hash=event_hash.hexdigest())


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return dict(count=0, min=None, p50=None, p95=None, p99=None, max=None)
    return dict(count=len(values), min=ordered[0], max=ordered[-1],
                **{f'p{p}': ordered[(len(ordered)*p+99)//100-1] for p in (50, 95, 99)})


def pair_archives(specs, *, max_decoded_bytes=MAX_DECODED, max_rows=MAX_ROWS, check=lambda: None):
    check()
    by_market = {s['market']: s for s in specs}
    if (len(specs) != 2 or set(by_market) != set(MARKETS) or
            len({(s['symbol'], s['month']) for s in specs}) != 1 or
            any(s['kind'] != 'orderbooks_slice' for s in specs)):
        raise ValueError('Exactly one matching spot/perp source pair required')
    stats = {m: {} for m in MARKETS}
    streams = {m: archive_events(by_market[m], stats[m], max_decoded_bytes=max_decoded_bytes,
                                max_rows=max_rows, check=check) for m in MARKETS}
    heads, state = {}, dict.fromkeys(MARKETS)
    ages = {m: dict(capture=[], exchange_update=[]) for m in MARKETS}
    paired = missing = ignored = frames = 0
    samples, tail = [], None
    pair_hash = hashlib.sha256()
    try:
        heads = {m: next(streams[m], None) for m in MARKETS}
        while any(heads.values()):
            check()
            at = min(e['frontier_us'] for e in heads.values() if e is not None)
            changed = False
            for market in MARKETS:
                while heads[market] is not None and heads[market]['frontier_us'] == at:
                    e = heads[market]
                    if e['disposition'] == 'ACCEPTED':
                        state[market] = e
                        changed = True
                    elif e['disposition'].endswith('_INVALIDATED'):
                        state[market] = None
                        changed = True
                    else:
                        ignored += 1
                    heads[market] = next(streams[market], None)
            if not changed:
                continue
            frames += 1
            if any(v is None for v in state.values()):
                missing += 1
                continue
            legs = {}
            for market, event in state.items():
                row = event['row']
                capture_age = at-row['event_time_us']
                update_age = at-row['exchange_update_us']
                if not 0 <= capture_age <= update_age:
                    raise ValueError('Future leg or invalid age in conditional join')
                ages[market]['capture'].append(capture_age)
                ages[market]['exchange_update'].append(update_age)
                legs[market] = dict(line=event['line'], source_row_hash=event['source_row_hash'],
                                    event_time_us=row['event_time_us'], exchange_update_us=row['exchange_update_us'],
                                    capture_age_us=capture_age, update_age_us=update_age)
            tail = dict(synthetic_frontier_us=at, legs=legs, eligible_for_evaluation=False)
            pair_hash.update((canonical_hash(tail)+'\n').encode())
            paired += 1
            if len(samples) < 3:
                samples.append(tail)
    finally:
        for stream in streams.values():
            stream.close()
    if tail is not None and tail not in samples:
        samples.append(tail)
    return dict(schema='gate_conditional_pair_diagnostic_v1', month=specs[0]['month'], symbol=specs[0]['symbol'],
                sources=stats, state_change_frames=frames, missing_leg_frames=missing, paired_frames=paired,
                ignored_events=ignored, age_us={m: {k: distribution(v) for k, v in a.items()} for m, a in ages.items()},
                samples=samples, pair_sequence_hash=pair_hash.hexdigest(), policy=POLICY,
                freshness_acceptance_threshold_us=None, metrics=None, eligible_for_evaluation=False,
                historical_observation_time_verified=False)


def preflight():
    for name, digest in PARENT_HASHES.items():
        if file_hash(PARENT/name) != digest:
            raise ValueError('Local census parent changed')
    completion = json.loads((PARENT/'local-completion.json').read_text())
    binding = local_preflight()
    if (completion['status'] != 'COMPLETE' or completion['exit_code'] != 0 or
            completion['plan_hash'] != binding['plan_hash']):
        raise ValueError('Local census incomplete/wrong plan')
    for item in json.loads((PARENT/'evidence-index.json').read_text())['files']:
        path = (PARENT/item['file']).resolve()
        if not path.is_relative_to(PARENT.resolve()) or file_hash(path) != item['sha256']:
            raise ValueError('Parent evidence drift')
    specs = [s for s in binding['inputs'] if s['kind'] == 'orderbooks_slice']
    if len(specs) != 4:
        raise ValueError('Four completed book archives required')
    return dict(schema='gate_pairing_input_plan_v1', plan_hash=binding['plan_hash'], inputs=specs,
                parent_hashes=PARENT_HASHES, policy=POLICY, max_runtime_sec=300,
                max_decoded_bytes_per_file=MAX_DECODED, max_total_decoded_bytes=4*MAX_DECODED,
                max_rows_per_file=MAX_ROWS, network_requests=0, eligible_for_evaluation=False)


def audit(output, check):
    output = Path(output)
    if output.resolve() != (OUTPUT_ROOT/'runs'/RUN_ID/'artifacts/gate-pairing').resolve():
        raise ValueError('Fixed diagnostic namespace required')
    if output.exists():
        raise FileExistsError('Pairing already attempted')
    binding = preflight()
    frozen = json.loads((OUTPUT_ROOT/'continuation-v18/local-input-plan.json').read_text())
    if frozen != dict(binding, input_binding_hash=canonical_hash(binding)):
        raise ValueError('Pairing diagnostic input plan drift')
    write_immutable(output/'input-binding.json', frozen)
    reports = []
    for month in sorted({s['month'] for s in binding['inputs']}):
        print(f'Conditional source-order pairing: {month}; no network or PnL', flush=True)
        specs = [s for s in binding['inputs'] if s['month'] == month]
        report = pair_archives(specs, check=check)
        reports.append(report)
        write_immutable(output/(month+'.json'), report)
        print(f"  paired frames={report['paired_frames']}; missing-leg frames={report['missing_leg_frames']}", flush=True)
    check()
    if preflight() != binding:
        raise ValueError('Inputs changed during diagnostic')
    result = dict(schema='gate_pairing_audit_v1', plan_hash=binding['plan_hash'], runtime_binding=runtime_binding(),
                  input_binding_hash=canonical_hash(binding), status='CONDITIONAL_DIAGNOSTIC_NOT_EXECUTION_HISTORY',
                  reports=reports, network_requests=0, metrics=None, eligible_for_evaluation=False,
                  historical_observation_time_verified=False, source_order_preserved=True)
    write_immutable(output/'audit.json', dict(result, audit_hash=canonical_hash(result)))
    return result
