"""One fixed HistData public archive, with no accounts or strategy evaluation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import io
from pathlib import Path, PurePosixPath
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_history import read_bounded
from .gate_catalog import checked_json
from .gold_history import AuditStopped
from .sources import NoRedirect

RUN_ID = 'history_histdata_gold_v8_20261007'
ARCHIVE_RUN_ID = 'history_histdata_archive_v8_20261007'
PARENT_RUNTIME = 'c8155375c217b922989def45ee106383f2e2f97e7173c0c1590d023498c6e855'
PARENT_AUDIT = '729df1024a04d9f51920a0a87f33bf0a5bee96ef291e14e2c4e954ecf655cbc3'
PAGE_SHA = 'f3431583179b3030397aad97396cdb87156b0b9f4e7ccaf13089bbc618d33d87'
PAGE = 'https://www.histdata.com/download-free-forex-data/?/ascii/tick-data-quotes/XAUUSD/2023/1'
ACTION = 'https://www.histdata.com/get.php'
FIELDS = dict(date='2023', datemonth='202301', platform='ASCII', timeframe='T', fxpair='XAUUSD')
MEMBER = 'DAT_ASCII_XAUUSD_T_202301.csv'
DOWNLOAD_CAP = 32*1024**2
DECODE_CAP = 256*1024**2
ROW_CAP = 2000000
EST = timezone(timedelta(hours=-5))


def request_plan():
    return dict(schema='histdata_single_archive_acquisition_v1', plan_hash=build_plan()['plan_hash'],
                fixed_run_id=RUN_ID, page=PAGE, allowed_action=ACTION, public_form_fields=FIELDS.copy(),
                expected_csv=MEMBER, selection='First development month, fixed before returns',
                max_requests=2, page_cap=1000000, archive_cap=DOWNLOAD_CAP,
                total_response_cap=DOWNLOAD_CAP+1000000, max_output_bytes=DOWNLOAD_CAP+2000000,
                max_decoded_bytes=DECODE_CAP, max_rows=ROW_CAP, max_runtime_sec=300, timeout_sec=20,
                source_probe=False, full_file_acquisition=True, retries=0, redirects=False,
                proxies=False, credentials=False, paid_data=False, zip_extraction=False,
                same_host_http_form_action_upgrade_to_https=True, research_contract_changed=False,
                evaluation_eligible=False)


class DownloadForms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms, self.current = [], None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'form':
            if self.current is not None:
                raise ValueError('Nested form')
            self.current = dict(id=values.get('id'), method=values.get('method', '').lower(), action=values.get('action', ''), fields={})
        elif tag == 'input' and self.current is not None and values.get('type', '').lower() == 'hidden':
            name = values.get('name')
            if not name or name in self.current['fields']:
                raise ValueError('Missing or duplicate form field')
            self.current['fields'][name] = values.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form' and self.current is not None:
            self.forms.append(self.current)
            self.current = None


def download_form(raw):
    parser = DownloadForms()
    parser.feed(raw.decode('utf-8'))
    if parser.current is not None:
        raise ValueError('Unclosed form')
    matches = []
    for form in parser.forms:
        if form['id'] != 'file_down':
            continue
        fields = form['fields']
        if not all(fields.get(k) == v for k, v in FIELDS.items()):
            continue
        action = urllib.parse.urljoin(PAGE, form['action'])
        # Only a same-host public download action may be upgraded; never downgrade TLS.
        if action == 'http://www.histdata.com/get.php':
            action = ACTION
        if (form['method'] != 'post' or action != ACTION or set(fields) != set(FIELDS)|{'tk'} or
                not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', fields['tk'])):
            raise ValueError('Unexpected public download form')
        matches.append(fields)
    if len(matches) != 1:
        raise ValueError('One exact XAUUSD January 2023 public form required')
    return urllib.parse.urlencode(matches[0]).encode('ascii')


def cached_form_preflight():
    parent = OUTPUT_ROOT/'runs'/RUN_ID
    complete, complete_sha = checked_json(parent/'completion.json')
    audit, audit_sha = checked_json(parent/'artifacts/histdata-sample/audit.json', 'audit_hash')
    owner, owner_sha = checked_json(parent/'owner.json')
    page = parent/'artifacts/histdata-sample/download-page.html'
    expected = dict(url=PAGE, method='GET', attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID',
                    response_cap=1000000, http_status=200,
                    body=dict(bytes_read=31616, declared_length=None, complete=True, reason='COMPLETE'),
                    error='Unexpected public download form', raw_file=page.name, sha256=PAGE_SHA)
    if (complete['status'] != 'COMPLETE' or complete['exit_code'] != 0 or
            complete['runtime_hash'] != PARENT_RUNTIME or audit['audit_hash'] != PARENT_AUDIT or
            canonical_hash(audit['runtime_binding']) != PARENT_RUNTIME or
            complete['plan_hash'] != build_plan()['plan_hash'] or audit['plan_hash'] != complete['plan_hash'] or
            audit['records'] != [expected] or audit['requests'] != 1 or audit['archive_parsed'] or
            file_hash(page) != PAGE_SHA or page.stat().st_size != 31616):
        raise ValueError('Exact completed GET-only parent required')
    artifacts = parent/'artifacts/histdata-sample'
    if sorted(p.name for p in artifacts.iterdir()) != ['01.attempt.json', '01.receipt.json', 'audit.json', 'download-page.html', 'request-plan.json']:
        raise ValueError('Parent contains additional progress')
    receipt, receipt_sha = checked_json(artifacts/'01.receipt.json')
    plan, plan_sha = checked_json(artifacts/'request-plan.json', 'request_plan_hash')
    if receipt != expected or plan['request_plan_hash'] != canonical_hash(request_plan()):
        raise ValueError('Original request evidence mismatch')
    elapsed = (parent/'completion.json').stat().st_mtime-datetime.fromisoformat(owner['worker_started_utc']).timestamp()
    if not 0 <= elapsed <= 60:
        raise ValueError('Parent exceeds the reserved 60-second runtime budget')
    payload = download_form(page.read_bytes())
    return dict(parent_run_id=RUN_ID, parent_audit_hash=PARENT_AUDIT, parent_runtime_hash=PARENT_RUNTIME,
                page_sha256=PAGE_SHA, audit_file_sha256=audit_sha, completion_file_sha256=complete_sha,
                owner_file_sha256=owner_sha, receipt_file_sha256=receipt_sha, plan_file_sha256=plan_sha,
                parent_elapsed_sec=elapsed, page_refetched=False, archive_previously_attempted=False), payload


def quote(line):
    values = line.decode('ascii').rstrip('\r\n').split(',')
    if len(values) != 4 or not re.fullmatch(r'202301\d{2} \d{9}', values[0]):
        raise ValueError('Unexpected month or tick schema')
    text = values[0]
    # strptime can backtrack variable-width fields and reinterpret invalid hour 24.
    stamp = datetime(int(text[:4]), int(text[4:6]), int(text[6:8]),
                     int(text[9:11]), int(text[11:13]), int(text[13:15]), int(text[15:])*1000, tzinfo=EST)
    prices = [Decimal(v) for v in values[1:]]
    if not all(p.is_finite() for p in prices) or not 0 < prices[0] <= prices[1] or prices[2] != 0:
        raise ValueError('Invalid quote or undocumented volume field')
    return int(stamp.timestamp()*1000), prices[0], prices[1]


def inspect_zip(raw, check=lambda: None):
    if len(raw) > DOWNLOAD_CAP:
        raise ValueError('Archive budget exceeded')
    bars, rows, decoded, previous, first, equal_times, gaps, max_gap = {}, 0, 0, None, None, 0, 0, 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if not 1 <= len(members) <= 8 or len(names) != len(set(names)) or names.count(MEMBER) != 1:
            raise ValueError('Unexpected ZIP members')
        if sum(m.file_size for m in members) > DECODE_CAP:
            raise ValueError('ZIP decompression budget')
        for member in members:
            check()
            name = PurePosixPath(member.filename)
            if (len(name.parts) != 1 or '\\' in member.filename or ':' in member.filename or
                    member.is_dir() or member.flag_bits & 1 or (member.external_attr >> 16) & 0o170000 == 0o120000 or
                    member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError('Unsafe ZIP member')
            if member.filename != MEMBER:
                if not member.filename.lower().endswith('.txt') or member.file_size > 1000000:
                    raise ValueError('Unknown non-CSV member')
                with archive.open(member) as source:
                    while source.read(65536):
                        check()  # Consume bounded auxiliary files to verify their CRC too.
                continue
            with archive.open(member) as source:
                while True:
                    check()
                    line = source.readline(257)
                    if not line:
                        break
                    decoded += len(line)
                    if len(line) > 256 or decoded > DECODE_CAP or rows >= ROW_CAP:
                        raise ValueError('CSV resource budget')
                    at, bid, ask = quote(line)
                    if previous is not None:
                        if at < previous:
                            raise ValueError('Unordered ticks')
                        delta = at-previous
                        equal_times += delta == 0
                        gaps += delta > 60000
                        max_gap = max(max_gap, delta)
                    first = at if first is None else first
                    previous, rows = at, rows+1
                    bucket = at//14400000*14400000
                    bar = bars.setdefault(bucket, dict(start_ms=bucket, end_ms=bucket+14400000, rows=0,
                                                       first_tick_ms=at, last_tick_ms=at,
                                                       bid=[bid]*4, ask=[ask]*4))
                    bar['rows'] += 1
                    bar['last_tick_ms'] = at
                    for side, value in (('bid', bid), ('ask', ask)):
                        old = bar[side]
                        bar[side] = [old[0], max(old[1], value), min(old[2], value), value]
                    if rows % 250000 == 0:
                        print(f'HistData ZIP validation: {rows} ticks', flush=True)
    if not rows:
        raise ValueError('Empty tick archive')
    summaries = [{**b, 'bid': list(map(str, b['bid'])), 'ask': list(map(str, b['ask'])),
                  'complete_session_verified': False, 'evaluation_eligible': False} for b in bars.values()]
    return dict(status='TICKS_PARSED_NOT_EVALUATOR_INPUT', rows=rows, csv_bytes=decoded,
                first_ms=first, last_ms=previous, equal_time_ticks=equal_times,
                gaps_over_one_minute=gaps, max_observed_gap_ms=max_gap, four_hour_diagnostics=summaries,
                timezone='FIXED_UTC_MINUS_05_NO_DST', calendar_certified=False, costs_verified=False,
                quote_volume_is_trade_volume=False, source_execution_venue_verified=False,
                missing_gaps_filled=False, metrics=None, evaluation_eligible=False)


def acquire(output, check, cached=False):
    output = Path(output)
    run_id = ARCHIVE_RUN_ID if cached else RUN_ID
    if output.resolve() != (OUTPUT_ROOT/'runs'/run_id/'artifacts/histdata-sample').resolve():
        raise ValueError('Fixed HistData namespace required; no renamed retry')
    if output.exists():
        raise FileExistsError('HistData attempt already recorded')
    plan = request_plan()
    data = None
    if cached:
        parent, data = cached_form_preflight()
        plan.update(fixed_run_id=run_id, parent=parent, max_requests=1, max_runtime_sec=240,
                    total_response_cap=DOWNLOAD_CAP, cumulative_requests_cap=2, cumulative_runtime_sec_cap=300)
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records, parsed = [], None

    def control():
        try:
            check()
        except TimeoutError as exc:
            raise AuditStopped(str(exc)) from exc

    for index in ((2,) if cached else (1, 2)):
        control()
        url = PAGE if index == 1 else ACTION
        cap = plan['page_cap'] if index == 1 else plan['archive_cap']
        record = dict(url=url, method='GET' if index == 1 else 'POST', attempts=1,
                      status='SOURCE_UNAVAILABLE_OR_INVALID', response_cap=cap)
        write_immutable(output/f'{index:02d}.attempt.json', record)
        print(f'HistData request {index}/2: {record["method"]} {url}', flush=True)
        headers = {'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'}
        if index == 2:
            headers.update({'Referer': PAGE, 'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=plan['timeout_sec']) as response:
                record['http_status'] = response.status
                if response.status != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Non-200 or encoded response')
                raw, body = read_bounded(response, control, cap=cap)
            record['body'] = body
            if not body['complete']:
                raise ValueError('Incomplete response; no retry or partial ZIP normalization')
            path = output/('download-page.html' if index == 1 else 'XAUUSD-202301.zip')
            with path.open('xb') as stream:
                stream.write(raw)
            record.update(raw_file=path.name, sha256=file_hash(path))
            if index == 1:
                data = download_form(raw)
                record['status'] = 'EXACT_PUBLIC_FORM_VALIDATED'
            else:
                parsed = inspect_zip(raw, control)
                record['status'] = parsed['status']
        except urllib.error.HTTPError as exc:
            record.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
            exc.close()
        except (urllib.error.URLError, OSError, ValueError, ArithmeticError, zipfile.BadZipFile) as exc:
            if isinstance(exc, AuditStopped):
                raise
            record['error'] = str(exc)
            if isinstance(exc, TimeoutError):
                record.update(status='SOURCE_TIMEOUT_NO_RETRY', bytes_read_unknown=True, reserved_response_bytes=cap)
        records.append(record)
        write_immutable(output/f'{index:02d}.receipt.json', record)
        if record['status'] != 'EXACT_PUBLIC_FORM_VALIDATED':
            break
    result = dict(schema='histdata_gold_sample_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan), records=records,
                  requests=len(records), archive_parsed=parsed is not None, parsed=parsed,
                  cumulative_requests=len(records)+(1 if cached else 0), page_refetched=False,
                  input_status='BLOCKED_DATA', metrics=None, evaluation_eligible=False,
                  failure_is_strategy_rejection=False, retry_authorized=False,
                  missing_not_zero=True, source_not_execution_venue=True)
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
