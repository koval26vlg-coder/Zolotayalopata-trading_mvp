"""One serial, bounded depth writer. Shipped manifest is offline-only."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from global_market_writer_claim import claim_global_market_writer, release_global_market_writer
from premarket_forward_depth_quality import canonical, decode, ref
from premarket_forward_depth_watch import _book_request, _levels, summarise
from premarket_forward_depth_plan import validate_plan
from research_checkpoint import verify_ref

BASE_PLAN = 'docs/plans/premarket-forward-depth-planonly-20260902-v6.json'
MANIFEST = 'docs/plans/premarket-depth-coordinator-runtime-20261006-v1.json'
CLAIM = 'docs/agent-log/active-market-data-writer-claim.json'
OUTPUT_ROOT = 'docs/analysis/premarket-depth-coordinator-runs'
SCHEMA = 'premarket_depth_serial_coordinator_runtime_v1'
LIMITS = {'max_events': 2, 'max_runtime_sec': 14400, 'max_http_attempts': 3200,
          'max_response_total_bytes': 256 * 1024**2, 'max_output_bytes': 64 * 1024**2,
          'min_free_bytes': 1024**3}
CODE = ('trading_mvp/src/premarket_depth_coordinator.py',
        'trading_mvp/src/global_market_writer_claim.py',
        'trading_mvp/src/premarket_forward_depth_plan.py',
        'trading_mvp/src/premarket_forward_depth_watch.py',
        'trading_mvp/src/premarket_forward_depth_quality.py',
        'trading_mvp/src/research_checkpoint.py',
        'tools/start_premarket_depth_coordinator_visible.ps1',
        'tools/check_active_run_gate.ps1', 'tools/check_trading_mvp_autopilot.ps1')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def require_execution_guard(state, runtime_hash, *, now=None):
    from datetime import datetime
    now = time.time() if now is None else now
    stamp = datetime.fromisoformat(state['observed_at_utc'].replace('Z', '+00:00')).timestamp()
    usage = state.get('usage', {})
    if (not 0 <= now - stamp <= 300 or state.get('stop_new_actions') is not False
            or state.get('decision') != 'RUN_PREMARKET_DEPTH_COORDINATOR'
            or state.get('runtime_manifest_hash') != runtime_hash
            or usage.get('status') != 'AVAILABLE' or usage.get('decision') != 'CONTINUE'
            or not isinstance(usage.get('remaining_percent'), (float, int))
            or not 15 < usage['remaining_percent'] <= 100
            or state.get('gate', {}).get('status') != 'READY_FOR_POSTPROCESS'):
        raise ValueError('fresh collection-enabled controller binding required')


def validate_events(events, plan, limits):
    if not 1 <= len(events) <= limits['max_events']:
        raise ValueError('batch capacity exceeded; never silently select a subset')
    identities = set()
    cap, qual = plan['capture'], plan['qualification']
    for e in events:
        if e.get('venue') not in ('gate', 'okx'):
            raise ValueError('venue outside frozen scope')
        for key in ('base', 'spot_symbol', 'perp_symbol'):
            if not isinstance(e.get(key), str) or not 1 <= len(e[key]) <= 128 or any(ord(c) < 32 for c in e[key]):
                raise ValueError('invalid event identity')
        for key in ('capture_from_ts', 'capture_to_ts', 't0_ts', 'perp_launched_ts', 'perp_ct_val'):
            if type(e.get(key)) not in (int, float) or not math.isfinite(e[key]):
                raise ValueError('invalid event number')
        start, end, t0 = (e[k] for k in ('capture_from_ts', 'capture_to_ts', 't0_ts'))
        if (not t0 - cap['window_before_min'] * 60 <= start < t0 < end
                or end != t0 + cap['window_after_min'] * 60
                or t0 - start < plan['notice_limit']['minimum_useful_pre_min'] * 60
                or e['perp_ct_val'] <= 0
                or not qual['min_lead_sec'] <= t0 - e['perp_launched_ts'] <= qual['max_lead_days'] * 86400):
            raise ValueError('event outside frozen qualification/window contract')
        identity = (e['venue'], e['base'], t0)
        if identity in identities:
            raise ValueError('duplicate event')
        identities.add(identity)


def capture_batch(*, plan, events, output, claim_path, run_id, binding_hash,
                  get, limits=None, clock=time.time, monotonic=time.monotonic,
                  sleep=time.sleep, stop=lambda: False, assert_start_allowed):
    """The same tested loop serves fixtures and the explicitly guarded CLI.

    Transport is injected, never implicitly constructed. No processes or request
    threads are spawned here. A failed/partial namespace can never be reused.
    """
    limits = dict(LIMITS if limits is None else limits)
    if (set(limits) != set(LIMITS) or any(type(v) is not int or v < 0 for v in limits.values())
            or any(limits[k] > LIMITS[k] for k in limits)
            or limits['max_runtime_sec'] == 0 or limits['max_output_bytes'] < 12000):
        raise ValueError('invalid bounded limits')
    validate_events(events, plan, limits)
    output, claim_path = Path(output), Path(claim_path)
    if output.exists() or stop():
        raise ValueError('namespace already used or stop requested')
    assert_start_allowed()
    cap = plan['capture']
    interval = cap['snapshot_interval_sec']
    begun, began_at = monotonic(), clock()
    claim = claim_global_market_writer(claim_path, run_id=run_id, owner_pid=os.getpid(),
        writer_pid=os.getpid(), terminal_pid=os.getppid(), owner_kind='premarket_depth_serial',
        plan_hash=binding_hash, output_namespace=output)
    result = {'status': 'STOPPED_INCOMPLETE', 'stop_reason': None, 'run_id': run_id,
              'requests': 0, 'errors': 0, 'response_bytes': 0, 'missed_slots': 0,
              'sample_certified': False, 'retry_authorized': False, 'events': []}
    used_bytes, jobs, paths, per_event = 0, [], [], []
    created = False
    reserve = 10000  # Room for terminal footers and result even when a data row hits the cap.

    def write_row(path, row):
        nonlocal used_bytes
        data = encoded(row)
        if used_bytes + len(data) > limits['max_output_bytes'] - reserve:
            raise RuntimeError('OUTPUT_BUDGET')
        with path.open('ab') as stream:
            stream.write(data)
        used_bytes += len(data)

    def owned():
        current = decode(claim_path.read_text(encoding='utf-8'))
        if any(current.get(k) != claim.get(k) for k in ('run_id', 'owner_pid', 'ownership_token', 'plan_hash', 'status')):
            raise RuntimeError('WRITER_OWNERSHIP_LOST')

    def budget_reason():
        if stop():
            return 'USER_STOP'
        if monotonic() - begun >= limits['max_runtime_sec'] or clock() >= began_at + limits['max_runtime_sec']:
            return 'RUNTIME_LIMIT'
        if result['requests'] >= limits['max_http_attempts']:
            return 'HTTP_BUDGET'
        if result['response_bytes'] >= limits['max_response_total_bytes']:
            return 'RESPONSE_BUDGET'
        if shutil.disk_usage(output).free < limits['min_free_bytes']:
            return 'DISK_RESERVE'
        owned()
        return None

    try:
        assert_start_allowed()
        output.mkdir(parents=True, exist_ok=False)
        created = True
        for i, e in enumerate(sorted(events, key=lambda e: (e['t0_ts'], e['venue'], e['base']))):
            key = canonical(e, '_unused')[:24]
            path = output / f'{e["venue"]}-{key}.jsonl'
            path.touch(exist_ok=False)
            paths.append(path)
            per_event.append({'requests': 0, 'errors': 0, 'missed_slots': 0, 'first_spot': None})
            result['events'].append({'base': e['base'], 'venue': e['venue'], 'path': path.name,
                                     'owner_pid': os.getpid()})
            write_row(path, {'record': 'header', 'schema': 'trading_mvp_premarket_forward_depth_capture_v1',
                'plan_id': plan['plan_id'], 'plan_hash': plan['plan_hash'], 'event': e,
                'hypothesis': plan['hypothesis'], 'runtime_manifest_hash': binding_hash,
                'size_units': 'VENUE_NATIVE_CONTRACTS_OR_BASE_NOT_CONVERTED',
                'started_at_ts': clock(), 'owner_pid': os.getpid()})
            for leg in ('perp', 'spot'):
                first = max(e['capture_from_ts'], e['t0_ts']) if leg == 'spot' else e['capture_from_ts']
                slot = e['t0_ts'] + math.ceil((first - e['t0_ts']) / interval) * interval
                while slot < e['capture_to_ts']:
                    jobs.append((slot, i, leg, e))
                    slot += interval
        # Earliest slot, then leg, then event: equal treatment across simultaneous events.
        jobs.sort(key=lambda j: (j[0], j[2], j[1]))
        for due, i, leg, e in jobs:
            reason = budget_reason()
            if reason:
                raise RuntimeError(reason)
            if clock() < due:
                while clock() < due:
                    reason = budget_reason()
                    if reason:
                        raise RuntimeError(reason)
                    sleep(min(1, due - clock()))
            reason = budget_reason()
            if reason:
                raise RuntimeError(reason)
            if clock() >= min(due + interval, e['capture_to_ts']):
                result['missed_slots'] += 1
                per_event[i]['missed_slots'] += 1
                write_row(paths[i], {'record': 'missed_slot', 'leg': leg, 'slot_ts': due,
                                    'reason': 'SERIAL_CAPACITY_OR_LATE_START', 'ts': clock()})
                continue
            if per_event[i]['requests'] >= cap['max_snapshots_per_event']:
                raise RuntimeError('EVENT_HTTP_BUDGET')
            result['requests'] += 1
            per_event[i]['requests'] += 1
            started = clock()
            timeout = min(cap['request_timeout_sec'], due + interval - started,
                          limits['max_runtime_sec'] - (monotonic() - begun),
                          began_at + limits['max_runtime_sec'] - started)
            available = min(cap['max_response_bytes'], limits['max_response_total_bytes'] - result['response_bytes'])
            try:
                row = get(e, leg, timeout_sec=timeout, max_bytes=available)
                consumed = row['response_bytes']
                if type(consumed) is not int or not 0 <= consumed <= available:
                    raise RuntimeError('TRANSPORT_BOUND_VIOLATION')
                result['response_bytes'] += consumed
                if clock() >= due + interval or monotonic() - begun >= limits['max_runtime_sec']:
                    raise TimeoutError('response arrived after slot/runtime deadline')
                if row.get('usable') is True and leg == 'spot' and per_event[i]['first_spot'] is None:
                    per_event[i]['first_spot'] = (clock() - e['t0_ts']) / 60
                row = {**row, 'record': 'book'}
            except (OSError, ValueError, urllib.error.URLError) as exc:
                consumed = getattr(exc, 'response_bytes', 0)
                if not 0 <= consumed <= available:
                    raise RuntimeError('TRANSPORT_BOUND_VIOLATION')
                result['response_bytes'] += consumed
                result['errors'] += 1
                per_event[i]['errors'] += 1
                row = {'record': 'error', 'reason': type(exc).__name__, 'response_bytes': consumed}
            row.update({'leg': leg, 'symbol': e[leg + '_symbol'], 'slot_ts': due,
                        'ts': clock(), 'request_started_ts': started,
                        'rel_min': round((clock() - e['t0_ts']) / 60, 3)})
            owned()
            write_row(paths[i], row)
            print(f'{run_id}: requests={result["requests"]} errors={result["errors"]} '
                  f'bytes={result["response_bytes"]} event={e["base"]}/{leg}', flush=True)
            sleep(min(cap['min_interval_between_requests_sec'],
                      max(0, limits['max_runtime_sec'] - (monotonic() - begun))))
        end = max(e['capture_to_ts'] for e in events)
        while clock() < end:
            reason = budget_reason()
            if reason:
                raise RuntimeError(reason)
            sleep(min(1, end - clock()))
        result['status'] = 'COMPLETED' if not result['errors'] and not result['missed_slots'] else 'STOPPED_INCOMPLETE'
        result['stop_reason'] = 'WINDOWS_RECORDED' if result['status'] == 'COMPLETED' else 'ERRORS_OR_MISSED_SLOTS'
    except (Exception, KeyboardInterrupt) as exc:
        if not created:
            raise
        result['stop_reason'] = 'USER_STOP' if isinstance(exc, KeyboardInterrupt) else str(exc)[:240]
    finally:
        # If ownership is lost, leave the foreign claim untouched and fail closed.
        owned()
        if created:
            for path, stats in zip(paths, per_event):
                first = stats['first_spot']
                data = encoded({'record': 'footer', 'status': result['status'], 'stop_reason': result['stop_reason'],
                    'snapshots': stats['requests'], 'errors': stats['errors'], 'missed_slots': stats['missed_slots'],
                    'first_spot_book_rel_min': first, 'anchor_tolerance_min': plan['anchor_check']['max_first_spot_book_delay_min'],
                    'anchor_suspect': first is None or first > plan['anchor_check']['max_first_spot_book_delay_min'],
                    'finished_at_ts': clock(), 'sample_certified': False})
                with path.open('ab') as stream:
                    stream.write(data)
                used_bytes += len(data)
            result['runtime_manifest_hash'] = binding_hash
            result['output_data_bytes'] = used_bytes
            data = encoded(result)
            if used_bytes + len(data) > limits['max_output_bytes']:
                raise RuntimeError('TERMINAL_OUTPUT_BUDGET')
            with (output / 'result.json').open('xb') as stream:
                stream.write(data)
        release_global_market_writer(claim_path, run_id=run_id, owner_pid=os.getpid(),
            ownership_token=claim['ownership_token'], expected_plan_hash=binding_hash,
            final_status=result['status'])
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, 'redirect forbidden', headers, fp)


class TransportError(OSError):
    def __init__(self, reason, consumed):
        super().__init__(reason)
        self.response_bytes = consumed


def public_transport(plan):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(event, leg, *, timeout_sec, max_bytes):
        venue = event['venue']
        suffix = 'spot' if leg == 'spot' else 'swap' if venue == 'okx' else 'perp'
        url = plan['depth_books'][venue + '_' + suffix]
        host = 'www.okx.com' if venue == 'okx' else 'api.gateio.ws'
        if urllib.parse.urlsplit(url).scheme != 'https' or urllib.parse.urlsplit(url).netloc != host:
            raise ValueError('public endpoint mismatch')
        query = _book_request(venue, leg, event[leg + '_symbol'], plan['capture']['depth_levels_requested'])
        request = urllib.request.Request(url + '?' + urllib.parse.urlencode(query),
            headers={'User-Agent': 'ZolotyayLopata-depth-coordinator/1.0', 'Accept-Encoding': 'identity'})
        begun, raw = time.monotonic(), bytearray()
        try:
            with opener.open(request, timeout=timeout_sec) as response:
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('unexpected compression')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) > max_bytes:
                    raise ValueError('declared response exceeds remaining budget')
                while len(raw) < max_bytes:
                    if time.monotonic() - begun >= timeout_sec:
                        raise TimeoutError('request deadline')
                    chunk = response.read1(min(65536, max_bytes - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                else:
                    if length is None or int(length) != len(raw):
                        raise ValueError('response incomplete at byte boundary')
            if time.monotonic() - begun >= timeout_sec:
                raise TimeoutError('request deadline')
            payload = json.loads(raw)
            bids, asks = _levels(payload, venue, leg)
            row = summarise(bids, asks, plan['capture']['distance_bands_pct'], plan['capture']['levels_retained_per_side'])
            return {**row, 'response_sha256': hashlib.sha256(raw).hexdigest(),
                    'response_bytes': len(raw), 'wire_bytes': len(raw)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise TransportError(type(exc).__name__, len(raw)) from exc
    return get


def freeze(root):
    plan = decode((root / BASE_PLAN).read_text(encoding='utf-8-sig'))
    validate_plan(plan, repo_root=root)
    value = {'schema': SCHEMA, 'mode': 'OFFLINE_IMPLEMENTED_NOT_ENABLED',
             'collection_enabled': False, 'schedules_resume_authorized': False,
             'base_plan': ref(root / BASE_PLAN), 'base_plan_hash': plan['plan_hash'],
             'limits': dict(LIMITS), 'batch': None, 'code': [ref(root / p) for p in CODE],
             'legacy_installer': ref(root / 'tools/install_premarket_forward_depth_scan_task.ps1'),
             'scope_changed': False, 'minimum_events_before_any_claim': 12,
             'no_retry': True, 'no_proxies': True, 'no_redirects': True,
             'capture_namespace': OUTPUT_ROOT, 'raw_response_saved': False}
    value['manifest_hash'] = canonical(value, 'manifest_hash')
    return value


def load_manifest(root, path):
    value = decode(path.read_text(encoding='utf-8-sig'))
    if (value.get('schema') != SCHEMA or value.get('manifest_hash') != canonical(value, 'manifest_hash')
            or value.get('limits') != LIMITS or value.get('scope_changed') is not False
            or value.get('capture_namespace') != OUTPUT_ROOT
            or {b['path'] for b in value['code']} != {str((root / p).resolve()) for p in CODE}):
        raise ValueError('runtime binding mismatch')
    for binding in [value['base_plan'], value['legacy_installer'], *value['code']]:
        verify_ref(binding, root)
    plan = decode(Path(value['base_plan']['path']).read_text(encoding='utf-8-sig'))
    validate_plan(plan, repo_root=root)
    if plan['plan_hash'] != value['base_plan_hash']:
        raise ValueError('base plan mismatch')
    return value, plan


def execution_preflight(root, path):
    runtime, plan = load_manifest(root, path)
    if runtime.get('collection_enabled') is not True:
        raise ValueError('COLLECTION_DISABLED_OFFLINE_ONLY')
    state = decode((root / 'docs/agent-log/trading-mvp-autopilot-state.json').read_text(encoding='utf-8-sig'))
    require_execution_guard(state, runtime['manifest_hash'])
    if (root / CLAIM).exists():
        raise ValueError('GLOBAL_WRITER_EXISTS')
    batch = decode(verify_ref(runtime['batch'], root).read_text(encoding='utf-8-sig'))
    if (batch.get('batch_hash') != canonical(batch, 'batch_hash') or batch.get('plan_hash') != plan['plan_hash']
            or not re.fullmatch(r'premarket_depth_[A-Za-z0-9_-]{1,100}', batch.get('run_id', ''))):
        raise ValueError('batch binding mismatch')
    validate_events(batch['events'], plan, runtime['limits'])
    start = min(e['capture_from_ts'] for e in batch['events'])
    end = max(e['capture_to_ts'] for e in batch['events'])
    if not start - 60 <= time.time() < start + plan['capture']['snapshot_interval_sec'] or end - min(start, time.time()) > LIMITS['max_runtime_sec']:
        raise ValueError('batch not due or cannot finish within runtime')
    output = root / OUTPUT_ROOT / batch['run_id']
    if output.exists():
        raise ValueError('batch namespace already used; no retry')
    return runtime, plan, batch, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--launch-token', default='')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--preflight', action='store_true')
    actions.add_argument('--run', action='store_true')
    actions.add_argument('--freeze-only', action='store_true')
    args = parser.parse_args()
    root = args.repo_root.resolve()
    path = args.manifest or root / MANIFEST
    try:
        if args.freeze_only:
            data = (json.dumps(freeze(root), indent=2, allow_nan=False) + '\n').encode('utf-8')
            with path.open('xb') as stream:
                stream.write(data)
            print('OFFLINE_RUNTIME_FROZEN_NO_COLLECTION')
            return 0
        runtime, plan, batch, output = execution_preflight(root, path)
        if args.preflight:
            print(json.dumps({'status': 'READY', 'run_id': batch['run_id'], 'output': str(output),
                              'max_runtime_sec': LIMITS['max_runtime_sec'], 'runtime_manifest_hash': runtime['manifest_hash']}))
            return 0
        if os.name != 'nt' or not sys.stdout.isatty():
            raise ValueError('visible Windows console required')
        import ctypes
        ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
        ctypes.windll.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        if not ctypes.windll.user32.IsWindowVisible(ctypes.windll.kernel32.GetConsoleWindow()):
            raise ValueError('visible console ownership not verified')
        if not re.fullmatch('[0-9a-f]{32}', args.launch_token):
            raise ValueError('visible launcher handshake required')
        control = root / 'docs/agent-log/run-gates' / (batch['run_id'] + '.depth-owner.json')
        deadline = time.monotonic() + 10
        while not control.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        owner = decode(control.read_text(encoding='utf-8-sig'))
        if (owner.get('token') != args.launch_token or owner.get('worker_pid') != os.getpid()
                or owner.get('owner_pid') != os.getppid() or owner.get('job_assigned') is not True
                or owner.get('runtime_manifest_hash') != runtime['manifest_hash']):
            raise ValueError('visible launcher handshake mismatch')
        # Recheck immutable inputs after waiting for the owning Job Object.
        runtime, plan, batch, output = execution_preflight(root, path)
        def guard():
            value, _ = load_manifest(root, path)
            require_execution_guard(decode((root / 'docs/agent-log/trading-mvp-autopilot-state.json').read_text(encoding='utf-8-sig')), value['manifest_hash'])
        result = capture_batch(plan=plan, events=batch['events'], output=output, claim_path=root / CLAIM,
            run_id=batch['run_id'], binding_hash=runtime['manifest_hash'], get=public_transport(plan),
            stop=lambda: (output / 'STOP').exists() or control.with_suffix('.stop').exists(),
            assert_start_allowed=guard)
        print(json.dumps(result))
        return 0 if result['status'] == 'COMPLETED' else 2
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
