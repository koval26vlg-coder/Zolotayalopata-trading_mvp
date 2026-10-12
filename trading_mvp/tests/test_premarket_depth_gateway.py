import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import premarket_depth_coordinator as c
import premarket_depth_dispatch as d
import premarket_depth_gateway as g

ROOT = Path(__file__).resolve().parents[2]
NOW = 1_800_000_000


class Response(io.BytesIO):
    def __init__(self, body=b'[]', headers=None, status=200):
        super().__init__(body)
        self.headers = {} if headers is None else headers
        self.status = status


def state():
    return dict(observed_at_utc=datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
        decision='RUN_PREMARKET_DEPTH_GATEWAY', stop_new_actions=False,
        runtime_manifest_hash='a'*64, campaign_hash='b'*64,
        gate={'status': 'READY_FOR_POSTPROCESS'},
        usage=dict(status='AVAILABLE', decision='CONTINUE', remaining_percent=99,
                   event_age_sec=0))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = json.loads((ROOT/c.BASE_PLAN).read_text())
        self.url = self.plan['schedule_sources']['gate_spot']['endpoint']
        self.calls = []
        self.network = patch.object(socket, 'socket', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def get(self, response, **overrides):
        def opener(request, timeout):
            self.calls.append(request.full_url)
            return response
        transport = g.metadata_transport(self.plan, open_request=opener, monotonic=lambda: NOW)
        return transport(self.url, {}, allowed_host='api.gateio.ws',
                         timeout_sec=10, max_bytes=overrides.get('max_bytes', 100))

    def test_streamed_metadata_receipt_without_raw_payload(self):
        body = b'[{"id":"AAA_USDT"}]'
        payload, receipt = self.get(Response(body))
        self.assertEqual(payload[0]['id'], 'AAA_USDT')
        self.assertEqual(receipt['response_bytes'], len(body))
        self.assertEqual(set(receipt), {'response_bytes', 'response_sha256'})
        self.assertEqual(len(self.calls), 1)

    def test_reject_url_outside_exact_catalog(self):
        transport = g.metadata_transport(self.plan, open_request=lambda *a, **k: self.fail('request'))
        for url in (self.url+'?extra=1', self.url+'/other', 'http://api.gateio.ws/api/v4/spot/currency_pairs'):
            with self.assertRaises(ValueError):
                transport(url, {}, allowed_host='api.gateio.ws', timeout_sec=10, max_bytes=100)

    def test_reject_unfrozen_query_and_host(self):
        transport = g.metadata_transport(self.plan, open_request=lambda *a, **k: self.fail('request'))
        for params, host in (({'key': 'secret'}, 'api.gateio.ws'), ({}, 'other.example')):
            with self.assertRaises(ValueError):
                transport(self.url, params, allowed_host=host, timeout_sec=10, max_bytes=100)

    def test_reject_boolean_and_nonfinite_limits(self):
        transport = g.metadata_transport(self.plan, open_request=lambda *a, **k: self.fail('request'))
        for timeout, cap in ((True, 10), (float('nan'), 10), (10, True), (10, 0), (10, 9*1024**2)):
            with self.assertRaises(ValueError):
                transport(self.url, {}, allowed_host='api.gateio.ws', timeout_sec=timeout, max_bytes=cap)

    def test_declared_oversize_reads_no_body(self):
        response = Response(b'[]', {'Content-Length': '101'})
        with patch.object(response, 'read1', side_effect=AssertionError('body read')):
            with self.assertRaises(c.TransportError) as caught:
                self.get(response)
        self.assertEqual(caught.exception.response_bytes, 0)

    def test_unknown_length_cap_never_reads_extra_byte(self):
        response = Response(b' '*101)
        sizes = []
        original = response.read1
        with patch.object(response, 'read1', side_effect=lambda n: (sizes.append(n), original(n))[1]):
            with self.assertRaises(c.TransportError) as caught:
                self.get(response)
        self.assertEqual(sum(sizes), 100)
        self.assertEqual(caught.exception.response_bytes, 100)

    def test_exact_declared_cap_is_valid(self):
        self.assertEqual(self.get(Response(b'[]', {'Content-Length': '2'}), max_bytes=2)[0], [])

    def test_truncated_declared_body_rejected(self):
        with self.assertRaises(c.TransportError):
            self.get(Response(b'[]', {'Content-Length': '10'}))

    def test_redirect_does_not_read_body(self):
        response = Response(b'private', status=302)
        with patch.object(response, 'read1', side_effect=AssertionError('redirect body')):
            with self.assertRaises(c.TransportError):
                self.get(response)
        self.assertEqual(len(self.calls), 1)

    def test_compression_and_bad_json_rejected(self):
        for response in (Response(b'[]', {'Content-Encoding': 'gzip'}), Response(b'not json'),
                Response(b'{"id":1,"id":2}'), Response(b'[NaN]'), Response(b'false')):
            with self.assertRaises(c.TransportError):
                self.get(response)

    def test_timeout_is_single_attempt(self):
        def opener(*args, **kwargs):
            self.calls.append('request')
            raise TimeoutError('sensitive response')
        transport = g.metadata_transport(self.plan, open_request=opener)
        with self.assertRaises(c.TransportError) as caught:
            transport(self.url, {}, allowed_host='api.gateio.ws', timeout_sec=10, max_bytes=100)
        self.assertEqual(self.calls, ['request'])
        self.assertNotIn('sensitive', str(caught.exception))

    def test_http_error_body_is_closed(self):
        import urllib.error
        response = Response(b'not read')
        def opener(*args, **kwargs):
            raise urllib.error.HTTPError(self.url, 500, 'fail', {}, response)
        with self.assertRaises(c.TransportError):
            g.metadata_transport(self.plan, open_request=opener)(self.url, {},
                allowed_host='api.gateio.ws', timeout_sec=10, max_bytes=100)
        self.assertTrue(response.closed)

    def test_default_transport_has_no_proxies_or_redirect_following(self):
        with patch.object(g.urllib.request, 'build_opener') as build:
            g.metadata_transport(self.plan)
        handlers = build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], c.NoRedirect)

    def test_guard_requires_exact_fresh_execution(self):
        g.require_guard(state(), 'a'*64, 'b'*64, now=NOW)
        for key, value in (('decision','RUN_PREMARKET_DEPTH_COORDINATOR'),
                ('runtime_manifest_hash','c'*64), ('campaign_hash','c'*64), ('stop_new_actions',True)):
            s = state(); s[key] = value
            with self.assertRaises(ValueError):
                g.require_guard(s, 'a'*64, 'b'*64, now=NOW)

    def test_guard_blocks_quota_stale_unavailable_and_other_writer(self):
        for remaining in (15, 0, True, float('nan')):
            s = state(); s['usage']['remaining_percent'] = remaining
            with self.assertRaises(ValueError):
                g.require_guard(s, 'a'*64, 'b'*64, now=NOW)
        for age in (-1, 301):
            s = state(); s['usage']['event_age_sec'] = age
            with self.assertRaises(ValueError):
                g.require_guard(s, 'a'*64, 'b'*64, now=NOW)
        s = state(); s['gate']['status'] = 'RUNNING'
        with self.assertRaises(ValueError):
            g.require_guard(s, 'a'*64, 'b'*64, now=NOW)
        with self.assertRaises(ValueError):
            g.require_guard(state(), 'a'*64, 'b'*64, now=NOW+301)

    def test_owner_requires_exact_pid_runtime_output_and_job(self):
        owner = dict(token='f'*32, worker_pid=12, owner_pid=10, job_assigned=True,
                     runtime_manifest_hash='a'*64, run_id='run', output=str(self.root))
        g.require_owner(owner, token='f'*32, pid=12, parent=10, runtime_hash='a'*64,
                        run_id='run', output=self.root)
        owner['job_assigned'] = False
        with self.assertRaises(ValueError):
            g.require_owner(owner, token='f'*32, pid=12, parent=10, runtime_hash='a'*64,
                            run_id='run', output=self.root)

    def test_cycle_uses_dispatch_and_never_direct_coordinator(self):
        calls = []
        with patch.object(d, 'scan_once', side_effect=lambda *a, **k: calls.append('scan') or {'status':'COMPLETE'}), \
             patch.object(d, 'capture_due', side_effect=lambda *a, **k: calls.append('capture') or {'status':'NOT_DUE'}), \
             patch.object(c, 'capture_batch', side_effect=AssertionError('budget bypass')):
            result = g.run_cycle(None, self.plan, self.root, self.root/'claim',
                                 None, None, lambda: None)
        self.assertEqual(calls, ['scan', 'capture'])
        self.assertEqual(result['status'], 'COMPLETE_NO_CAPTURE')

    def test_stop_before_cycle_does_not_consume_budget(self):
        with patch.object(d, 'scan_once', side_effect=AssertionError('scan')):
            with self.assertRaisesRegex(ValueError, 'STOP'):
                g.run_cycle(None, self.plan, self.root, self.root/'claim', None, None,
                            lambda: None, stop=lambda: True)

    def test_stop_between_scan_and_capture_does_not_start_capture(self):
        stopped = [False]
        def scan(*args, **kwargs):
            stopped[0] = True
            return {'status': 'COMPLETE'}
        with patch.object(d, 'scan_once', side_effect=scan), \
             patch.object(d, 'capture_due', side_effect=AssertionError('capture')):
            with self.assertRaisesRegex(ValueError, 'STOP'):
                g.run_cycle(None, self.plan, self.root, self.root/'claim', None, None,
                            lambda: None, stop=lambda: stopped[0])

    def test_scan_failure_has_no_capture_or_retry(self):
        with patch.object(d, 'scan_once', side_effect=TimeoutError()) as scan, \
             patch.object(d, 'capture_due', side_effect=AssertionError('capture')):
            with self.assertRaises(TimeoutError):
                g.run_cycle(None, self.plan, self.root, self.root/'claim', None, None, lambda: None)
        self.assertEqual(scan.call_count, 1)

    def test_frozen_gateway_remains_blocked_without_side_effects(self):
        path = self.root/'manifest.json'
        path.write_bytes(c.encoded(g.freeze(ROOT)))
        before = list(self.root.iterdir())
        result = g.preflight(ROOT, path)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'COLLECTION_DISABLED_NO_CAMPAIGN')
        self.assertEqual(before, list(self.root.iterdir()))

    def test_changed_manifest_rejected(self):
        value = g.freeze(ROOT); value['max_runtime_sec'] += 1
        value['manifest_hash'] = c.canonical(value, 'manifest_hash')
        path = self.root/'runtime.json'; path.write_bytes(c.encoded(value))
        with self.assertRaises(ValueError):
            g.preflight(ROOT, path)

    def test_cli_blocks_before_claim_or_output_even_with_run(self):
        import subprocess
        path = self.root/'manifest.json'; path.write_bytes(c.encoded(g.freeze(ROOT)))
        result = subprocess.run([sys.executable, str(ROOT/g.MODULE), '--manifest', str(path), '--run'],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['reason'], 'COLLECTION_DISABLED_NO_CAMPAIGN')
        self.assertEqual(list(self.root.iterdir()), [path])

    def context_fixture(self, *, limits=None):
        limits = dict(d.BUDGET) if limits is None else limits
        limits['output_bytes'] -= d.SCAN_OUTPUT_BYTES
        campaign = dict(campaign_id='fixture', run_id='premarket_gateway_fixture',
            plan_hash=self.plan['plan_hash'], dispatch_hash='d'*64,
            started_ts=NOW-10, hard_deadline_ts=NOW+100, limits=limits)
        campaign['campaign_hash'] = c.canonical(campaign, 'campaign_hash')
        source = self.root/'campaign.json'; source.write_bytes(c.encoded(campaign))
        runtime = dict(collection_enabled=True, campaign=c.ref(source),
                       manifest_hash='a'*64, base_runtime_hash='d'*64)
        path = self.root/'docs/analysis/premarket-depth-gateway-campaigns/fixture/ledger.sqlite'
        path.parent.mkdir(parents=True)
        ledger = d.Ledger.create(path, campaign_id='fixture', plan_hash=self.plan['plan_hash'],
            runtime_hash='a'*64, started_ts=NOW-10, limits=limits)
        current = state(); current['campaign_hash'] = campaign['campaign_hash']
        state_path = self.root/'docs/agent-log/trading-mvp-autopilot-state.json'
        state_path.parent.mkdir(parents=True)
        state_path.write_bytes(c.encoded(current))
        for target, name, value in ((g, 'load_runtime', runtime), (c, 'load_manifest', ({}, self.plan))):
            patched = patch.object(target, name, return_value=value)
            patched.start(); self.addCleanup(patched.stop)
        clock = patch.object(g.time, 'time', return_value=NOW)
        clock.start(); self.addCleanup(clock.stop)
        return runtime, campaign, ledger

    def test_enabled_preflight_needs_existing_bound_ledger_and_no_output(self):
        runtime, campaign, ledger = self.context_fixture()
        before = ledger.path.read_bytes()
        result = g.preflight(self.root, self.root/'runtime.json')
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['max_runtime_sec'], 100)
        self.assertEqual(before, ledger.path.read_bytes())
        self.assertFalse((self.root/g.OUTPUT_ROOT).exists())
        self.assertFalse((self.root/c.CLAIM).exists())

    def test_existing_claim_or_output_blocks_preflight(self):
        _, campaign, _ = self.context_fixture()
        claim = self.root/c.CLAIM; claim.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'GLOBAL_WRITER'):
            g.preflight(self.root, self.root/'runtime.json')
        claim.unlink()
        (self.root/g.OUTPUT_ROOT/campaign['run_id']).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'namespace already used'):
            g.preflight(self.root, self.root/'runtime.json')

    def test_missing_ledger_never_initializes_one(self):
        _, _, ledger = self.context_fixture()
        ledger.path.unlink()
        with self.assertRaisesRegex(ValueError, 'ledger absent'):
            g.preflight(self.root, self.root/'runtime.json')
        self.assertFalse(ledger.path.exists())

    def test_campaign_budget_tamper_is_rejected(self):
        runtime, campaign, _ = self.context_fixture()
        campaign['limits']['total_attempts'] -= 1
        campaign['campaign_hash'] = c.canonical(campaign, 'campaign_hash')
        source = self.root/'campaign.json'; source.write_bytes(c.encoded(campaign))
        runtime['campaign'] = c.ref(source)
        current = state(); current['campaign_hash'] = campaign['campaign_hash']
        (self.root/'docs/agent-log/trading-mvp-autopilot-state.json').write_bytes(c.encoded(current))
        with self.assertRaisesRegex(ValueError, 'budget binding'):
            g.preflight(self.root, self.root/'runtime.json')

    def test_campaign_expiry_blocks_before_output(self):
        self.context_fixture()
        with patch.object(g.time, 'time', return_value=NOW+101):
            with self.assertRaisesRegex(ValueError, 'campaign window'):
                g.preflight(self.root, self.root/'runtime.json')
        self.assertFalse((self.root/g.OUTPUT_ROOT).exists())

    def real_cycle(self, *, hard_deadline=None, fail_book=False):
        plan = copy.deepcopy(self.plan)
        plan['capture']['window_after_min'] = 2/3
        plan['capture']['min_interval_between_requests_sec'] = 0
        plan['notice_limit']['minimum_useful_pre_min'] = 0
        now = [NOW]
        ledger = d.Ledger.create(self.root/'ledger.sqlite', campaign_id='fixture',
            plan_hash=plan['plan_hash'], runtime_hash='a'*64, started_ts=NOW)
        claim = self.root/'claim.json'
        calls = []
        def opener(request, timeout):
            self.assertTrue(claim.exists())
            calls.append('metadata')
            if request.full_url.startswith('https://www.okx.com/'):
                payload = {'code': '0', 'data': []}
            elif '/spot/' in request.full_url:
                payload = [{'id':'AAA_USDT', 'buy_start':NOW+20, 'trade_status':'untradable', 'precision':4}]
            else:
                payload = [{'name':'AAA_USDT', 'launch_time':NOW-86400, 'quanto_multiplier':'1',
                            'order_price_round':'0.01'}]
            return Response(c.encoded(payload))
        def books(event, leg, **kwargs):
            self.assertTrue(claim.exists())
            self.assertIsNotNone(ledger.snapshot()['pending'])
            calls.append('book')
            if fail_book:
                raise TimeoutError('fixture')
            return dict(usable=True, response_bytes=10, wire_bytes=10)
        result = g.run_cycle(ledger, plan, self.root/'output', claim,
            g.metadata_transport(plan, open_request=opener, monotonic=lambda: now[0]), books,
            lambda: None, clock=lambda: now[0], monotonic=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0]+seconds), hard_deadline=hard_deadline)
        self.assertFalse(claim.exists())
        return result, ledger.snapshot(), calls

    def test_end_to_end_gateway_budget_claim_and_pilot_review(self):
        result, snapshot, calls = self.real_cycle()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(calls, ['metadata']*4 + ['book']*5)
        self.assertEqual(snapshot['metadata_attempts'], 4)
        self.assertEqual(snapshot['book_attempts'], 5)
        self.assertEqual(snapshot['status'], 'PILOT_REVIEW_REQUIRED')
        self.assertFalse(result['sample_certified'])

    def test_capture_cannot_start_past_campaign_deadline(self):
        result, snapshot, calls = self.real_cycle(hard_deadline=NOW+30)
        self.assertEqual(result['capture']['status'], 'HARD_DEADLINE_CONFLICT')
        self.assertEqual(calls, ['metadata']*4)
        self.assertEqual(snapshot['batches'], 0)
        self.assertFalse((self.root/'output').exists())

    def test_book_error_retains_reservation_and_has_no_retry(self):
        result, snapshot, calls = self.real_cycle(fail_book=True)
        self.assertEqual(result['status'], 'STOPPED_INCOMPLETE')
        self.assertEqual(calls, ['metadata']*4 + ['book'])
        self.assertEqual(snapshot['status'], 'STOPPED_INCOMPLETE')
        self.assertIsNotNone(snapshot['pending'])

    def test_launcher_routes_only_to_gateway_with_visible_owner(self):
        source = (ROOT/g.LAUNCHER).read_text(encoding='utf-8-sig')
        self.assertIn('premarket_depth_gateway.py', source)
        self.assertNotIn('premarket_depth_coordinator.py', source)
        for text in ('-WindowStyle Normal', '-NoExit', 'AssignProcessToJobObject',
                     '-Status -RunId', '-Stop -RunId', '.gateway-owner.json'):
            self.assertIn(text, source)


if __name__ == '__main__':
    unittest.main()
