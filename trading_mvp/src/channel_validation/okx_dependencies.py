"""Bounded option dependency audit. Never promotes candles or announcements to fills."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import ts, write_immutable
from .gate_catalog import checked_json
from .gate_history import number, read_bounded, CAP
from .gate_metadata import unique_keys
from .okx_history import CATALOG, FAMILIES, DAY_MS, parse_catalog
from .sources import NoRedirect

RUN_ID = 'history_okx_dependencies_v6_20261007'
EXIT_DAY = '2025-01-13'
EXIT_MS = DAY_MS+7*86400000
PARENT_HASH = 'a188c266039dd924a5a8e95ada9c554d259e9474a70f926a7a4791b0399b150e'
DOCUMENTS = (
    ('cap_change', 'https://www.okx.com/help/okx-to-adjust-parameters-for-options-fee-calculation'),
    ('tier_change', 'https://www.okx.com/help/okx-to-adjust-options-trading-fees'),
    ('current_specs', 'https://www.okx.com/en-gb/help/get-started-with-okx-options'),
)


def request_plan():
    requests = []
    for family in FAMILIES:
        for anchor in (DAY_MS, EXIT_MS):
            params = dict(instId=family, bar='1m', after=str(anchor+60000),
                          before=str(anchor-120000), limit='3')
            requests.append(dict(kind='index', family=family, anchor_ms=anchor,
                                 url='https://www.okx.com/api/v5/market/history-index-candles?'+urllib.parse.urlencode(params)))
    requests.append(dict(kind='catalog', url=CATALOG, payload=dict(module='4', instType='OPTION',
                         instQueryParam=dict(instFamilyList=list(FAMILIES)),
                         dateQuery=dict(dateAggrType='daily', begin=str(EXIT_MS+86400000-1), end=str(EXIT_MS+86400000-1)))))
    requests.extend(dict(kind=kind, url=url) for kind, url in DOCUMENTS)
    return dict(schema='okx_option_dependency_probe_v1', requests=requests, max_requests=8,
                retries=0, redirects=False, proxies=False, credentials=False, max_runtime_sec=300,
                per_response_bytes=CAP, total_response_bytes=8*CAP, full_archive_download=False,
                evaluation_eligible=False, fixed_run_id=RUN_ID)


def preflight():
    root = OUTPUT_ROOT/'continuation-v5'
    census, sha = checked_json(root/'census.json', 'census_hash')
    complete, _ = checked_json(root/'local-completion.json')
    if (census['census_hash'] != PARENT_HASH or not census['container_complete'] or
            census['plan_hash'] != build_plan()['plan_hash'] or complete['status'] != 'COMPLETE' or
            complete['runtime_hash'] != canonical_hash(census['runtime_binding'])):
        raise ValueError('Completed bound parent census required')
    return dict(census_hash=PARENT_HASH, census_file_sha256=sha)


def parse_index(raw, spec):
    payload = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(payload, dict) or str(payload.get('code')) != '0':
        raise ValueError('Index history API error')
    rows = payload.get('data')
    if not isinstance(rows, list) or len(rows) > 3 or spec['family'] not in FAMILIES:
        raise ValueError('Invalid index response/family')
    anchor, result = spec['anchor_ms'], []
    for row in rows:
        if not isinstance(row, list) or len(row) != 6 or row[5] != '1':
            raise ValueError('Expected six fields and a completed index candle')
        at, o, h, l, c = map(number, row[:5])
        if (at != int(at) or int(at) % 60000 or not anchor-120000 <= at < anchor+60000 or
                not 0 < l <= min(o, c) <= max(o, c) <= h):
            raise ValueError('Wrong UTC window/grid or invalid index prices')
        result.append(dict(start_ms=int(at), end_ms=int(at)+60000, open=str(o), high=str(h),
                           low=str(l), close=str(c), close_usable_not_before_ms=int(at)+60000))
    result.sort(key=lambda x: x['start_ms'])
    if len({x['start_ms'] for x in result}) != len(result):
        raise ValueError('Duplicate index candle')
    prior = [x for x in result if x['end_ms'] <= anchor]
    return dict(status='INDEX_REFERENCE_ONLY' if result else 'NO_INDEX_HISTORY', family=spec['family'],
                anchor_ms=anchor, candles=result, latest_closed_reference=prior[-1] if prior else None,
                execution_quote=False, publication_latency_verified=False, evaluation_eligible=False)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip-1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def inspect_document(raw, kind):
    parser = VisibleText()
    parser.feed(raw.decode('utf-8'))
    text = ' '.join(' '.join(parser.parts).split())
    result = dict(status='DOCUMENT_REQUIRES_REVIEW', date_coverage_certified=False,
                  jan2025_terms_verified=False, evaluation_eligible=False)
    if kind == 'cap_change' and all(x in text for x in (
            'OKX to adjust parameters for options fee calculation', 'May 15, 2025', '7:00 am UTC', '12.5%', '7%')):
        result.update(status='DATED_FEE_CAP_TRANSITION_FOUND', effective_at_utc='2025-05-15T07:00:00Z',
                      previous_cap_fraction='0.125', new_cap_fraction='0.07',
                      previous_effective_from=None, subsequent_effective_to=None)
    elif kind == 'tier_change' and all(x in text for x in (
            'OKX to adjust options trading fees', 'February 10, 2025', '10:40 am UTC', 'Lvl 1', '0.030%')):
        result.update(status='DATED_FEE_TIER_ANNOUNCEMENT_FOUND', effective_at_utc='2025-02-10T10:40:00Z',
                      prior_tiers_verified=False, applicability_requires_review=True)
    elif kind == 'current_specs' and all(x in text for x in ('Contract Multiplier', '0.01', '0.1')):
        result.update(status='CURRENT_SPEC_NOT_HISTORICAL_CERTIFICATE',
                      page_contains_2026_update=('2026' in text), historical_values_adopted=False)
    return result


def dated_taker_fee(terms, at, premium, quantity):
    """Pure native-currency arithmetic; callers must supply independently audited dated terms."""
    start, end = terms.get('valid_from'), terms.get('valid_to')
    if (not start or not end or not re.fullmatch(r'[0-9a-f]{64}', str(terms.get('evidence_sha256', ''))) or
            terms.get('verified') is not True or not ts(start) <= ts(at) < ts(end)):
        raise ValueError('Dated fee coverage missing; no backfill from a future announcement')
    if terms.get('premium_currency') != terms.get('settlement_currency') or terms.get('settlement_currency') not in ('BTC', 'ETH'):
        raise ValueError('Explicit native option units required')
    premium, quantity = number(premium), number(quantity)
    rate, cap, multiplier, size = [number(terms[k]) for k in ('taker_rate', 'premium_cap', 'multiplier', 'contract_value')]
    if (premium <= 0 or quantity <= 0 or quantity != int(quantity) or not 0 <= rate <= 1 or
            not 0 < cap <= 1 or multiplier <= 0 or size <= 0):
        raise ValueError('Invalid option fee inputs')
    return min(rate, premium*cap)*multiplier*size*quantity


def audit(output, check):
    output = Path(output)
    if output.resolve() != (OUTPUT_ROOT/'runs'/RUN_ID/'artifacts/okx-dependencies').resolve():
        raise ValueError('One-shot dependency audit RunId is fixed')
    if output.exists():
        raise FileExistsError('Dependency audit namespace already used; no blind retry')
    parent, plan = preflight(), request_plan()
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan), parent=parent))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records = []
    for index, spec in enumerate(plan['requests'], 1):
        check()
        print(f'Option dependency {index}/8: {spec["kind"]} {spec["url"]}', flush=True)
        record = dict(request=spec, attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID')
        payload = json.dumps(spec['payload']).encode() if 'payload' in spec else None
        request = urllib.request.Request(spec['url'], data=payload, headers={
            'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity', 'Content-Type': 'application/json'})
        try:
            with opener.open(request, timeout=20) as response:
                record['http_status'] = response.status
                if response.status != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Non-200 or encoded response')
                raw, body = read_bounded(response, check)
            record['body'] = body
            if not body['complete']:
                raise ValueError('Incomplete bounded response; no retry')
            path = output/f'{index:02d}.raw'
            with path.open('xb') as f:
                f.write(raw)
            record.update(raw_file=path.name, sha256=file_hash(path))
            if spec['kind'] == 'index':
                parsed = parse_index(raw, spec)
            elif spec['kind'] == 'catalog':
                archives = parse_catalog(raw, EXIT_DAY, EXIT_MS)
                parsed = dict(status='EXIT_ARCHIVE_LINKS_ONLY' if archives else 'NO_EXIT_ARCHIVE_LINKS',
                              archives=archives, archive_bytes_downloaded=0, exit_quotes_verified=False)
            else:
                parsed = inspect_document(raw, spec['kind'])
            record.update(status=parsed['status'], parsed=parsed)
        except urllib.error.HTTPError as exc:
            record.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
            exc.close()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if isinstance(exc, TimeoutError):
                raise
            record['error'] = str(exc)
        records.append(record)
        write_immutable(output/f'{index:02d}.receipt.json', record)
    result = dict(schema='okx_option_dependency_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), parent=parent, request_plan_hash=canonical_hash(plan),
                  requests=len(records), records=records, evaluation_eligible=False, metrics=None,
                  dated_terms_complete=False, exit_quotes_verified=False, missing_not_zero=True)
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
