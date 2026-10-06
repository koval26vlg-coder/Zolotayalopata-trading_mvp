"""Public option archive catalog and bounded prefix inspection, never a backtest."""
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import urllib.error
import urllib.request
import zlib

from .contract import build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_history import CAP, number, read_bounded
from .gate_metadata import unique_keys
from .sources import NoRedirect

CATALOG = 'https://www.okx.com/priapi/v5/broker/public/trade-data/download-link'
FAMILIES = ('BTC-USD', 'ETH-USD')
DAY = '2025-01-06'
DAY_MS = 1736121600000
DECOMPRESS_CAP = 8*1024**2


def request_plan():
    # Public website request, not account/trading API. Dates use UTC, not browser locale.
    payload = dict(module='4', instType='OPTION', instQueryParam=dict(instFamilyList=list(FAMILIES)),
                   dateQuery=dict(dateAggrType='daily', begin=str(DAY_MS+86400000-1), end=str(DAY_MS+86400000-1)))
    return dict(schema='okx_option_archive_probe_v1', catalog_url=CATALOG, catalog_method='POST',
                payload=payload, sample_day=DAY, max_requests=3, retries=0, proxies=False,
                redirects=False, credentials=False, per_response_bytes=CAP, total_response_bytes=3*CAP,
                prefix_range=f'bytes=0-{CAP-1}', max_runtime_sec=300,
                purpose='Verify actual historical option archive format, not profitability',
                full_archive_download=False, evaluation_eligible=False)


def parse_catalog(raw):
    value = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(value, dict) or str(value.get('code')) != '0':
        raise ValueError('Public catalog rejected request')
    data = value.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('details'), list):
        raise ValueError('Missing archive details')
    rows = []
    for group in data['details']:
        if not isinstance(group, dict) or group.get('instType') != 'OPTION' or group.get('instFamily') not in FAMILIES:
            raise ValueError('Unexpected instrument family/type')
        family = group['instFamily']
        entries = group.get('groupDetails')
        if not isinstance(entries, list):
            raise ValueError('Missing daily files')
        for item in entries:
            filename = f'{family}-optionchain-L2orderbook-400lv-{DAY}.tar.gz'
            url = f'https://static.okx.com/cdn/okx/match/orderbook/L2/400lv/daily/{DAY.replace("-", "")}/{filename}'
            if (item.get('filename') != filename or item.get('url') != url or
                    str(item.get('dateTs')) != str(DAY_MS) or number(item.get('sizeMB')) <= 0):
                raise ValueError('Catalog file/date/host binding mismatch')
            rows.append(dict(family=family, filename=filename, url=url, advertised_size_mb=str(item['sizeMB'])))
    if len({r['family'] for r in rows}) != len(rows) or len(rows) > len(FAMILIES):
        raise ValueError('Duplicate daily archive')
    return sorted(rows, key=lambda r: r['family'])


def validate_range(status, headers):
    if status != 206 or headers.get('Content-Encoding', 'identity').lower() != 'identity':
        raise ValueError('Server must honor the bounded byte range without content encoding')
    match = re.fullmatch(r'bytes 0-(\d+)/(\d+)', headers.get('Content-Range', ''))
    if not match:
        raise ValueError('Missing/invalid Content-Range')
    end, total = map(int, match.groups())
    if total <= 0 or end != min(CAP, total)-1 or int(headers.get('Content-Length', '-1')) != end+1:
        raise ValueError('Byte range/length mismatch')
    return dict(start=0, end=end, total_archive_bytes=total, entire_archive_in_response=end+1 == total)


def inspect_prefix(raw, check=lambda: None):
    inflater = zlib.decompressobj(16+zlib.MAX_WBITS)
    decoded = inflater.decompress(raw, DECOMPRESS_CAP)
    check()
    cursor, files, sample = 0, [], None
    while cursor+512 <= len(decoded) and len(files) < 20:
        check()
        header = decoded[cursor:cursor+512]
        if header == bytes(512):
            break
        expected = int(header[148:156].rstrip(b'\x00 ').strip() or b'0', 8)
        if sum(header[:148])+8*32+sum(header[156:]) != expected:
            raise ValueError('Invalid TAR header checksum')
        name = header[:100].split(b'\x00')[0].decode('utf-8')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('Unsafe TAR member')
        size = int(header[124:136].rstrip(b'\x00 ').strip() or b'0', 8)
        if size < 0:
            raise ValueError('Negative TAR member size')
        kind = header[156:157]
        files.append(dict(name=name, declared_bytes=size, type=kind.decode('ascii').strip('\x00')))
        if kind in (b'0', b'\x00') and size > 0:
            content = decoded[cursor+512:cursor+512+min(size, 131072)]
            line, sep, _ = content.partition(b'\n')
            if sep or size == len(content):
                record = json.loads(line, object_pairs_hook=unique_keys)
                if not isinstance(record, dict):
                    raise ValueError('First record is not an object')
                sample = dict(member=name, top_level_fields=sorted(record), record=record)
            break
        cursor += 512+((size+511)//512)*512
    return dict(decoded_prefix_bytes=len(decoded), decompression_capped=bool(inflater.unconsumed_tail),
                gzip_end_seen=inflater.eof, members_seen=files, sample=sample,
                archive_complete=False, option_chain_complete=False, evaluation_eligible=False)


def audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('One-shot option source namespace already used')
    plan = request_plan()
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    headers = {'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity', 'Content-Type': 'application/json'}
    records, archives = [], []

    def fetch(request, name, prefix=False):
        check()
        record = dict(url=request.full_url, method=request.get_method(), attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID')
        records.append(record)
        print(f'OKX historical source {len(records)}/3: {name}', flush=True)
        try:
            with opener.open(request, timeout=20) as response:
                record['http_status'] = response.status
                if prefix:
                    record['range'] = validate_range(response.status, response.headers)
                raw, body = read_bounded(response, check)
            record['body'] = body
            if not body['complete']:
                raise ValueError('Incomplete bounded HTTP response')
            path = output/name
            with path.open('xb') as stream:
                stream.write(raw)
            record.update(raw_file=name, sha256=file_hash(path))
            if prefix:
                record.update(parsed=inspect_prefix(raw, check), status='PREFIX_ONLY_NOT_BACKTEST_INPUT')
            else:
                record.update(archives=parse_catalog(raw), status='PUBLIC_ARCHIVE_CATALOG_CHECKED')
            return record
        except urllib.error.HTTPError as exc:
            record.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
            exc.close()
        except (urllib.error.URLError, ValueError, OSError, zlib.error) as exc:
            if isinstance(exc, TimeoutError):
                raise
            record['error'] = str(exc)
        return record

    request = urllib.request.Request(CATALOG, data=json.dumps(plan['payload']).encode(), headers=headers, method='POST')
    catalog = fetch(request, 'catalog.json')
    archives = catalog.get('archives', [])
    write_immutable(output/'01.receipt.json', catalog)
    for index, archive in enumerate(archives, 2):
        request = urllib.request.Request(archive['url'], headers={**headers, 'Range': plan['prefix_range']})
        record = fetch(request, archive['family']+'.tar.gz.prefix', prefix=True)
        write_immutable(output/f'{index:02d}.receipt.json', record)
    result = dict(schema='okx_option_archive_source_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan),
                  requests=len(records), records=records, evaluation_eligible=False,
                  option_history_complete=False, historical_universe_certified=False,
                  no_authentication=True, no_full_archive_download=True)
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
