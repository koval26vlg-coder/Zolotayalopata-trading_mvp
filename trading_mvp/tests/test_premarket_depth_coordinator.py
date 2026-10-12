import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import premarket_depth_coordinator as c
from global_market_writer_claim import claim_global_market_writer, release_global_market_writer

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def event(base='AAA'):
    return {'venue': 'gate', 'base': base, 'spot_symbol': base + '_USDT',
            'perp_symbol': base + '_USDT', 'perp_launched_ts': -3000,
            'perp_ct_val': 1, 't0_ts': 1020, 'capture_from_ts': 1000,
            'capture_to_ts': 1060, 'pre_window_available_min': 1 / 3}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'capture'
        self.claim = self.root / 'claim.json'
        self.clock = Clock()
        self.calls = []
        self.plan = json.loads((ROOT / c.BASE_PLAN).read_text(encoding='utf-8'))
        # Tiny synthetic window, not a rewritten real research plan.
        self.plan['notice_limit']['minimum_useful_pre_min'] = 0
        self.plan['capture']['window_after_min'] = 2 / 3
        self.limits = {**c.LIMITS, 'max_runtime_sec': 120, 'min_free_bytes': 0}
        self.stopped = False

    def get(self, event, leg, *, timeout_sec, max_bytes):
        self.assertTrue(self.claim.exists())
        self.calls.append((event['base'], leg, self.clock.time(), timeout_sec, max_bytes))
        return {'usable': True, 'response_sha256': 'a' * 64,
                'response_bytes': 100, 'wire_bytes': 100}

    def run_batch(self, **kw):
        args = dict(plan=self.plan, events=[event(), event('BBB')],
                    output=self.out, claim_path=self.claim, run_id='synthetic',
                    binding_hash='b' * 64, limits=self.limits, get=self.get,
                    clock=self.clock.time, monotonic=self.clock.time, sleep=self.clock.sleep,
                    stop=lambda: self.stopped, assert_start_allowed=lambda: None)
        args.update(kw)
        with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            return c.capture_batch(**args)

    def test_two_events_one_pid_serial_and_no_preopen_spot(self):
        result = self.run_batch()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['requests'], 10)
        self.assertEqual({p['owner_pid'] for p in result['events']}, {os.getpid()})
        self.assertEqual({x[0] for x in self.calls}, {'AAA', 'BBB'})
        self.assertTrue(all(t >= 1020 for _, leg, t, _, _ in self.calls if leg == 'spot'))
        self.assertTrue(all(b[2] - a[2] >= 1 for a, b in zip(self.calls, self.calls[1:])))
        self.assertFalse(self.claim.exists())
        self.assertFalse(result['sample_certified'])

    def test_existing_claim_no_output_or_network(self):
        owner = claim_global_market_writer(self.claim, run_id='other', owner_pid=os.getpid(),
                                          owner_kind='test', plan_hash='c' * 64, output_namespace=self.root / 'other')
        before = self.claim.read_bytes()
        with self.assertRaises(Exception):
            self.run_batch()
        self.assertEqual(self.claim.read_bytes(), before)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.calls)
        release_global_market_writer(self.claim, run_id='other', owner_pid=os.getpid(),
                                     ownership_token=owner['ownership_token'], final_status='TEST')

    def test_stop_preserves_partial_without_retry(self):
        def getter(*a, **kw):
            row = self.get(*a, **kw)
            self.stopped = True
            return row
        result = self.run_batch(get=getter)
        self.assertEqual(result['status'], 'STOPPED_INCOMPLETE')
        self.assertEqual(len(self.calls), 1)
        before = list(self.out.glob('*.jsonl'))[0].read_bytes()
        with self.assertRaises(ValueError):
            self.run_batch()
        self.assertEqual(list(self.out.glob('*.jsonl'))[0].read_bytes(), before)

    def test_request_error_not_retried_same_slot(self):
        def getter(*a, **kw):
            self.get(*a, **kw)
            raise TimeoutError('synthetic timeout')
        result = self.run_batch(get=getter)
        self.assertEqual(result['status'], 'STOPPED_INCOMPLETE')
        self.assertEqual(result['requests'], 10)
        self.assertEqual(result['errors'], 10)

    def test_runtime_deadline_stops_more_requests(self):
        self.limits['max_runtime_sec'] = 5
        result = self.run_batch()
        self.assertEqual(result['stop_reason'], 'RUNTIME_LIMIT')
        self.assertEqual(len(self.calls), 2)

    def test_slow_requests_disclose_missed_slots_no_catchup_burst(self):
        def getter(*a, **kw):
            row = self.get(*a, **kw)
            self.clock.sleep(21)
            return row
        result = self.run_batch(get=getter)
        self.assertEqual(result['status'], 'STOPPED_INCOMPLETE')
        self.assertGreater(result['missed_slots'], 0)
        self.assertLess(result['requests'], 10)

    def test_total_request_cap(self):
        self.limits['max_http_attempts'] = 3
        result = self.run_batch()
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(result['stop_reason'], 'HTTP_BUDGET')

    def test_byte_budget_passed_to_transport_and_never_exceeded(self):
        self.limits['max_response_total_bytes'] = 150
        def getter(*a, **kw):
            row = self.get(*a, **kw)
            row['response_bytes'] = row['wire_bytes'] = min(100, kw['max_bytes'])
            return row
        result = self.run_batch(get=getter)
        self.assertLessEqual(result['response_bytes'], 150)
        self.assertEqual([x[4] for x in self.calls], [150, 50])
        self.assertEqual(result['stop_reason'], 'RESPONSE_BUDGET')

    def test_oversize_response_is_incomplete(self):
        self.limits['max_response_total_bytes'] = 50
        result = self.run_batch()
        self.assertEqual(result['status'], 'STOPPED_INCOMPLETE')
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['stop_reason'], 'TRANSPORT_BOUND_VIOLATION')

    def test_output_cap_reserves_terminal_record(self):
        self.limits['max_output_bytes'] = 16000
        def getter(*a, **kw):
            return {**self.get(*a, **kw), 'padding': 'x' * 15000}
        result = self.run_batch(get=getter)
        self.assertEqual(result['stop_reason'], 'OUTPUT_BUDGET')
        self.assertLessEqual(sum(p.stat().st_size for p in self.out.iterdir() if p.is_file()), 16000)
        self.assertTrue((self.out / 'result.json').is_file())

    def test_duplicate_and_over_capacity_batch_reject_before_claim(self):
        for events in ([event(), event()], [event('A'), event('B'), event('C')]):
            with self.assertRaises(ValueError):
                self.run_batch(events=events)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.claim.exists())

    def test_guard_failure_before_claim_or_output(self):
        def reject():
            raise ValueError('guard blocked')
        with self.assertRaisesRegex(ValueError, 'guard blocked'):
            self.run_batch(assert_start_allowed=reject)
        self.assertFalse(self.claim.exists())
        self.assertFalse(self.out.exists())

    def test_stop_already_present_blocks_without_output(self):
        self.stopped = True
        with self.assertRaises(ValueError):
            self.run_batch()
        self.assertFalse(self.out.exists())

    def test_namespace_race_preserves_foreign_result(self):
        count = 0
        def race():
            nonlocal count
            count += 1
            if count == 2:
                self.out.mkdir()
                (self.out / 'result.json').write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):
            self.run_batch(assert_start_allowed=race)
        self.assertEqual((self.out / 'result.json').read_bytes(), b'foreign')
        self.assertFalse(self.claim.exists())
        self.assertFalse(self.calls)

    def test_completion_waits_until_window_end(self):
        self.run_batch()
        self.assertGreaterEqual(self.clock.time(), 1060)

    def test_stop_at_end_of_wait_never_sends_request(self):
        def sleep(seconds):
            self.clock.sleep(seconds)
            if self.clock.time() >= 1020:
                self.stopped = True
        result = self.run_batch(sleep=sleep)
        self.assertEqual(result['stop_reason'], 'USER_STOP')
        self.assertEqual(len(self.calls), 2)

    def test_ownership_loss_does_not_release_foreign_claim(self):
        def getter(*a, **kw):
            row = self.get(*a, **kw)
            value = json.loads(self.claim.read_text())
            value['ownership_token'] = 'f' * 32
            self.claim.write_text(json.dumps(value))
            return row
        with self.assertRaisesRegex(RuntimeError, 'OWNERSHIP_LOST'):
            self.run_batch(get=getter)
        self.assertTrue(self.claim.exists())
        self.assertFalse((self.out / 'result.json').exists())

    def test_current_guard_cannot_authorize_collection(self):
        state = {'decision': 'PREMARKET_DEPTH_QUALITY_COMPLETE_INSUFFICIENT_SAMPLE',
                 'stop_new_actions': True, 'usage': {'decision': 'CONTINUE', 'remaining_percent': 86},
                 'observed_at_utc': '2026-10-06T00:00:00Z'}
        with self.assertRaises(ValueError):
            c.require_execution_guard(state, 'a' * 64, now=1791244800)


class TransportAndLauncherTests(unittest.TestCase):
    def test_redirects_forbidden(self):
        with self.assertRaises(Exception):
            c.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://www.okx.com/')

    def test_legacy_installer_blocked_without_scheduler_or_network(self):
        script = (ROOT / 'tools/install_premarket_forward_depth_scan_task.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('LEGACY_HIDDEN_CAPTURE_RETIRED', script)
        self.assertLess(script.index('LEGACY_HIDDEN_CAPTURE_RETIRED'), script.index('if ($Uninstall)'))

    def test_launcher_is_visible_and_has_bounded_watchdog(self):
        script = (ROOT / 'tools/start_premarket_depth_coordinator_visible.ps1').read_text(encoding='utf-8-sig')
        for text in ('-WindowStyle Normal', '-NoExit', '-NoNewWindow', '$watch.Elapsed.TotalSeconds',
                     '[switch]$Status', '[switch]$Stop', '[switch]$PreflightOnly'):
            self.assertIn(text, script)
        self.assertNotIn('WindowStyle Hidden', script)

    def test_transport_declared_oversize_reads_no_body(self):
        response = io.BytesIO(b'x' * 50)
        response.headers = {'Content-Length': '50'}
        class Opener:
            def open(self, *a, **kw):
                return response
        with patch.object(c.urllib.request, 'build_opener', return_value=Opener()):
            get = c.public_transport(json.loads((ROOT / c.BASE_PLAN).read_text()))
            with self.assertRaises(c.TransportError) as error:
                get(event(), 'spot', timeout_sec=20, max_bytes=10)
        self.assertEqual(error.exception.response_bytes, 0)

    def test_transport_incomplete_read_reports_exact_bytes(self):
        response = io.BytesIO(b'x' * 50)
        response.headers = {}
        class Opener:
            def open(self, *a, **kw):
                return response
        with patch.object(c.urllib.request, 'build_opener', return_value=Opener()):
            get = c.public_transport(json.loads((ROOT / c.BASE_PLAN).read_text()))
            with self.assertRaises(c.TransportError) as error:
                get(event(), 'spot', timeout_sec=20, max_bytes=10)
        self.assertEqual(error.exception.response_bytes, 10)

    def test_transport_success_uses_frozen_summary_without_raw_body(self):
        raw = json.dumps({'bids': [['99', '2']], 'asks': [['101', '3']]}).encode()
        response = io.BytesIO(raw)
        response.headers = {'Content-Length': str(len(raw))}
        class Opener:
            def open(self, request, **kw):
                self.request = request
                return response
        opener = Opener()
        with patch.object(c.urllib.request, 'build_opener', return_value=opener) as build:
            get = c.public_transport(json.loads((ROOT / c.BASE_PLAN).read_text()))
            row = get(event(), 'spot', timeout_sec=20, max_bytes=500)
        self.assertTrue(row['usable'])
        self.assertEqual(row['response_bytes'], len(raw))
        self.assertNotIn('raw', row)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertTrue(opener.request.full_url.startswith('https://api.gateio.ws/api/v4/spot/order_book?'))

    def test_runtime_manifest_byte_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = c.freeze(ROOT)
            value['limits']['max_http_attempts'] += 1
            path = root / 'bad.json'
            path.write_bytes(c.encoded(value))
            with self.assertRaisesRegex(ValueError, 'binding mismatch'):
                c.load_manifest(ROOT, path)

    def test_failed_freeze_leaves_no_empty_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.json'
            args = ['coordinator', '--repo-root', tmp, '--manifest', str(path), '--freeze-only']
            with patch.object(sys, 'argv', args):
                self.assertEqual(c.main(), 2)
            self.assertFalse(path.exists())

    def test_freeze_does_not_share_mutable_budget(self):
        value = c.freeze(ROOT)
        self.assertIsNot(value['limits'], c.LIMITS)

    def test_offline_manifest_blocks_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.json'
            path.write_bytes(c.encoded(c.freeze(ROOT)))
            with self.assertRaisesRegex(ValueError, 'COLLECTION_DISABLED_OFFLINE_ONLY'):
                c.execution_preflight(ROOT, path)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher')
    def test_launcher_control_publication_is_atomic_and_no_clobber(self):
        script = ROOT / 'tools/start_premarket_depth_coordinator_visible.ps1'
        text = script.read_text(encoding='utf-8-sig')
        self.assertIn('[IO.File]::Move($temp, $path)', text)
        with tempfile.TemporaryDirectory() as tmp:
            command = r'''
$ErrorActionPreference = 'Stop'
$ast = [Management.Automation.Language.Parser]::ParseFile($env:TEST_LAUNCHER, [ref]$null, [ref]$null)
$fn = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Create-Json'}, $true)
. ([scriptblock]::Create($fn.Extent.Text))
$path = Join-Path $env:TEST_OUTPUT 'owner.json'
Create-Json $path @{token='original'}
try { Create-Json $path @{token='replacement'}; throw 'Collision not rejected' }
catch { if ($_.Exception.Message -eq 'Collision not rejected') { throw } }
if ((Get-Content $path -Raw | ConvertFrom-Json).token -ne 'original') { throw 'Owner overwritten' }
if (@(Get-ChildItem $env:TEST_OUTPUT).Count -ne 1) { throw 'Temporary file leaked' }
'''
            result = subprocess.run(['pwsh', '-NoProfile', '-Command', command],
                env={**os.environ, 'TEST_LAUNCHER': str(script), 'TEST_OUTPUT': tmp},
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fresh_authorized_guard_and_quota_boundaries(self):
        state = {'observed_at_utc': '1970-01-01T00:16:40+00:00', 'stop_new_actions': False,
                 'decision': 'RUN_PREMARKET_DEPTH_COORDINATOR', 'runtime_manifest_hash': 'a' * 64,
                 'usage': {'status': 'AVAILABLE', 'decision': 'CONTINUE', 'remaining_percent': 86},
                 'gate': {'status': 'READY_FOR_POSTPROCESS'}}
        c.require_execution_guard(state, 'a' * 64, now=1000)
        for now in (999, 1301):
            with self.assertRaises(ValueError):
                c.require_execution_guard(state, 'a' * 64, now=now)
        for percent in (15, 0, float('nan')):
            state['usage']['remaining_percent'] = percent
            with self.assertRaises(ValueError):
                c.require_execution_guard(state, 'a' * 64, now=1000)


if __name__ == '__main__':
    unittest.main()
