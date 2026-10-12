"""One visible discovery/capture cycle through the existing campaign budget.

The shipped manifest is disabled. No schedule, campaign or ledger is created.
Offline fixtures exercise the same transport and dispatch boundary as the CLI.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import premarket_depth_coordinator as c
import premarket_depth_dispatch as d
from research_checkpoint import verify_ref
from premarket_forward_depth_quality import _pairs, _constant

MODULE = 'trading_mvp/src/premarket_depth_gateway.py'
LAUNCHER = 'tools/start_premarket_depth_gateway_visible.ps1'
MANIFEST = 'docs/plans/premarket-depth-gateway-runtime-20261012-v1.json'
OUTPUT_ROOT = 'docs/analysis/premarket-depth-gateway-runs'
MAX_RUNTIME = d.SCAN_RUNTIME + c.LIMITS['max_runtime_sec']


def metadata_transport(plan, *, open_request=None, monotonic=time.monotonic):
    if open_request is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), c.NoRedirect())
        open_request = opener.open
    allowed = [(s['endpoint'], s['fixed_query']) for s in plan['schedule_sources'].values()]

    def get(url, params, *, allowed_host, timeout_sec, max_bytes):
        parsed = urllib.parse.urlsplit(url)
        if (not any(url == u and params == q for u, q in allowed)
                or parsed.scheme != 'https' or parsed.netloc != allowed_host
                or allowed_host not in ('www.okx.com', 'api.gateio.ws')
                or parsed.query or parsed.fragment or type(params) is not dict
                or type(max_bytes) is not int or not 0 < max_bytes <= plan['capture']['max_response_bytes']
                or type(timeout_sec) not in (int, float) or not math.isfinite(timeout_sec)
                or not 0 < timeout_sec <= plan['capture']['request_timeout_sec']):
            raise ValueError('endpoint or request limits outside frozen scope')
        request = urllib.request.Request(url + ('?' + urllib.parse.urlencode(params) if params else ''),
            headers={'User-Agent': 'ZolotyayLopata-depth-gateway/1.0', 'Accept-Encoding': 'identity'})
        raw = bytearray()
        began = monotonic()
        try:
            with open_request(request, timeout=timeout_sec) as response:
                if response.status != 200:
                    raise ValueError('non-success response; no body consumption')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('unexpected encoding')
                length = response.headers.get('Content-Length')
                declared = None if length is None else int(length)
                if declared is not None and not 0 <= declared <= max_bytes:
                    raise ValueError('declared response outside budget')
                while len(raw) < max_bytes:
                    if monotonic() - began >= timeout_sec:
                        raise TimeoutError('request deadline')
                    chunk = response.read1(min(65536, max_bytes - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if ((declared is not None and declared != len(raw))
                        or (declared is None and len(raw) == max_bytes)):
                    raise ValueError('incomplete response at byte boundary')
            if monotonic() - began >= timeout_sec:
                raise TimeoutError('request deadline')
            payload = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
            if not isinstance(payload, (dict, list)):
                raise ValueError('catalogue must be an object or array')
            return payload, dict(response_bytes=len(raw),
                response_sha256=hashlib.sha256(raw).hexdigest())
        except urllib.error.HTTPError as exc:
            exc.close()
            raise c.TransportError('HTTPError', len(raw)) from exc
        except (OSError, ValueError, TypeError) as exc:
            raise c.TransportError(type(exc).__name__, len(raw)) from exc
    return get


def require_guard(state, runtime_hash, campaign_hash, *, now=None):
    now = time.time() if now is None else now
    usage = state.get('usage', {})
    stamp = datetime.fromisoformat(state['observed_at_utc'].replace('Z', '+00:00'))
    remaining = usage.get('remaining_percent')
    age = usage.get('event_age_sec')
    if (stamp.tzinfo is None or not 0 <= now - stamp.timestamp() <= 300
            or state.get('decision') != 'RUN_PREMARKET_DEPTH_GATEWAY'
            or state.get('stop_new_actions') is not False
            or state.get('runtime_manifest_hash') != runtime_hash
            or state.get('campaign_hash') != campaign_hash
            or state.get('gate', {}).get('status') != 'READY_FOR_POSTPROCESS'
            or usage.get('status') != 'AVAILABLE' or usage.get('decision') != 'CONTINUE'
            or type(remaining) not in (int, float) or not math.isfinite(remaining)
            or not 15 < remaining <= 100 or type(age) not in (int, float)
            or not math.isfinite(age) or not 0 <= age <= 300):
        raise ValueError('fresh exact gateway controller/quota binding required')


def require_owner(owner, *, token, pid, parent, runtime_hash, run_id, output):
    if (not re.fullmatch('[0-9a-f]{32}', token) or owner.get('token') != token
            or owner.get('worker_pid') != pid or owner.get('owner_pid') != parent
            or owner.get('job_assigned') is not True or owner.get('run_id') != run_id
            or owner.get('runtime_manifest_hash') != runtime_hash
            or Path(owner.get('output', '')).resolve() != Path(output).resolve()):
        raise ValueError('visible owner binding mismatch')


def run_cycle(ledger, plan, output, claim, metadata_get, book_get, guard, *,
              clock=time.time, monotonic=time.monotonic, sleep=time.sleep, stop=lambda: False,
              hard_deadline=None):
    begun = monotonic()
    def stopped():
        return stop() or monotonic() - begun >= MAX_RUNTIME
    def before_start():
        if stopped():
            raise ValueError('STOP_OR_DEADLINE')
        guard()
    def metadata(*args, **kwargs):
        if stopped():
            raise ValueError('STOP_OR_DEADLINE')
        return metadata_get(*args, **kwargs)
    before_start()
    report = d.scan_once(ledger, plan, claim, metadata, before_start, clock=clock, sleep=sleep)
    before_start()
    if hard_deadline is not None:
        d.finite_ts(hard_deadline)
        selected = d.select_batch(report, plan, clock(), ledger.snapshot()['consumed'])
        if selected['status'] == 'DUE' and max(e['capture_to_ts'] for e in selected['events']) >= hard_deadline:
            return dict(status='COMPLETE_NO_CAPTURE', scan_report_hash=report['report_hash'],
                        capture={'status': 'HARD_DEADLINE_CONFLICT'}, sample_certified=False,
                        retry_authorized=False)
    capture = d.capture_due(ledger, plan, report, Path(output)/'captures', claim, book_get,
                            before_start, clock=clock, monotonic=monotonic, sleep=sleep, stop=stopped)
    # A refusal to select a batch is not a completed capture or a market verdict.
    result = 'COMPLETED' if capture['status'] == 'COMPLETED' else (
        'COMPLETE_NO_CAPTURE' if capture['status'] != 'STOPPED_INCOMPLETE' else 'STOPPED_INCOMPLETE')
    return dict(status=result, scan_report_hash=report['report_hash'] if 'report_hash' in report else None,
                capture=capture, sample_certified=False, retry_authorized=False)


def freeze(root):
    parent = d.preflight(root, root/d.MANIFEST)
    value = dict(schema='premarket_depth_gateway_runtime_v1',
        base_runtime=c.ref(root/d.MANIFEST), base_runtime_hash=parent['manifest_hash'],
        code=[c.ref(root/p) for p in (MODULE, LAUNCHER)], scope_changed=False,
        collection_enabled=False, schedules_resume_authorized=False, campaign=None,
        max_runtime_sec=MAX_RUNTIME, one_shot=True, output_root=OUTPUT_ROOT,
        summary_output_reserved_bytes=d.SCAN_OUTPUT_BYTES,
        direct_coordinator_bypass_allowed=False)
    value['manifest_hash'] = c.canonical(value, 'manifest_hash')
    return value


def load_runtime(root, path):
    value = c.decode(path.read_text(encoding='utf-8-sig'))
    expected = freeze(root)
    # A future campaign is a separate exact binding, never a CLI enable switch.
    expected.update(collection_enabled=value.get('collection_enabled'), campaign=value.get('campaign'))
    expected['manifest_hash'] = c.canonical(expected, 'manifest_hash')
    if value != expected or type(value['collection_enabled']) is not bool:
        raise ValueError('gateway runtime binding mismatch')
    return value


def execution_context(root, path):
    runtime = load_runtime(root, path)
    if not runtime['collection_enabled'] or not runtime['campaign']:
        raise ValueError('COLLECTION_DISABLED_NO_CAMPAIGN')
    campaign = c.decode(verify_ref(runtime['campaign'], root).read_text(encoding='utf-8-sig'))
    _, plan = c.load_manifest(root, root/c.MANIFEST)
    run_id = campaign.get('run_id', '')
    if (campaign.get('campaign_hash') != c.canonical(campaign, 'campaign_hash')
            or campaign.get('plan_hash') != plan['plan_hash']
            or campaign.get('dispatch_hash') != runtime['base_runtime_hash']
            or not re.fullmatch('premarket_gateway_[A-Za-z0-9_-]{1,80}', run_id)
            or not re.fullmatch('[A-Za-z0-9_-]{1,64}', campaign.get('campaign_id', ''))):
        raise ValueError('campaign binding mismatch')
    current = c.decode((root/'docs/agent-log/trading-mvp-autopilot-state.json').read_text(encoding='utf-8-sig'))
    require_guard(current, runtime['manifest_hash'], campaign['campaign_hash'])
    if (root/c.CLAIM).exists():
        raise ValueError('GLOBAL_WRITER_EXISTS')
    output = root/OUTPUT_ROOT/run_id
    if output.exists():
        raise ValueError('run namespace already used; no retry')
    ledger_path = root/'docs/analysis/premarket-depth-gateway-campaigns'/campaign['campaign_id']/'ledger.sqlite'
    ledger = d.Ledger(ledger_path, plan['plan_hash'], runtime['manifest_hash'])
    limits = campaign.get('limits')
    if (not isinstance(limits, dict) or set(limits) != set(d.BUDGET)
            or any(type(v) is not int or not 0 < v <= d.BUDGET[k] for k, v in limits.items())
            or not d.LEDGER_BYTES <= limits['output_bytes'] <= d.BUDGET['output_bytes']-d.SCAN_OUTPUT_BYTES
            or ledger.config['limits'] != limits):
        raise ValueError('campaign budget binding mismatch or summary reserve absent')
    if ledger.config['campaign_id'] != campaign['campaign_id'] or ledger.snapshot()['status'] != 'ACTIVE':
        raise ValueError('campaign not active or review required')
    now = time.time()
    d.finite_ts(campaign['started_ts']); d.finite_ts(campaign['hard_deadline_ts'])
    if (campaign['started_ts'] != ledger.config['started_ts']
            or not campaign['started_ts'] <= now < campaign['hard_deadline_ts']
            or campaign['hard_deadline_ts'] > campaign['started_ts'] + d.REVIEW_DAY*86400):
        raise ValueError('campaign window blocked')
    return runtime, plan, campaign, ledger, output


def preflight(root, path):
    try:
        runtime, plan, campaign, ledger, output = execution_context(root, path)
    except ValueError as exc:
        if str(exc) != 'COLLECTION_DISABLED_NO_CAMPAIGN':
            raise
        return dict(status='BLOCKED', reason=str(exc), network_requests=0,
                    writer_claim_created=False, output_created=False)
    return dict(status='READY', run_id=campaign['run_id'], output=str(output),
                max_runtime_sec=min(MAX_RUNTIME, int(campaign['hard_deadline_ts']-time.time())),
                runtime_manifest_hash=runtime['manifest_hash'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--launch-token', default='')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--preflight', action='store_true')
    actions.add_argument('--freeze-only', action='store_true')
    actions.add_argument('--run', action='store_true')
    args = parser.parse_args(); root = args.repo_root.resolve(); path = args.manifest or root/MANIFEST
    started = False; output = None
    try:
        if args.freeze_only:
            with path.open('xb') as stream:
                stream.write(c.encoded(freeze(root)))
            print('OFFLINE_GATEWAY_FROZEN'); return 0
        check = preflight(root, path)
        if args.preflight or check['status'] != 'READY':
            print(json.dumps(check)); return 0 if check['status'] == 'READY' else 2
        if os.name != 'nt' or not sys.stdout.isatty():
            raise ValueError('visible Windows console required')
        import ctypes
        ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
        ctypes.windll.user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        if not ctypes.windll.user32.IsWindowVisible(ctypes.windll.kernel32.GetConsoleWindow()):
            raise ValueError('visible console required')
        control = root/'docs/agent-log/run-gates'/(check['run_id']+'.gateway-owner.json')
        until = time.monotonic()+10
        while not control.exists() and time.monotonic() < until:
            time.sleep(0.05)
        owner = c.decode(control.read_text(encoding='utf-8-sig'))
        require_owner(owner, token=args.launch_token, pid=os.getpid(), parent=os.getppid(),
                      runtime_hash=check['runtime_manifest_hash'], run_id=check['run_id'], output=check['output'])
        runtime, plan, campaign, ledger, output = execution_context(root, path)
        def guard():
            fresh = load_runtime(root, path)
            verify_ref(fresh['campaign'], root)
            current = c.decode((root/'docs/agent-log/trading-mvp-autopilot-state.json').read_text(encoding='utf-8-sig'))
            require_guard(current, runtime['manifest_hash'], campaign['campaign_hash'])
        def stop():
            return control.with_suffix('.stop').exists() or time.time() >= campaign['hard_deadline_ts']
        output.mkdir(parents=True, exist_ok=False); started = True
        print('One budgeted discovery cycle, then at most one due capture batch.', flush=True)
        result = run_cycle(ledger, plan, output, root/c.CLAIM, metadata_transport(plan),
                           c.public_transport(plan), guard, stop=stop,
                           hard_deadline=campaign['hard_deadline_ts'])
        result.update(run_id=campaign['run_id'], runtime_manifest_hash=runtime['manifest_hash'])
        if len(c.encoded(result)) > d.SCAN_OUTPUT_BYTES:
            raise ValueError('gateway summary output budget exceeded')
        with (output/'result.json').open('xb') as stream:
            stream.write(c.encoded(result))
        print(json.dumps(result)); return 2 if result['status'] == 'STOPPED_INCOMPLETE' else 0
    except Exception as exc:
        result = dict(status='STOPPED_INCOMPLETE' if started else 'BLOCKED',
                      reason=str(exc), retry_authorized=False)
        if started and not (output/'result.json').exists():
            with (output/'result.json').open('xb') as stream:
                stream.write(c.encoded(result))
        print(json.dumps(result)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
