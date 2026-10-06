"""Bounded Gate history diagnostics; never certifies a historical universe."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .contract import ROOT, OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import ts, write_immutable
from .sources import NoRedirect

API_DOC = 'https://www.gate.com/docs/developers/apiv4/en/spot/#market-k-line-chart'
SAMPLE_ROOT = OUTPUT_ROOT/'runs/history_sources_v1_20261006/artifacts/public-history-sample'
SAMPLE_AUDIT = OUTPUT_ROOT/'gate-source-audit.json'
CAP = 1000000


def requests_plan():
    requests = []
    # Fixed coverage/schema probes, not a selection of profitable assets or dates.
    for base in ('BTC', 'ETH'):
        for date, interval, count in (('2022-12-02', '1d', 30), ('2023-01-01', '1h', 6),
                                      ('2025-01-01', '1d', 2), ('2026-09-01', '1d', 2)):
            step = {'1h': 3600, '1d': 86400}[interval]
            start = int(ts(date+'T00:00:00Z'))
            end = start+step*count
            query = urllib.parse.urlencode(dict(currency_pair=base+'_USDT', interval=interval,
                                                **{'from': start, 'to': end-1}))
            requests.append(dict(kind='candles', base=base, interval=interval, step=step,
                                 start=start, end=end,
                                 url='https://api.gateio.ws/api/v4/spot/candlesticks?'+query))
    # These are directory-availability probes, not an assertion of an S3 API.
    for url in ('https://download.gatedata.org/',
                'https://download.gatedata.org/spot/candlesticks_1d/202301/'):
        requests.append(dict(kind='catalog_probe', url=url))
    return dict(schema='gate_history_probe_v1', requests=requests, max_requests=10,
                per_response_bytes=CAP, total_response_bytes=CAP*10, retries=0,
                redirects=False, proxies=False, max_runtime_sec=300,
                purpose='Schema, exact quote volume and historical catalog availability only',
                universe_certified=False, evaluation_authorized_by_this_audit=False)


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not an amount')
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid amount') from exc
    if not n.is_finite():
        raise ValueError('Nonfinite amount')
    return n


def normalize_rest(payload, spec):
    """Strict eight-column API schema. CSV archives do not use this schema."""
    if not isinstance(payload, list) or not payload:
        raise ValueError('No historical candles returned')
    result = []
    for row in payload:
        if not isinstance(row, list) or len(row) != 8 or str(row[7]).lower() != 'true':
            raise ValueError('Unverified schema or incomplete candle')
        at = number(row[0])
        if at != int(at) or not spec['start'] <= at < spec['end'] or (at-spec['start']) % spec['step']:
            raise ValueError('Candle outside requested UTC grid')
        q, c, h, l, o, v = map(number, row[1:7])
        if not 0 < l <= min(o, c) <= max(o, c) <= h or min(q, v) < 0:
            raise ValueError('Invalid OHLCV')
        # A unit swap must not silently turn base quantity into USDT turnover.
        if (v == 0 and q != 0) or (v > 0 and not l*v-Decimal('.000001') <= q <= h*v+Decimal('.000001')):
            raise ValueError('Quote/base volume units inconsistent with OHLC')
        result.append(dict(ts=int(at), end_ts=int(at)+spec['step'], symbol=spec['base']+'_USDT',
                           open=str(o), high=str(h), low=str(l), close=str(c), volume=str(v), quote_volume=str(q),
                           closed=True, quote_volume_method='EXCHANGE_REPORTED_NOT_VOLUME_TIMES_CLOSE'))
    result.sort(key=lambda r: r['ts'])
    if [r['ts'] for r in result] != list(range(spec['start'], spec['end'], spec['step'])):
        raise ValueError('Incomplete or duplicate requested candle grid')
    return result


def archive_comparison(rows, archive_raw):
    with gzip.GzipFile(fileobj=io.BytesIO(archive_raw)) as stream:
        raw = stream.read(32*1024**2+1)
    if len(raw) > 32*1024**2:
        raise ValueError('Archive decompression budget')
    archive = {}
    for values in csv.reader(io.StringIO(raw.decode('utf-8-sig'))):
        if len(values) != 6:
            raise ValueError('Unexpected archive schema')
        stamp = int(values[0])
        if stamp in archive:
            raise ValueError('Duplicate archive candle')
        archive[stamp] = values
    compared, base_matches, quote_matches, price_matches = 0, 0, 0, 0
    for row in rows:
        a = archive.get(row['ts'])
        if a is None:
            raise ValueError('REST candle missing in archive')
        compared += 1
        base_matches += number(a[1]) == number(row['volume'])
        quote_matches += number(a[1]) == number(row['quote_volume'])
        price_matches += all(number(a[i]) == number(row[k]) for i, k in
                             ((2, 'close'), (3, 'high'), (4, 'low'), (5, 'open')))
    if not compared:
        raise ValueError('No comparable rows')
    meaning = 'UNRESOLVED'
    if price_matches == compared and base_matches == compared and quote_matches < compared:
        meaning = 'BASE_VOLUME_MATCHES_API_ON_SAMPLED_ROWS'
    return dict(compared=compared, base_volume_matches=base_matches, quote_volume_matches=quote_matches,
                ohlc_matches=price_matches, archive_column_1=meaning,
                global_schema_certified=False, quote_turnover_reconstructible_from_csv=False)


def read_bounded(response, check, cap=CAP):
    declared = response.headers.get('Content-Length')
    declared = int(declared) if declared is not None else None
    if declared is not None and declared < 0:
        raise ValueError('Negative Content-Length')
    if declared is not None and declared > cap:
        return b'', dict(bytes_read=0, declared_length=declared, complete=False, reason='DECLARED_OVERSIZE')
    chunks, size, eof = [], 0, False
    while size < cap:
        check()
        chunk = response.read(min(65536, cap-size))
        if not chunk:
            eof = True
            break
        size += len(chunk)
        chunks.append(chunk)
    complete = (eof if declared is None else size == declared)
    return b''.join(chunks), dict(bytes_read=size, declared_length=declared, complete=complete,
                                  reason='COMPLETE' if complete else 'TRUNCATED_OR_LENGTH_MISMATCH')


def download_audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Audit namespace already used; no blind repeat')
    plan = requests_plan()
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    old = json.loads(SAMPLE_AUDIT.read_text(encoding='utf-8'))
    samples = {r['url']: r for r in old['records'] if r.get('archive_verified')}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records = []
    for i, spec in enumerate(plan['requests'], 1):
        check()
        print(f"History audit {i}/{len(plan['requests'])}: {spec['url']}", flush=True)
        record = dict(spec, attempts=1, retrieved_at=datetime.now(timezone.utc).isoformat(),
                      status='UNAVAILABLE_OR_INVALID', normalized_input_eligible=False)
        try:
            request = urllib.request.Request(spec['url'], headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
            with opener.open(request, timeout=15) as response:
                record['http_status'] = response.status
                raw, body = read_bounded(response, check)
            record['body'] = body
            if not body['complete']:
                record['status'] = 'BODY_NOT_COMPLETE'
            else:
                path = output/f'{i:02d}.response'
                with path.open('xb') as f:
                    f.write(raw)
                record.update(raw_file=path.name, raw_sha256=file_hash(path))
                if spec['kind'] == 'candles':
                    rows = normalize_rest(json.loads(raw), spec)
                    record.update(status='VALID_CANDLE_SAMPLE', rows=len(rows), first_ts=rows[0]['ts'],
                                  last_ts=rows[-1]['ts'], quote_volume_exact=True)
                    write_immutable(output/f'{i:02d}.normalized-sample.json', dict(
                        rows=rows, source_sha256=record['raw_sha256'], source_url=spec['url'],
                        eligible_for_evaluation=False, historical_publication_time_certified=False,
                        reason='Sample only, historical universe and full periods are not certified'))
                    if spec['interval'] == '1h':
                        url = f"https://download.gatedata.org/spot/candlesticks_1h/202301/{spec['base']}_USDT-202301.csv.gz"
                        sample = samples[url]
                        source = SAMPLE_ROOT/sample['path']
                        if source.parent != SAMPLE_ROOT or file_hash(source) != sample['sha256']:
                            raise ValueError('Prior sample provenance mismatch')
                        record['archive_comparison'] = archive_comparison(rows, source.read_bytes())
                        record['archive_sha256'] = sample['sha256']
                else:
                    record.update(status='CATALOG_RESPONSE_REQUIRES_REVIEW',
                                  historical_membership_complete=False)
        except urllib.error.HTTPError as exc:
            record.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
            exc.close()
        except (urllib.error.URLError, ValueError, OSError, EOFError, KeyError) as exc:
            if isinstance(exc, TimeoutError):
                raise
            record['error'] = str(exc)
        records.append(record)
        write_immutable(output/f'{i:02d}.receipt.json', record)
    result = dict(schema='gate_history_audit_v1', request_plan_hash=canonical_hash(plan),
                  plan_hash=build_plan()['plan_hash'], runtime_binding=runtime_binding(),
                  prior_sample_audit_sha256=file_hash(SAMPLE_AUDIT), requests=len(records), records=records,
                  eligible_for_evaluation=False, universe_certified=False,
                  blockers=['Historical complete Gate spot membership and as-of asset types remain unverified',
                            'Samples do not cover full development/walk-forward/final periods'],
                  documentation=API_DOC)
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
