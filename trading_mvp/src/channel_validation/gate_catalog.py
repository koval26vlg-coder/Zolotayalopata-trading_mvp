"""Bounded archive-object discovery, not a certified PIT membership list."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_history import CAP, SAMPLE_ROOT, SAMPLE_AUDIT, read_bounded, number, normalize_rest
from .sources import NoRedirect

PROBE_RUN = OUTPUT_ROOT/'runs/history_gate_units_v2_20261006'
MONTHS = ('202301', '202501', '202609')
NS = '{http://s3.amazonaws.com/doc/2006-03-01/}'


def parse_catalog(raw, prefix, marker=''):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML declarations forbidden')
    root = ET.fromstring(raw)
    field = lambda key: root.findtext(NS+key, '')
    if root.tag != NS+'ListBucketResult' or field('Name') != 'gateio-public-data':
        raise ValueError('Unexpected public bucket response')
    if field('Prefix') != prefix or field('Marker') != marker or field('IsTruncated') not in ('true', 'false'):
        raise ValueError('Catalog prefix/marker/completeness mismatch')
    objects = []
    for item in root.findall(NS+'Contents'):
        key = item.findtext(NS+'Key', '')
        size = int(item.findtext(NS+'Size', '-1'))
        if not key.startswith(prefix) or key <= marker or '..' in key.split('/') or size < 0:
            raise ValueError('Out-of-scope catalog object')
        objects.append(dict(key=key, bytes=size, last_modified=item.findtext(NS+'LastModified'),
                            etag=item.findtext(NS+'ETag'), payload_sha256=None))
    keys = [r['key'] for r in objects]
    if keys != sorted(set(keys)) or len(keys) > 1000:
        raise ValueError('Duplicate/unsorted/oversized object catalog')
    truncated = field('IsTruncated') == 'true'
    # With no delimiter, ListObjects v1 uses the last key if NextMarker is absent.
    next_marker = field('NextMarker') or (keys[-1] if keys else '')
    if truncated and (not keys or next_marker != keys[-1] or next_marker <= marker):
        raise ValueError('Truncated catalog made no safe pagination progress')
    return dict(objects=objects, is_truncated=truncated, next_marker=next_marker if truncated else None)


def aggregate_archive(raw, rest_rows):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        content = f.read(32*1024**2+1)
    if len(content) > 32*1024**2:
        raise ValueError('Decompression budget')
    hours = {}
    for row in csv.reader(io.StringIO(content.decode('utf-8-sig'))):
        if len(row) != 6 or int(row[0]) in hours:
            raise ValueError('Archive schema/duplicate mismatch')
        hours[int(row[0])] = row
    comparisons = []
    for rest in rest_rows:
        expected = range(rest['ts'], rest['end_ts'], 3600)
        if any(at not in hours for at in expected):
            raise ValueError('Missing hour; cannot compare full daily volume')
        rows = [hours[at] for at in expected]
        volume = sum((number(r[1]) for r in rows), Decimal(0))
        comparisons.append(dict(ts=rest['ts'], hours=len(rows),
                                base_volume_equal=volume == number(rest['volume']),
                                base_volume_difference=str(volume-number(rest['volume'])),
                                quote_volume_equal=volume == number(rest['quote_volume']),
                                ohlc_equal=(number(rows[0][5]) == number(rest['open']) and
                                            number(rows[-1][2]) == number(rest['close']) and
                                            max(number(r[3]) for r in rows) == number(rest['high']) and
                                            min(number(r[4]) for r in rows) == number(rest['low']))))
    return dict(comparisons=comparisons, full_schema_certification=False,
                inferred_volume_unit=('BASE_ON_SAMPLED_DAYS' if comparisons and all(
                    c['base_volume_equal'] and c['ohlc_equal'] and not c['quote_volume_equal'] for c in comparisons) else 'UNRESOLVED'))


def checked_json(path, hash_field=None):
    path = Path(path)
    before = file_hash(path)
    result = json.loads(path.read_text(encoding='utf-8-sig'))
    if file_hash(path) != before:
        raise ValueError('Input changed while reading')
    if hash_field and result[hash_field] != canonical_hash({k: v for k, v in result.items() if k != hash_field}):
        raise ValueError('Input content binding mismatch')
    return result, before


def reconcile_samples(check):
    complete, _ = checked_json(PROBE_RUN/'completion.json')
    audit, digest = checked_json(PROBE_RUN/'artifacts/gate-history-audit/audit.json', 'audit_hash')
    if complete['status'] != 'COMPLETE' or complete['plan_hash'] != build_plan()['plan_hash']:
        raise ValueError('Completed matching source audit required')
    if canonical_hash(audit['runtime_binding']) != complete['runtime_hash'] or audit['plan_hash'] != complete['plan_hash']:
        raise ValueError('Source audit runtime/plan mismatch')
    old, old_hash = checked_json(SAMPLE_AUDIT)
    if old_hash != audit['prior_sample_audit_sha256']:
        raise ValueError('Source audit lineage changed')
    samples = {r['url']: r for r in old['records'] if r.get('archive_verified')}
    evidence = []
    for record in audit['records']:
        check()
        if record['status'] != 'VALID_CANDLE_SAMPLE' or record['start'] < 1704067200:
            continue
        path = PROBE_RUN/'artifacts/gate-history-audit'/record['raw_file']
        if path.parent != PROBE_RUN/'artifacts/gate-history-audit' or file_hash(path) != record['raw_sha256']:
            raise ValueError('REST sample binding mismatch')
        rows = normalize_rest(json.loads(path.read_bytes()), record)
        month = datetime.fromtimestamp(record['start'], timezone.utc).strftime('%Y%m')
        url = f"https://download.gatedata.org/spot/candlesticks_1h/{month}/{record['base']}_USDT-{month}.csv.gz"
        sample = samples[url]
        archive = SAMPLE_ROOT/sample['path']
        if archive.parent != SAMPLE_ROOT or file_hash(archive) != sample['sha256']:
            raise ValueError('CSV sample binding mismatch')
        evidence.append(dict(base=record['base'], month=month, rest_sha256=record['raw_sha256'],
                             archive_sha256=sample['sha256'], **aggregate_archive(archive.read_bytes(), rows)))
    catalog_record = audit['records'][8]
    catalog_raw = PROBE_RUN/'artifacts/gate-history-audit'/catalog_record['raw_file']
    if file_hash(catalog_raw) != catalog_record['raw_sha256']:
        raise ValueError('Catalog source proof mismatch')
    parse_catalog(catalog_raw.read_bytes(), '')
    return dict(parent_audit_sha256=digest, old_sample_audit_sha256=old_hash, comparisons=evidence,
                universe_certified=False, evaluation_eligible=False)


def catalog_audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Catalog namespace already used; no blind repeat')
    reconciliation = reconcile_samples(check)
    plan = dict(months=list(MONTHS), prefix_template='spot/candlesticks_1d/{month}/',
                max_pages_per_month=4, max_requests=12, max_runtime_sec=300,
                bytes_per_response=CAP, total_response_bytes=CAP*12, retries=0,
                no_proxies=True, no_redirects=True, no_credentials=True,
                pagination='ListObjects v1 marker from verified previous page; no delimiter',
                historical_universe_certified=False)
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    write_immutable(output/'volume-reconciliation.json', reconciliation)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    months, attempts = [], 0
    for month in MONTHS:
        marker, objects, receipts, finished, error = '', [], [], False, None
        prefix = plan['prefix_template'].format(month=month)
        for page in range(1, 5):
            check()
            query = urllib.parse.urlencode(dict(prefix=prefix, marker=marker, **{'max-keys': 1000}))
            url = 'https://download.gatedata.org/?'+query
            attempts += 1
            receipt = dict(url=url, page=page, month=month, marker=marker, attempt=1)
            print(f'Gate archive catalog {month} page {page}, request {attempts}/12', flush=True)
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
                with opener.open(request, timeout=15) as response:
                    receipt['http_status'] = response.status
                    raw, body = read_bounded(response, check)
                receipt['body'] = body
                if not body['complete']:
                    raise ValueError('Catalog body incomplete')
                path = output/f'{month}-{page}.xml'
                with path.open('xb') as f:
                    f.write(raw)
                receipt.update(raw_file=path.name, sha256=file_hash(path))
                parsed = parse_catalog(raw, prefix, marker)
                objects.extend(parsed['objects'])
                receipt.update(objects=len(parsed['objects']), is_truncated=parsed['is_truncated'])
                finished = not parsed['is_truncated']
                marker = parsed['next_marker']
            except urllib.error.HTTPError as exc:
                receipt['http_status'] = exc.code
                error = 'HTTP_ERROR_NO_RETRY'
                exc.close()
            except (urllib.error.URLError, ValueError, OSError, ET.ParseError) as exc:
                if isinstance(exc, TimeoutError):
                    raise
                error = str(exc)
            receipt['error'] = error
            receipts.append(receipt)
            write_immutable(output/f'{month}-{page}.receipt.json', receipt)
            if error or finished:
                break
        pattern = re.compile(re.escape(prefix)+r'([A-Za-z0-9_]+)_USDT-'+month+r'\.csv\.gz')
        pairs = sorted({m.group(1)+'_USDT' for row in objects if (m := pattern.fullmatch(row['key'])) and row['bytes'] > 0})
        months.append(dict(month=month, prefix=prefix, objects=objects, usdt_archive_pairs=pairs,
                           pages=len(receipts), catalog_listing_complete=finished and error is None,
                           next_marker=marker, error=error, receipts=receipts,
                           historical_membership_complete=False, asset_types_verified=False,
                           warning='File presence does not prove exact listing/delisting time or historical asset type'))
    result = dict(schema='gate_monthly_archive_catalog_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan), requests=attempts,
                  source_reconciliation=reconciliation, months=months, evaluation_eligible=False,
                  next_step='Resolve listing lifecycle, as-of asset types and preceding 30-day exact turnover before ranking')
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
