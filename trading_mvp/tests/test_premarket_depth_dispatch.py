import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import premarket_depth_dispatch as d
import premarket_depth_coordinator as c
from global_market_writer_claim import claim_global_market_writer

ROOT = Path(__file__).resolve().parents[2]
NOW = 1_800_000_000


def event(base='AAA', t0=NOW + 7200):
    return dict(venue='gate', base=base, spot_symbol=base+'_USDT', perp_symbol=base+'_USDT',
                t0_ts=t0, perp_launched_ts=t0-86400, perp_ct_val=1,
                capture_from_ts=t0-7200, capture_to_ts=t0+7200)


def report(plan, events, at=NOW):
    r = dict(plan_hash=plan['plan_hash'], observed_ts=at, status='COMPLETE',
             candidates=events, rejected=[], sources=[])
    r['report_hash'] = c.canonical(r, 'report_hash')
    return r


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = json.loads((ROOT/c.BASE_PLAN).read_text())
        self.ledger = d.Ledger.create(self.root/'ledger.sqlite', campaign_id='fixture',
            plan_hash=self.plan['plan_hash'], runtime_hash='a'*64, started_ts=NOW)
        self.network = patch.object(socket, 'socket', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_create_exclusive_and_binding(self):
        with self.assertRaises(FileExistsError):
            d.Ledger.create(self.ledger.path, campaign_id='fixture', plan_hash='b'*64,
                            runtime_hash='a'*64, started_ts=NOW)
        with self.assertRaises(ValueError):
            d.Ledger(self.ledger.path, 'wrong', 'a'*64)

    def test_request_reservation_survives_reopen_and_blocks_blind_retry(self):
        self.ledger.start_scan(NOW)
        cap = self.ledger.begin_request('metadata', 'scan:one', 100, NOW)
        self.assertEqual(cap, 100)
        reopened = d.Ledger(self.ledger.path, self.plan['plan_hash'], 'a'*64)
        self.assertEqual(reopened.snapshot()['metadata_bytes'], 100)
        with self.assertRaisesRegex(ValueError, 'PENDING'):
            reopened.begin_request('metadata', 'scan:two', 100, NOW)

    def test_settlement_releases_only_unused_bytes_and_no_retry(self):
        self.ledger.start_scan(NOW)
        self.ledger.begin_request('metadata', 'one', 100, NOW)
        self.ledger.settle_request('one', 30)
        self.assertEqual(self.ledger.snapshot()['metadata_bytes'], 30)
        with self.assertRaises(ValueError):
            self.ledger.begin_request('metadata', 'one', 100, NOW)
        with self.assertRaises(ValueError):
            self.ledger.settle_request('one', 0)

    def test_http_and_body_caps(self):
        limits = {**d.BUDGET, 'metadata_attempts': 1, 'metadata_bytes': 50}
        ledger = d.Ledger.create(self.root/'small.sqlite', campaign_id='tiny',
            plan_hash=self.plan['plan_hash'], runtime_hash='a'*64, started_ts=NOW, limits=limits)
        ledger.start_scan(NOW)
        self.assertEqual(ledger.begin_request('metadata', 'one', 100, NOW), 50)
        ledger.settle_request('one', 20)
        with self.assertRaisesRegex(ValueError, 'HTTP_BUDGET'):
            ledger.begin_request('metadata', 'two', 100, NOW)

    def test_bad_settlement_keeps_reservation(self):
        self.ledger.start_scan(NOW)
        self.ledger.begin_request('metadata', 'one', 100, NOW)
        with self.assertRaises(ValueError):
            self.ledger.settle_request('one', 101)
        self.assertEqual(self.ledger.snapshot()['pending']['capacity'], 100)

    def test_scan_spacing_review_and_deadline(self):
        self.ledger.start_scan(NOW)
        self.ledger.finish_scan(report(self.plan, []))
        for ts in (NOW-1, NOW+899, NOW+14*86400, NOW+42*86400):
            with self.assertRaises(ValueError):
                self.ledger.start_scan(ts)
        self.ledger.start_scan(NOW+900)

    def test_hash_tampering_is_rejected(self):
        import sqlite3
        with sqlite3.connect(self.ledger.path) as db:
            db.execute("UPDATE state SET body='{}'")
        db.close()
        with self.assertRaises(ValueError):
            self.ledger.snapshot()

    def test_two_events_selected_without_return_data(self):
        r = report(self.plan, [event('B'), event('A')])
        selected = d.select_batch(r, self.plan, NOW, {})
        self.assertEqual(selected['status'], 'DUE')
        self.assertEqual([e['base'] for e in selected['events']], ['A', 'B'])

    def test_three_simultaneous_events_are_not_silently_filtered(self):
        r = report(self.plan, [event('A'), event('B'), event('C')])
        self.assertEqual(d.select_batch(r, self.plan, NOW, {})['status'], 'CAPACITY_BLOCKED')

    def test_overlap_with_future_event_cannot_be_silently_skipped(self):
        r = report(self.plan, [event('A'), event('B', NOW+7300)])
        self.assertEqual(d.select_batch(r, self.plan, NOW, {})['status'], 'WINDOW_SPAN_BLOCKED')

    def test_not_due_stale_and_moved_schedule(self):
        self.assertEqual(d.select_batch(report(self.plan,[event(t0=NOW+8000)]), self.plan, NOW, {})['status'], 'NOT_DUE')
        with self.assertRaises(ValueError):
            d.select_batch(report(self.plan,[event()],NOW-901), self.plan,NOW,{})
        moved = d.select_batch(report(self.plan,[event()]),self.plan,NOW,{'gate:AAA':NOW+7000})
        self.assertEqual(moved['status'],'SCHEDULE_CHANGED_ALREADY_CAPTURED')

    def test_invalid_or_duplicate_candidates_block(self):
        for events in ([event(),event()], [{**event(),'perp_ct_val':float('nan')}]):
            with self.assertRaises(ValueError):
                d.select_batch(report(self.plan,events),self.plan,NOW,{})

    def getter(self, url, params, **kw):
        sources=self.plan['schedule_sources']
        if url==sources['okx_spot']['endpoint']:
            payload={'code':'0','data':[]}
        elif url==sources['gate_spot']['endpoint']:
            payload=[{'id':'AAA_USDT','buy_start':NOW+7200,'trade_status':'untradable','precision':4}]
        else:
            payload=[{'name':'AAA_USDT','launch_time':NOW-86400,'quanto_multiplier':'1','order_price_round':'0.01'}]
        raw=c.encoded(payload)
        return payload,dict(response_bytes=len(raw),response_sha256=hashlib.sha256(raw).hexdigest())

    def test_scan_uses_four_sources_one_claim_and_never_spawn(self):
        calls=[]
        def get(*args,**kw):
            self.assertTrue((self.root/'claim.json').exists())
            calls.append(args)
            return self.getter(*args,**kw)
        with patch('premarket_forward_depth_watch._spawn_capture', side_effect=AssertionError('old spawn')):
            r=d.scan_once(self.ledger,self.plan,self.root/'claim.json',get,lambda:None,clock=lambda:NOW)
        self.assertEqual(len(calls),4)
        self.assertEqual(len(r['candidates']),1)
        self.assertFalse((self.root/'claim.json').exists())
        self.assertEqual(self.ledger.snapshot()['metadata_attempts'],4)

    def test_foreign_writer_blocks_scan_before_budget_or_requests(self):
        claim_global_market_writer(self.root/'claim.json',run_id='foreign',owner_pid=os.getpid(),
            owner_kind='fixture',plan_hash='b'*64,output_namespace=self.root/'foreign')
        with self.assertRaises(Exception):
            d.scan_once(self.ledger,self.plan,self.root/'claim.json',self.getter,lambda:None,clock=lambda:NOW)
        self.assertEqual(self.ledger.snapshot()['scans'],0)

    def test_bad_response_blocks_complete_scan_and_later_requests(self):
        def get(*a,**kw):
            raise TimeoutError('synthetic timeout')
        with self.assertRaises(TimeoutError):
            d.scan_once(self.ledger,self.plan,self.root/'claim.json',get,lambda:None,clock=lambda:NOW)
        state=self.ledger.snapshot()
        self.assertEqual(state['status'],'STOPPED_INCOMPLETE')
        self.assertEqual(state['metadata_attempts'],1)
        self.assertIsNotNone(state['pending'])

    def test_changed_report_same_event_count_rejected(self):
        self.ledger.start_scan(NOW)
        first=report(self.plan,[event()]);self.ledger.finish_scan(first)
        other=report(self.plan,[event('B')])
        with self.assertRaises(ValueError):
            self.ledger.reserve_batch(other,[event('B')],'premarket_depth_b',NOW)

    def test_first_pilot_budget_reserved_and_no_second_pilot(self):
        r=report(self.plan,[event()]);self.ledger.start_scan(NOW);self.ledger.finish_scan(r)
        self.ledger.reserve_batch(r,[event()],'premarket_depth_a',NOW)
        self.assertEqual(self.ledger.snapshot()['captures'],1)
        self.assertGreaterEqual(self.ledger.snapshot()['output_reserved'],c.LIMITS['max_output_bytes'])
        self.ledger.finish_batch('COMPLETED')
        with self.assertRaisesRegex(ValueError,'PILOT_REVIEW'):
            self.ledger.start_scan(NOW+900)

    def test_scan_to_coordinator_end_to_end_uses_temporary_outputs(self):
        plan=copy.deepcopy(self.plan)
        plan['capture']['window_after_min']=2/3
        plan['notice_limit']['minimum_useful_pre_min']=0
        now=[NOW]
        e={**event(t0=NOW+20),'capture_from_ts':NOW,'capture_to_ts':NOW+60}
        r=report(plan,[e]);self.ledger.start_scan(NOW);self.ledger.finish_scan(r)
        calls=[]
        def get(e,leg,**kw):
            self.assertTrue((self.root/'claim.json').exists());calls.append((e['base'],leg))
            return dict(usable=True,response_bytes=10,wire_bytes=10)
        result=d.capture_due(self.ledger,plan,r,self.root/'captures',self.root/'claim.json',
            get,lambda:None,clock=lambda:now[0],monotonic=lambda:now[0],sleep=lambda sec:now.__setitem__(0,now[0]+sec))
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(len(calls),5)
        self.assertEqual(self.ledger.snapshot()['book_attempts'],5)
        self.assertEqual(self.ledger.snapshot()['status'],'PILOT_REVIEW_REQUIRED')
        self.assertFalse((self.root/'claim.json').exists())

    def test_concurrent_reservations_allow_only_one_pending_request(self):
        from concurrent.futures import ThreadPoolExecutor
        self.ledger.start_scan(NOW)
        def reserve(key):
            try:
                self.ledger.begin_request('metadata',key,100,NOW)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,['one','two']))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.ledger.snapshot()['metadata_attempts'],1)

    def test_receipt_is_sanitized_not_copied_wholesale(self):
        def getter(*a,**kw):
            payload,receipt=self.getter(*a,**kw)
            return payload,{**receipt,'raw_payload':'SHOULD_NOT_BE_SAVED'}
        r=d.scan_once(self.ledger,self.plan,self.root/'claim.json',getter,lambda:None,clock=lambda:NOW)
        self.assertNotIn('SHOULD_NOT_BE_SAVED',json.dumps(r))

    def test_already_missed_start_is_reported_not_not_due(self):
        r=report(self.plan,[event(t0=NOW+100)])
        selected=d.select_batch(r,self.plan,NOW+200,{})
        self.assertEqual(selected['status'],'MISSED_CAPTURE_START')

    def test_budget_refusal_stops_coordinator_without_busy_loop(self):
        r=report(self.plan,[event()]);self.ledger.start_scan(NOW);self.ledger.finish_scan(r)
        calls=[]
        def get(*a,**kw):
            calls.append(a)
            raise AssertionError('no request should be sent')
        with patch.object(self.ledger,'begin_request',side_effect=ValueError('HTTP_BUDGET')):
            result=d.capture_due(self.ledger,self.plan,r,self.root/'captures',self.root/'claim.json',
                get,lambda:None,clock=lambda:NOW,monotonic=lambda:NOW,sleep=lambda sec:None)
        self.assertEqual(len(calls),0)
        self.assertEqual(result['status'],'STOPPED_INCOMPLETE')
        self.assertIn('CAMPAIGN_REQUEST_BLOCKED',result['stop_reason'])

    def test_immutable_refreeze_and_preflight_no_output(self):
        manifest=d.freeze(ROOT)
        path=self.root/'runtime.json';path.write_bytes(c.encoded(manifest))
        result=d.preflight(ROOT,path)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertFalse(result['writer_claim_created'])
        self.assertFalse(manifest['collection_enabled'])
        manifest['budget']['captures']+=1;path.write_bytes(c.encoded(manifest))
        with self.assertRaises(ValueError):
            d.preflight(ROOT,path)

    def test_output_budget_refuses_scan_before_request(self):
        ledger=d.Ledger.create(self.root/'zero-room.sqlite',campaign_id='small',
            plan_hash=self.plan['plan_hash'],runtime_hash='a'*64,started_ts=NOW,
            limits={**d.BUDGET,'output_bytes':d.LEDGER_BYTES})
        with self.assertRaisesRegex(ValueError,'OUTPUT_BUDGET'):
            ledger.start_scan(NOW)
        self.assertEqual(ledger.snapshot()['scans'],0)

    def test_combined_request_budget_independent_of_per_kind(self):
        ledger=d.Ledger.create(self.root/'combined.sqlite',campaign_id='small',
            plan_hash=self.plan['plan_hash'],runtime_hash='a'*64,started_ts=NOW,
            limits={**d.BUDGET,'total_attempts':1})
        ledger.start_scan(NOW);ledger.begin_request('metadata','first',10,NOW)
        ledger.settle_request('first',1)
        with self.assertRaisesRegex(ValueError,'HTTP_BUDGET'):
            ledger.begin_request('metadata','second',10,NOW)

    def test_failed_book_request_stops_after_one_and_keeps_reserved_bytes(self):
        r=report(self.plan,[event()]);self.ledger.start_scan(NOW);self.ledger.finish_scan(r)
        calls=[]
        def get(*a,**kw):
            calls.append(a);raise TimeoutError('fixture timeout')
        result=d.capture_due(self.ledger,self.plan,r,self.root/'captures',self.root/'claim.json',
            get,lambda:None,clock=lambda:NOW,monotonic=lambda:NOW,sleep=lambda sec:None)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['stop_reason'],'CAMPAIGN_REQUEST_UNSETTLED_NO_RETRY')
        self.assertEqual(self.ledger.snapshot()['book_bytes'],self.plan['capture']['max_response_bytes'])

    def test_corrupted_source_report_same_hash_cannot_be_consumed(self):
        import sqlite3
        r=report(self.plan,[event()]);self.ledger.start_scan(NOW);self.ledger.finish_scan(r)
        db=sqlite3.connect(self.ledger.path)
        try:
            with db:
                db.execute("UPDATE reports SET body='{}'")
        finally:
            db.close()
        with self.assertRaises(ValueError):
            self.ledger.reserve_batch(r,[event()],'premarket_depth_a',NOW)

    def test_scan_duration_exceeded_is_not_complete(self):
        now=[NOW]
        def getter(*a,**kw):
            value=self.getter(*a,**kw);now[0]+=301;return value
        with self.assertRaisesRegex(ValueError,'SCAN_RUNTIME'):
            d.scan_once(self.ledger,self.plan,self.root/'claim.json',getter,lambda:None,
                        clock=lambda:now[0],sleep=lambda _:None)
        self.assertEqual(self.ledger.snapshot()['status'],'STOPPED_INCOMPLETE')

    def test_batch_is_immutable_and_hash_bound_to_exact_scan(self):
        r=report(self.plan,[event()]);self.ledger.start_scan(NOW);self.ledger.finish_scan(r)
        batch=self.ledger.reserve_batch(r,[event()],'premarket_depth_a',NOW)
        self.assertEqual(batch['source_report_hash'],r['report_hash'])
        self.assertEqual(batch['batch_hash'],c.canonical(batch,'batch_hash'))
        self.assertEqual(self.ledger.batch('premarket_depth_a'),batch)
        with self.assertRaises(ValueError):
            self.ledger.reserve_batch(r,[event()],'premarket_depth_a',NOW)

    def test_review_boundary_prevents_start_of_unfinishable_window(self):
        now=NOW+14*86400-100
        e=event(t0=now+7200);r=report(self.plan,[e],now)
        self.ledger.start_scan(now);self.ledger.finish_scan(r)
        result=d.capture_due(self.ledger,self.plan,r,self.root/'captures',self.root/'claim.json',
            lambda *a,**k:self.fail('network'),lambda:None,clock=lambda:now)
        self.assertEqual(result['status'],'REVIEW_WINDOW_CONFLICT')
        self.assertEqual(self.ledger.snapshot()['batches'],0)
        self.assertFalse((self.root/'captures').exists())


if __name__=='__main__':
    unittest.main()
