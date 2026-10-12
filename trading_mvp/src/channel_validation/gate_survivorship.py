"""One-shot delisted-pair diagnostics; never promotes today's list to PIT data."""
import csv
import gzip
import io
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .contract import build_plan, canonical_hash, file_hash, runtime_binding
from .data import ts, write_immutable
from .gate_catalog import aggregate_archive
from .gate_history import CAP, normalize_rest, number, read_bounded
from .sources import NoRedirect

SYMBOLS_URL = 'https://www.gate.com/api/web/v1/tst/market_symbols?sub_website_id=0'
NOTICE_URL = 'https://www.gate.com/announcements/article/101367'
PAIRS = ('TRC', 'EYWA')


def request_plan():
    requests = [dict(kind='export_symbols', url=SYMBOLS_URL),
                dict(kind='notice', url=NOTICE_URL)]
    start = int(ts('2026-08-01T00:00:00Z'))
    end = start+2*86400
    # The first two pairs in a dated delisting notice, not chosen by returns.
    for base in PAIRS:
        pair = base+'_USDT'
        requests.append(dict(kind='hourly_archive', base=base, start=start,
                             end=int(ts('2026-09-01T00:00:00Z')), step=3600,
                             url=f'https://download.gatedata.org/spot/candlesticks_1h/202608/{pair}-202608.csv.gz'))
        query = urllib.parse.urlencode(dict(currency_pair=pair, interval='1d', **{'from': start, 'to': end-1}))
        requests.append(dict(kind='daily_rest', base=base, start=start, end=end, step=86400,
                             url='https://api.gateio.ws/api/v4/spot/candlesticks?'+query))
        requests.append(dict(kind='current_pair', base=base,
                             url='https://api.gateio.ws/api/v4/spot/currency_pairs/'+pair))
    return dict(schema='gate_delisted_pair_probe_v1', requests=requests, max_requests=8,
                per_response_bytes=CAP, total_response_bytes=8*CAP, max_runtime_sec=300,
                retries=0, redirects=False, proxies=False, credentials=False,
                sample_selection='First two rows of official notice 101367; coverage test only',
                notice_published_utc='2026-08-26T07:10:00Z',
                notice_effective_utc='2026-09-02T03:00:00Z',
                notice_dates_basis='Manually read public article; not a complete lifecycle ledger',
                historical_universe_certified=False, evaluation_eligible=False)


def parse_symbols(payload):
    if not isinstance(payload, dict) or payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
        raise ValueError('Invalid export symbol response')
    values = payload['data'].get('spot')
    if not isinstance(values, list) or not values:
        raise ValueError('Missing spot export symbols')
    result = []
    for value in values:
        if not isinstance(value, str) or value.count('_') != 1 or not all(value.split('_')) or any(c.isspace() for c in value):
            raise ValueError('Invalid export symbol')
        result.append(value.upper())
    if len(result) != len(set(result)):
        raise ValueError('Duplicate export symbol')
    return dict(pairs=sorted(result), count=len(result), observed_at=payload.get('timestamp'),
                historical_membership_complete=False, asset_types_verified=False)


def parse_archive(raw, spec):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(32*1024**2+1)
    if len(decoded) > 32*1024**2:
        raise ValueError('Decompression budget exceeded')
    stamps = []
    for row in csv.reader(io.StringIO(decoded.decode('utf-8-sig'))):
        if len(row) != 6:
            raise ValueError('Archive column mismatch')
        at, volume, close, high, low, opening = map(number, row)
        if at != int(at) or not spec['start'] <= at < spec['end'] or (at-spec['start']) % spec['step']:
            raise ValueError('Archive timestamp outside requested grid')
        if volume < 0 or not 0 < low <= min(close, opening) <= max(close, opening) <= high:
            raise ValueError('Invalid archive OHLCV')
        stamps.append(int(at))
    expected = list(range(spec['start'], spec['end'], spec['step']))
    if not stamps or len(stamps) != len(set(stamps)):
        raise ValueError('Empty or duplicate archive')
    return dict(rows=len(stamps), first=min(stamps), last=max(stamps),
                full_requested_grid=sorted(stamps) == expected,
                missing_bars=len(set(expected)-set(stamps)),
                exact_quote_turnover_available=False, historical_membership_complete=False)


def conclusions(records):
    symbol_records = [r for r in records if r['kind'] == 'export_symbols' and r.get('parsed')]
    symbols = set(symbol_records[0]['parsed']['pairs']) if symbol_records else None
    samples = []
    for base in PAIRS:
        pair = base+'_USDT'
        archive = next((r for r in records if r.get('base') == base and r['kind'] == 'hourly_archive'), {})
        daily = next((r for r in records if r.get('base') == base and r['kind'] == 'daily_rest'), {})
        parsed = archive.get('parsed', {})
        missing = None if symbols is None else pair not in symbols
        historical_archive = bool(parsed.get('rows'))
        samples.append(dict(pair=pair, absent_from_export_symbols=missing,
                            historical_archive_observed=historical_archive,
                            export_list_missing_historical_pair=missing is True and historical_archive,
                            full_requested_archive_grid=parsed.get('full_requested_grid', False),
                            exact_daily_turnover_observed=bool(daily.get('parsed'))))
    return dict(samples=samples, historical_universe_certified=False, evaluation_eligible=False,
                reason='Sample availability is not complete historical membership, as-of types or 30-day ranking coverage')


def audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('One-shot namespace already used')
    plan = request_plan()
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records, payloads = [], {}
    for index, spec in enumerate(plan['requests'], 1):
        check()
        record = dict(**spec, attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID')
        print(f"Delisted-pair audit {index}/8: {spec['kind']} {spec.get('base', '')}", flush=True)
        try:
            request = urllib.request.Request(spec['url'], headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
            try:
                response = opener.open(request, timeout=15)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                record['http_status'] = response.status
                raw, body = read_bounded(response, check)
            record['body'] = body
            if not body['complete']:
                raise ValueError('Incomplete source body; no completeness inference')
            path = output/f'{index:02d}.raw'
            with path.open('xb') as stream:
                stream.write(raw)
            record.update(raw_file=path.name, sha256=file_hash(path))
            if record['http_status'] != 200:
                record['status'] = 'HTTP_ERROR_NO_RETRY'
                # Store only structured public API diagnostics, not arbitrary HTML text.
                if spec['kind'] in ('daily_rest', 'current_pair'):
                    try:
                        error = json.loads(raw)
                        if isinstance(error, dict):
                            record['api_error'] = {k: str(error[k])[:300] for k in ('label', 'message') if k in error}
                    except (ValueError, UnicodeError):
                        pass
            elif spec['kind'] == 'export_symbols':
                record['parsed'] = parse_symbols(json.loads(raw))
                record['status'] = 'CURRENT_EXPORT_LIST_ONLY'
            elif spec['kind'] == 'hourly_archive':
                record['parsed'] = parse_archive(raw, spec)
                record['status'] = 'ARCHIVE_SCHEMA_CHECKED'
                payloads[spec['base']] = raw
            elif spec['kind'] == 'daily_rest':
                rows = normalize_rest(json.loads(raw), spec)
                record['parsed'] = dict(rows=len(rows), exact_quote_turnover=True)
                record['status'] = 'DAILY_SAMPLE_VALID'
                if spec['base'] in payloads:
                    record['archive_reconciliation'] = aggregate_archive(payloads[spec['base']], rows)
            elif spec['kind'] == 'current_pair':
                pair = json.loads(raw)
                if not isinstance(pair, dict) or pair.get('id') != spec['base']+'_USDT':
                    raise ValueError('Current pair response mismatch')
                record['parsed'] = {k: pair.get(k) for k in ('id', 'trade_status', 'buy_start', 'sell_start', 'delisting_time', 'type')}
                record['status'] = 'CURRENT_METADATA_ONLY'
            else:
                record['status'] = 'NOTICE_CAPTURED_NOT_LIFECYCLE_CERTIFIED'
        except (urllib.error.URLError, ValueError, OSError, EOFError, UnicodeError) as exc:
            if isinstance(exc, TimeoutError):
                raise
            record['error'] = str(exc)
        records.append(record)
        write_immutable(output/f'{index:02d}.receipt.json', record)
    result = dict(schema='gate_survivorship_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan),
                  requests=len(records), records=records, **conclusions(records))
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
