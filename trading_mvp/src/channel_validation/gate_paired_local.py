"""Offline full-file census of six completed Gate downloads. No trading results."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
from pathlib import Path

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable

RUN_ID = 'history_gate_paired_local_v17_20261008'
PARENT_ID = 'history_gate_paired_v16_20261008'
PARENT = OUTPUT_ROOT/'continuation-v16'
SOURCE = OUTPUT_ROOT/'runs'/PARENT_ID/'artifacts/gate-paired-audit'
PARENT_AUDIT_SHA = 'bc526f0388ad0fa4a65493950d75953d97756945c57278ee6f0363ae6c78a60b'
PARENT_COMPLETION_SHA = '9f9b2331a51a196388cbee43a962ddfe226e847a3618bcc8765cf2f06b855074'
MAX_DECODED = 32*1024**2
MAX_TOTAL_DECODED = 128*1024**2
MAX_LINE = 1024**2
MAX_ROWS = 200000


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean numeric value')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid number') from exc
    if not result.is_finite():
        raise ValueError('Nonfinite number')
    return result


def micros(value, scale):
    result = number(value)*scale
    if result != result.to_integral_value() or not 946684800000000 <= result < 4102444800000000:
        raise ValueError('Invalid time precision or source unit')
    return int(result)


def normalize_book(row, spec):
    spot = spec['market'] == 'spot'
    if spec['market'] not in ('spot', 'futures_usdt') or not isinstance(row, dict):
        raise ValueError('Unknown book market/schema')
    scale = 1000 if spot else 1000000
    current = micros(row['current'], scale)
    update = micros(row['update'], scale) if 'update' in row else None
    if update is not None and update > current:
        raise ValueError('Exchange update after capture timestamp')
    levels = {}
    for side in ('bids', 'asks'):
        raw = row[side]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 10000:
            raise ValueError('Empty or excessive book depth')
        prices, normalized = [], []
        for item in raw:
            if spot:
                if not isinstance(item, list) or len(item) != 2:
                    raise ValueError('Unexpected spot level')
                price, size = map(number, item)
            else:
                if not isinstance(item, dict):
                    raise ValueError('Unexpected futures level')
                price, size = number(item['p']), number(item['s'])
            if price <= 0 or size <= 0:
                raise ValueError('Nonpositive price/size')
            prices.append(price)
            normalized.append(dict(price=str(price), raw_size=str(size)))
        if len(set(prices)) != len(prices) or prices != sorted(prices, reverse=side == 'bids'):
            raise ValueError('Duplicate or unordered book prices')
        levels[side] = normalized
    if number(levels['bids'][0]['price']) >= number(levels['asks'][0]['price']):
        raise ValueError('Locked/crossed book')
    identifier = row.get('id')
    if identifier is not None:
        identifier = number(identifier)
        if identifier < 0 or identifier != identifier.to_integral_value():
            raise ValueError('Invalid update id')
        identifier = str(identifier)
    return dict(schema='gate_book_diagnostic_v1', market=spec['market'], symbol=spec['symbol'],
                event_time_us=current, exchange_update_us=update, source_id=identifier,
                source_time_unit='milliseconds' if spot else 'seconds',
                bids=levels['bids'], asks=levels['asks'], size_unit='UNVERIFIED_NATIVE_SIZE',
                size_unit_verified=False, historical_observation_time_verified=False,
                eligible_for_evaluation=False)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def normalize_line(raw, spec):
    if spec['kind'] == 'orderbooks_slice':
        return normalize_book(json.loads(raw, parse_float=Decimal, object_pairs_hook=unique_object), spec)
    if spec['kind'] != 'funding_applies' or spec['market'] != 'futures_usdt':
        raise ValueError('Only books and actual funding allowed')
    fields = raw.decode('utf-8').strip().split(',')
    if len(fields) != 2:
        raise ValueError('Unexpected actual funding schema')
    return dict(schema='gate_funding_diagnostic_v1', symbol=spec['symbol'], market=spec['market'],
                event_time_us=micros(fields[0], 1000000), rate=str(number(fields[1])),
                source_time_unit='seconds', settlement_semantics_verified=False,
                historical_observation_time_verified=False, eligible_for_evaluation=False)


def window(spec):
    start = datetime.strptime(spec['month'], '%Y%m').replace(tzinfo=timezone.utc)
    end = (int(start.timestamp())+3600) if spec['kind'] == 'orderbooks_slice' else int(
        datetime(start.year+(start.month == 12), start.month % 12+1, 1, tzinfo=timezone.utc).timestamp())
    return int(start.timestamp())*1000000, end*1000000


def scan_archive(path, spec, *, max_decoded_bytes=MAX_DECODED, max_line_bytes=MAX_LINE,
                 max_rows=MAX_ROWS, check=lambda: None):
    first_bound, last_bound = window(spec)
    decoded = physical = blanks = valid = invalid = reversals = equal = outside = duplicates = 0
    first = last = previous = largest_gap = None
    min_depth = dict(bids=None, asks=None)
    max_depth = dict(bids=0, asks=0)
    missing_update = 0
    seen, errors, samples = set(), [], []
    gaps = Counter()
    normalized_hash, decoded_hash = hashlib.sha256(), hashlib.sha256()
    tail = None
    check()
    with gzip.open(path, 'rb') as stream:
        while True:
            if physical % 1000 == 0:
                check()
            raw = stream.readline(min(max_line_bytes+1, max_decoded_bytes-decoded+1))
            if not raw:
                break  # gzip verifies CRC and trailer before EOF is accepted.
            if len(raw) > max_line_bytes or decoded+len(raw) > max_decoded_bytes or physical >= max_rows:
                raise ValueError('Decoded byte, line or row budget exceeded')
            physical += 1
            decoded += len(raw)
            decoded_hash.update(raw)
            if not raw.strip():
                blanks += 1
                continue
            try:
                row = normalize_line(raw, spec)
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                invalid += 1
                if len(errors) < 5:
                    errors.append(dict(line=physical, error=str(exc)))
                continue
            valid += 1
            at = row['event_time_us']
            first = at if first is None else min(first, at)
            last = at if last is None else max(last, at)
            outside += not first_bound <= at < last_bound
            if previous is not None:
                reversals += at < previous
                equal += at == previous
                delta = at-previous
                if delta > 0:
                    largest_gap = delta if largest_gap is None else max(largest_gap, delta)
                    if spec['kind'] == 'funding_applies':
                        gaps[str(delta)] += 1
            previous = at
            digest = canonical_hash(row)
            duplicates += digest in seen
            seen.add(digest)
            normalized_hash.update((digest+'\n').encode('ascii'))
            if spec['kind'] == 'orderbooks_slice':
                missing_update += row['exchange_update_us'] is None
                for side in ('bids', 'asks'):
                    depth = len(row[side])
                    min_depth[side] = depth if min_depth[side] is None else min(min_depth[side], depth)
                    max_depth[side] = max(max_depth[side], depth)
            tail = dict(line=physical, row=row)
            if len(samples) < 2:
                samples.append(tail)
    check()
    if tail is not None and tail['line'] not in [x['line'] for x in samples]:
        samples.append(tail)
    return dict(gzip_crc_verified=True, physical_lines=physical, blank_lines=blanks,
                decoded_bytes=decoded, decoded_sha256=decoded_hash.hexdigest(), valid_rows=valid,
                invalid_rows=invalid, invalid_examples=errors, first_time_us=first, last_time_us=last,
                window_start_us=first_bound, window_end_us=last_bound,
                time_reversal_count=reversals, equal_time_count=equal, duplicate_record_count=duplicates,
                out_of_window_count=outside, largest_positive_gap_us=largest_gap,
                positive_gap_counts_us=dict(sorted(gaps.items())), min_depth=min_depth, max_depth=max_depth,
                missing_exchange_update_count=missing_update, samples=samples,
                normalized_sequence_hash=normalized_hash.hexdigest(),
                structural_clean=valid > 0 and not any((invalid, reversals, duplicates, outside)),
                eligible_for_evaluation=False)


def selected_records(records):
    selected = [r for r in records if r['kind'] in ('orderbooks_slice', 'funding_applies')]
    if any(not r['body']['complete'] for r in selected):
        raise ValueError('Partial response cannot be used for a full-file census')
    return selected


def preflight():
    if file_hash(PARENT/'gate-paired-audit.json') != PARENT_AUDIT_SHA or file_hash(
            PARENT/'probe-completion.json') != PARENT_COMPLETION_SHA:
        raise ValueError('Parent checkpoint changed')
    parent = json.loads((PARENT/'gate-paired-audit.json').read_text())
    completion = json.loads((PARENT/'probe-completion.json').read_text())
    if completion['status'] != 'COMPLETE' or completion['exit_code'] != 0 or completion['plan_hash'] != build_plan()['plan_hash']:
        raise ValueError('Parent not complete or wrong research plan')
    records = selected_records(parent['records'])
    if len(records) != 6:
        raise ValueError('Exactly six completed local inputs required')
    inputs = []
    for record in records:
        path = (SOURCE/record['raw_file']).resolve()
        if (not path.is_relative_to(SOURCE.resolve()) or file_hash(path) != record['raw_sha256'] or
                path.stat().st_size != record['body']['bytes_read']):
            raise ValueError('Local archive input hash or size mismatch')
        inputs.append(dict(path=str(path), sha256=record['raw_sha256'], bytes=path.stat().st_size,
                           kind=record['kind'], month=record['month'], market=record['market'],
                           symbol=record['symbol'], source_url=record['url']))
    return dict(schema='gate_paired_local_input_binding_v1', inputs=inputs,
                parent_audit_sha256=PARENT_AUDIT_SHA, parent_completion_sha256=PARENT_COMPLETION_SHA,
                plan_hash=build_plan()['plan_hash'], max_runtime_sec=300,
                max_decoded_bytes_per_file=MAX_DECODED, max_total_decoded_bytes=MAX_TOTAL_DECODED,
                max_line_bytes=MAX_LINE, max_rows_per_file=MAX_ROWS, network_requests=0,
                eligible_for_evaluation=False)


def audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Local census namespace already used')
    binding = preflight()
    frozen = json.loads((OUTPUT_ROOT/'continuation-v17/local-input-plan.json').read_text())
    if frozen != dict(binding, input_binding_hash=canonical_hash(binding)):
        raise ValueError('Local input plan changed')
    write_immutable(output/'input-binding.json', frozen)
    reports, total = [], 0
    for i, spec in enumerate(binding['inputs'], 1):
        check()
        print(f"Local archive {i}/6: {spec['market']} {spec['kind']} {spec['month']}", flush=True)
        scan = scan_archive(Path(spec['path']), spec, check=check,
                            max_decoded_bytes=min(MAX_DECODED, MAX_TOTAL_DECODED-total))
        total += scan['decoded_bytes']
        if file_hash(spec['path']) != spec['sha256']:
            raise ValueError('Input changed during scan')
        report = dict(input=spec, **scan)
        reports.append(report)
        write_immutable(output/f'{i:02d}.census.json', report)
        print(f"  CRC verified; rows={scan['valid_rows']}; invalid={scan['invalid_rows']}; "
              f"time_reversals={scan['time_reversal_count']}; duplicates={scan['duplicate_record_count']}", flush=True)
    result = dict(schema='gate_paired_local_census_v1', input_binding_hash=canonical_hash(binding),
                  plan_hash=binding['plan_hash'], runtime_binding=runtime_binding(),
                  status='LOCAL_CENSUS_COMPLETE_NOT_BACKTEST', reports=reports,
                  total_decoded_bytes=total, total_valid_rows=sum(r['valid_rows'] for r in reports),
                  full_file_crc_checks=len(reports), network_requests=0, metrics=None,
                  eligible_for_evaluation=False)
    write_immutable(output/'audit.json', dict(result, audit_hash=canonical_hash(result)))
    return result
