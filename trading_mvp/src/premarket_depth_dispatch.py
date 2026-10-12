"""Offline-tested discovery -> durable budget -> serial coordinator integration.

No CLI network mode. Transport and a fresh execution guard must be explicitly
injected by a future visible gateway; this module never schedules or spawns work.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time

import premarket_depth_coordinator as c
from global_market_writer_claim import claim_global_market_writer, release_global_market_writer
from premarket_forward_depth_watch import _scan_gate, _scan_okx, qualifies

BUDGET = dict(scans=4032, captures=24, batches=24, metadata_attempts=16128,
              book_attempts=38400, total_attempts=54528, metadata_bytes=18*1024**3,
              book_bytes=6*1024**3, total_bytes=24*1024**3, output_bytes=2*1024**3)
LEDGER_BYTES = 256*1024**2
SCAN_OUTPUT_BYTES = 16384
SCAN_INTERVAL = 900
SCAN_RUNTIME = 300
REVIEW_DAY = 14
HORIZON_DAYS = 42
MANIFEST = 'docs/plans/premarket-depth-dispatch-runtime-20261006-v1.json'


def digest(value):
    return hashlib.sha256(c.encoded(value)).hexdigest()


def finite_ts(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('invalid timestamp')
    return value


def check_report(report, plan_hash):
    if (report.get('status') != 'COMPLETE' or report.get('plan_hash') != plan_hash
            or report.get('report_hash') != c.canonical(report, 'report_hash')):
        raise ValueError('scan report binding mismatch')
    finite_ts(report['observed_ts'])


class Ledger:
    """FULL-synchronous SQLite transactions; unsettled reservations fail closed.

    Body capacity is committed BEFORE a request. Only its one matching receipt
    can refund unused body bytes. Request identity is never refunded or reused.
    Output allocations remain charged in full, including incomplete captures.
    """
    @classmethod
    def create(cls, path, *, campaign_id, plan_hash, runtime_hash, started_ts, limits=None):
        path = Path(path)
        finite_ts(started_ts)
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}', campaign_id):
            raise ValueError('invalid campaign id')
        limits = dict(BUDGET if limits is None else limits)
        if (set(limits) != set(BUDGET) or any(type(v) is not int or v <= 0 or v > BUDGET[k]
                for k,v in limits.items()) or limits['output_bytes'] < LEDGER_BYTES):
            raise ValueError('invalid budget')
        config = dict(campaign_id=campaign_id, plan_hash=plan_hash, runtime_hash=runtime_hash,
                      started_ts=started_ts, limits=limits)
        # Existing, corrupted, or partially created journals must never be reset.
        with path.open('xb'):
            pass
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA max_page_count=65536')
            db.executescript('''
                CREATE TABLE config (body TEXT NOT NULL, sha TEXT NOT NULL);
                CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, sha TEXT NOT NULL);
                CREATE TABLE audit (seq INTEGER PRIMARY KEY, action TEXT NOT NULL, body TEXT NOT NULL, previous TEXT NOT NULL, sha TEXT NOT NULL);
                CREATE TABLE requests (key TEXT PRIMARY KEY, kind TEXT NOT NULL, capacity INTEGER NOT NULL, actual INTEGER);
                CREATE TABLE reports (hash TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE batches (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO config VALUES (?,?)', (c.encoded(config).decode(),digest(config)))
            state = dict(status='ACTIVE', scans=0, captures=0, batches=0, metadata_attempts=0,
                         book_attempts=0, metadata_bytes=0, book_bytes=0,
                         output_reserved=LEDGER_BYTES, last_scan_ts=None, mode=None, pending=None,
                         report_hash=None, consumed={}, batch_id=None)
            cls._save(db, state, 'CREATE')
            db.commit()
        finally:
            db.close()
        return cls(path,plan_hash,runtime_hash)

    def __init__(self,path,plan_hash,runtime_hash):
        self.path=Path(path).resolve()
        if not self.path.is_file():
            raise ValueError('ledger absent; explicit initialization required')
        with self._db() as db:
            raw,sha=db.execute('SELECT body,sha FROM config').fetchone()
            self.config=c.decode(raw)
            if (digest(self.config)!=sha or self.config['plan_hash']!=plan_hash
                    or self.config['runtime_hash']!=runtime_hash):
                raise ValueError('ledger binding mismatch')
            previous='0'*64
            for expected,row in enumerate(db.execute('SELECT seq,action,body,previous,sha FROM audit ORDER BY seq'),1):
                seq,action,body,prev,h=row
                if seq!=expected or prev!=previous or h!=digest([seq,action,c.decode(body),prev]):
                    raise ValueError('ledger audit chain mismatch')
                previous=h
            self._state(db)

    @contextmanager
    def _db(self):
        if self.path.stat().st_size > LEDGER_BYTES:
            raise ValueError('LEDGER_SIZE_BUDGET')
        db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA max_page_count=65536')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _state(db):
        body,sha=db.execute('SELECT body,sha FROM state WHERE id=1').fetchone()
        state=c.decode(body)
        seq,action,last,prev,h=db.execute('SELECT seq,action,body,previous,sha FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        if sha!=digest(state) or body!=last or h!=digest([seq,action,state,prev]):
            raise ValueError('ledger state integrity mismatch')
        return state

    @staticmethod
    def _save(db,state,action):
        prior=db.execute('SELECT seq,sha FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        seq,prev=(prior[0]+1,prior[1]) if prior else (1,'0'*64)
        body=c.encoded(state).decode()
        db.execute('INSERT INTO audit VALUES (?,?,?,?,?)',(seq,action,body,prev,digest([seq,action,state,prev])))
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?,?)',(body,digest(state)))

    def snapshot(self):
        with self._db() as db:
            return self._state(db)

    def _window(self,state,now):
        age=finite_ts(now)-self.config['started_ts']
        if age<0 or age>=HORIZON_DAYS*86400:
            raise ValueError('CAMPAIGN_DEADLINE')
        if age>=REVIEW_DAY*86400:
            raise ValueError('DAY14_REVIEW_REQUIRED')
        if state['status']!='ACTIVE':
            raise ValueError(state['status'])
        if state['pending'] is not None:
            raise ValueError('PENDING_REQUEST_NO_RETRY')

    def start_scan(self,now):
        with self._db() as db:
            s=self._state(db);self._window(s,now)
            if s['mode'] is not None:
                raise ValueError('OPERATION_ALREADY_ACTIVE')
            if s['last_scan_ts'] is not None and now-s['last_scan_ts']<SCAN_INTERVAL:
                raise ValueError('SCAN_NOT_DUE')
            if s['scans']>=self.config['limits']['scans']:
                raise ValueError('SCAN_BUDGET')
            if s['output_reserved']+SCAN_OUTPUT_BYTES>self.config['limits']['output_bytes']:
                raise ValueError('OUTPUT_BUDGET')
            s.update(scans=s['scans']+1,last_scan_ts=now,mode='metadata',report_hash=None)
            s['output_reserved']+=SCAN_OUTPUT_BYTES
            self._save(db,s,'START_SCAN')

    def begin_request(self,kind,key,capacity,now):
        if kind not in ('metadata','book') or type(capacity) is not int or capacity<=0 or not 0<len(key)<=256:
            raise ValueError('invalid request')
        with self._db() as db:
            s=self._state(db);self._window(s,now);b=self.config['limits']
            if s['mode']!=kind:
                raise ValueError('request outside active operation')
            if (s[kind+'_attempts']>=b[kind+'_attempts']
                    or s['metadata_attempts']+s['book_attempts']>=b['total_attempts']):
                raise ValueError('HTTP_BUDGET')
            capacity=min(capacity,b[kind+'_bytes']-s[kind+'_bytes'],
                         b['total_bytes']-s['metadata_bytes']-s['book_bytes'])
            if capacity<=0:
                raise ValueError('RESPONSE_BUDGET')
            try:
                db.execute('INSERT INTO requests VALUES (?,?,?,NULL)',(key,kind,capacity))
            except sqlite3.IntegrityError as exc:
                raise ValueError('REQUEST_ALREADY_USED_NO_RETRY') from exc
            s[kind+'_attempts']+=1;s[kind+'_bytes']+=capacity
            s['pending']=dict(key=key,kind=kind,capacity=capacity)
            self._save(db,s,'RESERVE_REQUEST')
            return capacity

    def settle_request(self,key,actual):
        with self._db() as db:
            s=self._state(db);p=s['pending']
            if not p or p['key']!=key or type(actual) is not int or not 0<=actual<=p['capacity']:
                raise ValueError('request receipt mismatch')
            s[p['kind']+'_bytes']-=p['capacity']-actual
            db.execute('UPDATE requests SET actual=? WHERE key=? AND actual IS NULL',(actual,key))
            s['pending']=None;self._save(db,s,'SETTLE_REQUEST')

    def finish_scan(self,report):
        check_report(report,self.config['plan_hash'])
        if len(c.encoded(report))>SCAN_OUTPUT_BYTES:
            raise ValueError('SCAN_OUTPUT_BUDGET')
        with self._db() as db:
            s=self._state(db)
            if s['status']!='ACTIVE' or s['mode']!='metadata' or s['pending']:
                raise ValueError('scan incomplete')
            db.execute('INSERT INTO reports VALUES (?,?)',(report['report_hash'],c.encoded(report).decode()))
            s.update(report_hash=report['report_hash'],mode=None)
            self._save(db,s,'FINISH_SCAN')

    def reserve_batch(self,report,events,run_id,now):
        check_report(report,self.config['plan_hash'])
        with self._db() as db:
            s=self._state(db);self._window(s,now);b=self.config['limits']
            saved=db.execute('SELECT body FROM reports WHERE hash=?',(s['report_hash'],)).fetchone()
            if s['mode'] or s['report_hash']!=report['report_hash'] or not saved or c.decode(saved[0])!=report:
                raise ValueError('latest scan binding mismatch')
            if s['batches']:
                raise ValueError('PILOT_REVIEW_REQUIRED')
            if (not 1<=len(events)<=2 or s['captures']+len(events)>b['captures']
                    or s['batches']+1>b['batches']):
                raise ValueError('CAPTURE_BUDGET')
            if s['output_reserved']+c.LIMITS['max_output_bytes']>b['output_bytes']:
                raise ValueError('OUTPUT_BUDGET')
            for event in events:
                key=event['venue']+':'+event['base']
                if key in s['consumed'] or event not in report['candidates']:
                    raise ValueError('event reused or source changed')
                s['consumed'][key]=event['t0_ts']
            s.update(mode='book',batch_id=run_id,batches=s['batches']+1,captures=s['captures']+len(events))
            s['output_reserved']+=c.LIMITS['max_output_bytes']
            batch=dict(schema='premarket_depth_budgeted_batch_v1',run_id=run_id,
                plan_hash=self.config['plan_hash'],runtime_hash=self.config['runtime_hash'],
                source_report_hash=report['report_hash'],events=events,reserved_at_ts=now,
                output_reserved_bytes=c.LIMITS['max_output_bytes'])
            batch['batch_hash']=c.canonical(batch,'batch_hash')
            db.execute('INSERT INTO batches VALUES (?,?)',(run_id,c.encoded(batch).decode()))
            self._save(db,s,'RESERVE_BATCH')
            return batch

    def batch(self,run_id):
        with self._db() as db:
            row=db.execute('SELECT body FROM batches WHERE id=?',(run_id,)).fetchone()
            if not row:
                raise ValueError('batch not reserved')
            batch=c.decode(row[0])
            if (batch['batch_hash']!=c.canonical(batch,'batch_hash') or batch['run_id']!=run_id
                    or batch['plan_hash']!=self.config['plan_hash'] or batch['runtime_hash']!=self.config['runtime_hash']):
                raise ValueError('batch binding mismatch')
            return batch

    def finish_batch(self,status):
        with self._db() as db:
            s=self._state(db)
            if s['mode']!='book':
                raise ValueError('no active batch')
            s['status']='PILOT_REVIEW_REQUIRED' if status=='COMPLETED' and not s['pending'] else 'STOPPED_INCOMPLETE'
            s['mode']=None;self._save(db,s,'FINISH_BATCH')

    def abort(self):
        with self._db() as db:
            s=self._state(db);s['status']='STOPPED_INCOMPLETE'
            self._save(db,s,'ABORT_NO_RETRY')


def select_batch(report,plan,now,consumed):
    check_report(report,plan['plan_hash'])
    if not 0<=finite_ts(now)-report['observed_ts']<=SCAN_INTERVAL:
        raise ValueError('STALE_SCAN')
    candidates=report['candidates']
    seen=set();available=[]
    for e in candidates:
        c.validate_events([e],plan,c.LIMITS)
        key=e['venue']+':'+e['base']
        if key in seen:
            raise ValueError('ambiguous event identity')
        seen.add(key)
        if key in consumed:
            if consumed[key]!=e['t0_ts']:
                return dict(status='SCHEDULE_CHANGED_ALREADY_CAPTURED',events=[])
            continue
        available.append(e)
    available.sort(key=lambda e:(e['capture_from_ts'],e['venue'],e['base']))
    if any(e['capture_from_ts']<=now and now-e['capture_from_ts']>=plan['capture']['snapshot_interval_sec']
           for e in available):
        return dict(status='MISSED_CAPTURE_START',events=[])
    due=[e for e in available if e['capture_from_ts']<=now<e['t0_ts']]
    if not due:
        return dict(status='NOT_DUE',events=[])
    # Include the entire overlapping component, even events that start later.
    selected=[due[0]];end=selected[0]['capture_to_ts']
    for e in available:
        if e==selected[0]:
            continue
        if e['capture_from_ts']<end and e['capture_to_ts']>now:
            selected.append(e);end=max(end,e['capture_to_ts'])
    if len(selected)>c.LIMITS['max_events']:
        return dict(status='CAPACITY_BLOCKED',events=[])
    if end-now>c.LIMITS['max_runtime_sec']:
        return dict(status='WINDOW_SPAN_BLOCKED',events=[])
    if any(now-e['capture_from_ts']>=plan['capture']['snapshot_interval_sec'] for e in selected):
        return dict(status='MISSED_CAPTURE_START',events=[])
    return dict(status='DUE',events=selected)


def scan_once(ledger,plan,claim_path,get,assert_start_allowed,*,clock=time.time,sleep=time.sleep):
    if ledger.config['plan_hash']!=plan['plan_hash']:
        raise ValueError('plan binding mismatch')
    assert_start_allowed()
    started=clock();scan_id=f"premarket_depth_{ledger.config['campaign_id']}_{int(started)}"
    claim=claim_global_market_writer(claim_path,run_id=scan_id,owner_pid=os.getpid(),writer_pid=os.getpid(),
        terminal_pid=os.getppid(),owner_kind='premarket_metadata',plan_hash=ledger.config['runtime_hash'],output_namespace=ledger.path.parent)
    active=False;complete=False;sources=[]
    def owned():
        current=c.decode(Path(claim_path).read_text(encoding='utf-8'))
        if any(current.get(k)!=claim.get(k) for k in ('run_id','owner_pid','ownership_token')):
            raise ValueError('WRITER_OWNERSHIP_LOST')
    def bounded_get(url,params,**kw):
        owned()
        if sources:
            sleep(plan['capture']['min_interval_between_requests_sec'])
        remaining=SCAN_RUNTIME-(clock()-started)
        if remaining<=0:
            raise ValueError('SCAN_RUNTIME')
        key=scan_id+':'+str(len(sources))
        cap=ledger.begin_request('metadata',key,kw['max_bytes'],clock())
        payload,receipt=get(url,params,**{**kw,'max_bytes':cap,'timeout_sec':min(kw['timeout_sec'],remaining)})
        owned()
        if type(receipt.get('response_bytes')) is not int or not re.fullmatch('[0-9a-f]{64}',receipt.get('response_sha256','')):
            raise ValueError('response provenance absent')
        ledger.settle_request(key,receipt['response_bytes'])
        if clock()-started>=SCAN_RUNTIME:
            raise ValueError('SCAN_RUNTIME')
        # Reject duplicate identities before legacy pure parsers build dictionaries.
        if kw['allowed_host']=='www.okx.com':
            if not isinstance(payload,dict) or str(payload.get('code'))!='0' or not isinstance(payload.get('data'),list):
                raise ValueError('invalid OKX catalogue')
            rows=payload['data'];field='instId'
        else:
            if not isinstance(payload,list):
                raise ValueError('invalid Gate catalogue')
            rows=payload;field='id' if '/spot/' in url else 'name'
        ids=[r[field] for r in rows]
        if len(ids)!=len(set(ids)):
            raise ValueError('ambiguous catalogue identity')
        sources.append(dict(url=url,query=params,response_bytes=receipt['response_bytes'],
                            response_sha256=receipt['response_sha256']))
        return payload,receipt
    try:
        assert_start_allowed();ledger.start_scan(started);active=True
        cap=plan['capture']
        events=[]
        for parse in (_scan_okx,_scan_gate):
            events.extend(parse(bounded_get,plan,timeout=cap['request_timeout_sec'],max_bytes=cap['max_response_bytes']))
        now=clock();candidates=[];rejected=[]
        for e in events:
            if e['t0_ts']<=now:
                continue
            reason=qualifies(e,plan,now)
            start=max(now,e['t0_ts']-cap['window_before_min']*60,e['perp_launched_ts'])
            if e['t0_ts']-start<plan['notice_limit']['minimum_useful_pre_min']*60:
                reason='INSUFFICIENT_PRE_WINDOW'
            if reason:
                rejected.append(dict(venue=e['venue'],base=e['base'],t0_ts=e['t0_ts'],reason=reason));continue
            e.update(perp_ct_val=float(e['perp_ct_val']),capture_from_ts=start,
                     capture_to_ts=e['t0_ts']+cap['window_after_min']*60,
                     equity_note=dict(checked=False,reason='NO_EXTERNAL_LISTING_REFERENCE',excluded=False))
            c.validate_events([e],plan,c.LIMITS);candidates.append(e)
        report=dict(status='COMPLETE',plan_hash=plan['plan_hash'],observed_ts=now,
                    candidates=candidates,rejected=rejected,sources=sources)
        report['report_hash']=c.canonical(report,'report_hash')
        owned();ledger.finish_scan(report);complete=True
        return report
    except BaseException:
        if active:
            ledger.abort()
        raise
    finally:
        release_global_market_writer(claim_path,run_id=scan_id,owner_pid=os.getpid(),
            ownership_token=claim['ownership_token'],expected_plan_hash=ledger.config['runtime_hash'],
            final_status='COMPLETED' if complete else 'STOPPED_INCOMPLETE')


def capture_due(ledger,plan,report,output_root,claim_path,get,assert_start_allowed,*,
                clock=time.time,monotonic=time.monotonic,sleep=time.sleep,stop=lambda:False):
    state=ledger.snapshot()
    selected=select_batch(report,plan,clock(),state['consumed'])
    if selected['status']!='DUE':
        return selected
    if max(e['capture_to_ts'] for e in selected['events'])>=ledger.config['started_ts']+REVIEW_DAY*86400:
        return dict(status='REVIEW_WINDOW_CONFLICT',events=[])
    run_id='premarket_depth_'+ledger.config['campaign_id']+'_'+report['report_hash'][:16]
    output=Path(output_root)/run_id
    guard_calls=0;reserved=False;count=0
    def guard():
        nonlocal guard_calls,reserved
        assert_start_allowed();guard_calls+=1
        if guard_calls==2:
            # The coordinator owns the global claim before this durable reservation.
            batch=ledger.reserve_batch(report,selected['events'],run_id,clock());reserved=True
            if ledger.batch(run_id)!=batch:
                raise ValueError('batch readback mismatch')
    def bounded_get(e,leg,**kw):
        nonlocal count
        count+=1;key=run_id+':'+str(count)
        try:
            cap=ledger.begin_request('book',key,kw['max_bytes'],clock())
        except ValueError as exc:
            # The old loop records ValueError as a per-slot response failure.
            # A campaign-wide budget refusal must terminate it, not burn slots.
            raise RuntimeError('CAMPAIGN_REQUEST_BLOCKED: '+str(exc)) from exc
        row=get(e,leg,**{**kw,'max_bytes':cap})
        ledger.settle_request(key,row['response_bytes'])
        return row
    def stopped():
        # A failed/unsettled request must not be followed by another request.
        if ledger.snapshot()['pending'] is not None:
            raise RuntimeError('CAMPAIGN_REQUEST_UNSETTLED_NO_RETRY')
        return stop()
    try:
        result=c.capture_batch(plan=plan,events=selected['events'],output=output,claim_path=claim_path,
            run_id=run_id,binding_hash=ledger.config['runtime_hash'],get=bounded_get,assert_start_allowed=guard,
            clock=clock,monotonic=monotonic,sleep=sleep,stop=stopped)
        if reserved:
            ledger.finish_batch(result['status'])
        return result
    except BaseException:
        if reserved:
            ledger.abort()
        raise


def freeze(root):
    base,_=c.load_manifest(root,root/c.MANIFEST)
    result=dict(schema='premarket_depth_dispatch_runtime_v1',collection_enabled=False,
        schedules_resume_authorized=False,campaign=None,scope_changed=False,
        base_runtime=c.ref(root/c.MANIFEST),base_runtime_hash=base['manifest_hash'],
        budget=dict(BUDGET),scan_interval_sec=SCAN_INTERVAL,scan_runtime_sec=SCAN_RUNTIME,
        review_day=REVIEW_DAY,horizon_days=HORIZON_DAYS,pilot_batches_before_quality_review=1,
        code=[c.ref(root/'trading_mvp/src/premarket_depth_dispatch.py')],
        live_gateway_installed=False,production_ledger_initialized=False)
    result['manifest_hash']=c.canonical(result,'manifest_hash')
    return result


def preflight(root,path):
    value=c.decode(path.read_text(encoding='utf-8-sig'))
    if value.get('manifest_hash')!=c.canonical(value,'manifest_hash') or value!=freeze(root):
        raise ValueError('runtime binding mismatch')
    return dict(status='BLOCKED',reason='OFFLINE_ONLY_NO_LIVE_GATEWAY_OR_CAMPAIGN',
                offline_implementation_bound=True,network_requests=0,writer_claim_created=False,
                manifest_hash=value['manifest_hash'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--manifest',type=Path)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze-only',action='store_true');mode.add_argument('--preflight',action='store_true')
    args=parser.parse_args();root=args.repo_root.resolve();path=args.manifest or root/MANIFEST
    try:
        if args.freeze_only:
            data=(json.dumps(freeze(root),indent=2,allow_nan=False)+'\n').encode()
            with path.open('xb') as stream:
                stream.write(data)
            print('OFFLINE_DISPATCH_FROZEN');return 0
        result=preflight(root,path);print(json.dumps(result));return 2
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc))));return 2


if __name__=='__main__':
    raise SystemExit(main())
