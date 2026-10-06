"""Bounded provider-coverage audit, not a point-in-time market membership feed."""
from datetime import datetime
import json
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.request

from .contract import build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_history import CAP, read_bounded
from .sources import NoRedirect

URL = 'https://api.tardis.dev/v1/exchanges/gate-io'
DOC = 'https://docs.tardis.dev/historical-data-details/gate-io'


def request_plan():
    return dict(schema='gate_provider_metadata_probe_v1', requests=[URL], max_requests=1,
                per_response_bytes=CAP, total_response_bytes=CAP, max_runtime_sec=300,
                retries=0, redirects=False, proxies=False, credentials=False,
                purpose='Historical symbol discovery; provider availability is not listing membership',
                evaluation_eligible=False)


def utc_date(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('Explicit UTC provider timestamp required')
    return datetime.fromisoformat(value[:-1]+'+00:00')


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate JSON key')
        obj[key] = value
    return obj


def parse_metadata(raw, check=lambda: None):
    payload = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(payload, dict) or payload.get('id') != 'gate-io':
        raise ValueError('Wrong provider exchange')
    symbols = payload.get('availableSymbols')
    if not isinstance(symbols, list) or not symbols or len(symbols) > 20000:
        raise ValueError('Missing/oversized availableSymbols')
    rows, seen = [], set()
    for symbol in symbols:
        check()
        if not isinstance(symbol, dict):
            raise ValueError('Invalid symbol record')
        ident = symbol.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', ident) or ident in seen:
            raise ValueError('Invalid/duplicate symbol id')
        seen.add(ident)
        if symbol.get('type') != 'spot':
            raise ValueError('Non-spot symbol in Gate spot metadata')
        start = utc_date(symbol.get('availableSince'))
        end = symbol.get('availableTo')
        if end is not None and utc_date(end) <= start:
            raise ValueError('Reversed provider coverage interval')
        rows.append(dict(symbol=ident, instrument_type='spot',
                         provider_available_since=symbol['availableSince'], provider_available_to=end,
                         listing_ts=None, delisting_ts=None, asset_type=None, type_available_at=None))
    rows.sort(key=lambda row: row['symbol'])
    usdt = [r for r in rows if r['symbol'].endswith('_USDT')]
    return dict(symbols=rows, symbol_count=len(rows), usdt_symbol_count=len(usdt),
                finite_provider_interval_count=sum(r['provider_available_to'] is not None for r in rows),
                delisted_samples=[r for r in rows if r['symbol'] in ('TRC_USDT', 'EYWA_USDT', 'LIY_USDT', 'BICITY_USDT')],
                observed_field_names=sorted({k for s in symbols for k in s}),
                provider_intervals_are_listing_dates=False, missing_end_means='UNKNOWN_NOT_PROVEN_ACTIVE',
                historical_membership_complete=False, asset_types_verified=False,
                daily_turnover_complete=False, evaluation_eligible=False)


def audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('One-shot metadata namespace already used')
    plan = request_plan()
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    record = dict(url=URL, documentation_url=DOC, attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID')
    print('Gate historical provider metadata: one public request, no retry', flush=True)
    check()
    try:
        request = urllib.request.Request(URL, headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
        with opener.open(request, timeout=20) as response:
            record['http_status'] = response.status
            raw, body = read_bounded(response, check)
        record['body'] = body
        if not body['complete']:
            raise ValueError('Incomplete provider metadata cannot define an empty or complete universe')
        path = output/'provider-response.json'
        with path.open('xb') as stream:
            stream.write(raw)
        record.update(raw_file=path.name, sha256=file_hash(path))
        record.update(parsed=parse_metadata(raw, check), status='PROVIDER_COVERAGE_ONLY_NOT_PIT_MEMBERSHIP')
    except urllib.error.HTTPError as exc:
        record.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
        exc.close()
    except (urllib.error.URLError, ValueError, OSError) as exc:
        if isinstance(exc, TimeoutError):
            raise
        record['error'] = str(exc)
    result = dict(schema='gate_provider_metadata_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan),
                  requests=1, record=record, historical_universe_certified=False,
                  evaluation_eligible=False, input_status='BLOCKED_DATA',
                  unresolved=['Complete as-of membership including delistings and symbol reuse',
                              'As-of stablecoin/wrapped/staked/derivative asset classification',
                              'Complete previous 30 UTC days of exact quote turnover for ranking candidates'])
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
