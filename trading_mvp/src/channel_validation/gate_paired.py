"""One bounded Gate archive-format probe, never an evaluation input."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.request
import zlib

from .contract import OUTPUT_ROOT, canonical_hash, file_hash
from .data import write_immutable
from .sources import NoRedirect

CAP = 1000000
RUN_ID = 'history_gate_paired_v16_20261008'
CHECKPOINT = OUTPUT_ROOT / 'continuation-v16'
DOC = 'https://www.gate.com/developer/historical_quotes'


def request_plan():
    requests = []
    for month in ('202301', '202501'):
        for market, kind in (('spot', 'orderbooks_slice'), ('futures_usdt', 'orderbooks_slice'),
                             ('futures_usdt', 'funding_applies'), ('futures_usdt', 'funding_updates'),
                             ('futures_usdt', 'mark_prices')):
            suffix = month+'0100.gz' if kind == 'orderbooks_slice' else month+'.csv.gz'
            requests.append(dict(month=month, market=market, kind=kind, symbol='BTC_USDT',
                                 url=f'https://download.gatedata.org/{market}/{kind}/{month}/BTC_USDT-{suffix}'))
    return dict(schema='gate_paired_archive_probe_v1', source_documentation=DOC,
                requests=requests, max_requests=10, per_response_bytes=CAP,
                total_response_bytes=10*CAP, max_runtime_sec=300, retries=0,
                redirects=False, proxies=False, decompressed_bytes_per_response=CAP,
                oversize_policy='READ_BOUNDED_PREFIX_ONLY_NEVER_CERTIFY_FULL_ARCHIVE',
                purpose='Availability, compression and raw schema only; no returns or signals',
                eligible_for_evaluation=False)


def preflight():
    path = CHECKPOINT / 'probe-plan.json'
    saved = json.loads(path.read_text(encoding='utf-8-sig'))
    plan = request_plan()
    if saved != dict(plan, request_plan_hash=canonical_hash(plan)):
        raise ValueError('Fixed paired archive request plan mismatch')
    return canonical_hash(plan)


def read_prefix(response, check, cap=CAP):
    declared = response.headers.get('Content-Length')
    declared = None if declared is None else int(declared)
    if declared is not None and declared < 0:
        raise ValueError('Negative declared length')
    chunks, size, eof = [], 0, False
    while size < cap:
        check()
        chunk = response.read(min(65536, cap-size))
        if not chunk:
            eof = True
            break
        chunks.append(chunk)
        size += len(chunk)
    complete = size == declared if declared is not None else eof
    return b''.join(chunks), dict(declared_length=declared, bytes_read=size, complete=complete,
                                  truncated=not complete,
                                  reason='COMPLETE' if complete else 'CAP_OR_LENGTH_MISMATCH')


def inspect_archive(raw, body_complete, decompressed_cap=CAP):
    if not raw.startswith(b'\x1f\x8b'):
        raise ValueError('Not a gzip archive')
    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
    try:
        plain = decoder.decompress(raw, decompressed_cap)
    except zlib.error as exc:
        raise ValueError('Invalid gzip stream') from exc
    expanded_cap = len(plain) == decompressed_cap and not decoder.eof
    if body_complete and not expanded_cap and (not decoder.eof or decoder.unused_data):
        raise ValueError('Incomplete gzip or unexpected additional member')
    # Inspect only whole prefix lines; no inferred column semantics or normalized quotes.
    lines = plain.split(b'\n')[:-1]
    previews = [line[:400].decode('utf-8', errors='replace') for line in lines[:2]]
    return dict(gzip_complete=bool(body_complete and decoder.eof and not decoder.unused_data),
                decompressed_bytes=len(plain), decompressed_truncated=expanded_cap or not body_complete,
                complete_lines_in_prefix=len(lines), first_line_previews=previews,
                sample_csv_widths=[len(next(csv.reader([line]))) for line in previews],
                column_semantics_verified=False, eligible_for_evaluation=False)


def probe_one(spec, opener, output, number, check):
    record = dict(spec, attempts=1, retrieved_at=datetime.now(timezone.utc).isoformat(),
                  status='UNAVAILABLE_OR_INVALID', eligible_for_evaluation=False,
                  body=dict(bytes_read=0, complete=False, reason='NO_SUCCESSFUL_BODY'))
    try:
        request = urllib.request.Request(spec['url'], headers={
            'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
        with opener.open(request, timeout=15) as response:
            record['http_status'] = response.status
            if response.status != 200:
                raise ValueError('Unexpected status; no partial-range reconstruction')
            raw, body = read_prefix(response, check)
        record['body'] = body
        path = Path(output) / f'{number:02d}.quarantined.gz-part'
        with path.open('xb') as f:
            f.write(raw)
        record.update(raw_file=path.name, raw_sha256=file_hash(path))
        record['inspection'] = inspect_archive(raw, body['complete'])
        record['status'] = ('GZIP_ARCHIVE_COMPLETE_SCHEMA_UNVERIFIED'
                            if record['inspection']['gzip_complete'] else 'GZIP_PREFIX_ONLY')
    except urllib.error.HTTPError as exc:
        record.update(http_status=exc.code, error='HTTP_ERROR_NO_REDIRECT_NO_RETRY')
        exc.close()
    except TimeoutError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        record['error'] = str(exc)
    return record


def audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('One-shot probe already attempted')
    request_hash = preflight()
    plan = request_plan()
    write_immutable(output/'request-plan.json', dict(plan, request_plan_hash=request_hash))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records = []
    for i, spec in enumerate(plan['requests'], 1):
        check()
        print(f"Gate paired archive {i}/10: {spec['url']}", flush=True)
        record = probe_one(spec, opener, output, i, check)
        records.append(record)
        write_immutable(output/f'{i:02d}.receipt.json', record)
        print(f"  {record['status']}; bytes={record['body']['bytes_read']}", flush=True)
    result = dict(schema='gate_paired_archive_probe_result_v1', request_plan_hash=request_hash,
                  requests_attempted=len(records), bytes_read=sum(r['body']['bytes_read'] for r in records),
                  records=records, eligible_for_evaluation=False, metrics=None,
                  status='BOUNDED_PROBE_COMPLETE_NOT_BACKTEST', repeat_authorized=False)
    if result['bytes_read'] > plan['total_response_bytes']:
        raise ValueError('Total probe response budget exceeded')
    write_immutable(output/'audit.json', dict(result, audit_hash=canonical_hash(result)))
    return result
