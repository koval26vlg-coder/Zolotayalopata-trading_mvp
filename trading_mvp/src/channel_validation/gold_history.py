"""Bounded public gold source audit, preserving unknown units and missing sessions."""
from datetime import datetime, timezone
import lzma
import math
from pathlib import Path
import ssl
import struct
import urllib.error
import urllib.request

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_history import CAP, read_bounded
from .gate_catalog import checked_json
from .sources import NoRedirect

RUN_ID = 'history_gold_source_v7_20261007'
REMAINING_RUN_ID = 'history_gold_unattempted_v7_20261007'
PARENT_RUNTIME = '807f9a5e9dea2e743f93dd138a39d4043b98b58adef05edbb171c1de7f3556fc'
DATES = ('2023-01-03', '2024-01-03', '2025-01-06', '2026-09-01')
HOURS = (12, 13, 14, 15)
DECODE_CAP = 16*1024**2
RECORD = struct.Struct('>IIIff')
DOCUMENTS = (
    'https://www.dukascopy.com/api/data/get/historical-data-export',
    'https://www.dukascopy.com/swiss/english/forex/forex-trading-accounts/link/',
    'https://www.dukascopy.com/wiki/en/development/strategy-api/orders-and-positions/order-amounts/',
)


class AuditStopped(TimeoutError):
    """Cooperative deadline/stop, distinct from a single socket timeout."""


def remaining_preflight():
    parent = OUTPUT_ROOT/'runs'/RUN_ID
    loaded, hashes = {}, {}
    for name in ('intent.json', 'owner.json', 'completion.json', 'failure.json'):
        loaded[name], hashes[name] = checked_json(parent/name)
    old_plan, hashes['request-plan.json'] = checked_json(parent/'artifacts/gold-history-audit/request-plan.json', 'request_plan_hash')
    complete, intent, failure = loaded['completion.json'], loaded['intent.json'], loaded['failure.json']
    if (complete['status'] != 'STOPPED_INCOMPLETE' or complete['exit_code'] != 2 or
            complete['runtime_hash'] != PARENT_RUNTIME or intent['runtime_hash'] != PARENT_RUNTIME or
            canonical_hash(intent['runtime']) != PARENT_RUNTIME or complete['plan_hash'] != build_plan()['plan_hash'] or
            failure != dict(error='The read operation timed out', retry_authorized=False) or
            old_plan['request_plan_hash'] != canonical_hash(request_plan())):
        raise ValueError('Exact first-request timeout provenance required')
    # The bound old implementation wrote a receipt after every request, before advancing.
    if sorted(p.name for p in (parent/'artifacts/gold-history-audit').iterdir()) != ['request-plan.json']:
        raise ValueError('Parent progress is not the exact known first-request interruption')
    started = datetime.fromisoformat(loaded['owner.json']['worker_started_utc']).timestamp()
    elapsed = (parent/'completion.json').stat().st_mtime-started
    if not 0 <= elapsed <= 60:
        raise ValueError('Remaining 240-second phase would not preserve total 300-second budget')
    return dict(run_id=RUN_ID, file_sha256=hashes, runtime_hash=PARENT_RUNTIME,
                parent_elapsed_sec=elapsed, first_request_not_retried=True,
                first_response_bytes_unknown=True, reserved_parent_bytes=CAP)


def request_plan():
    requests = []
    for day in DATES:
        date = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        for hour in HOURS:
            requests.append(dict(kind='hour_ticks', day=day, hour=hour,
                start_ms=int(date.replace(hour=hour).timestamp()*1000),
                url=f'https://datafeed.dukascopy.com/datafeed/XAUUSD/{date.year}/{date.month-1:02d}/{date.day:02d}/{hour:02d}h_ticks.bi5'))
    requests.extend(dict(kind='current_document', url=url) for url in DOCUMENTS)
    return dict(schema='gold_public_history_source_probe_v1', source_candidate='Dukascopy XAUUSD',
                model_id='gold_macd', plan_hash=build_plan()['plan_hash'], requests=requests,
                max_requests=19, retries=0, redirects=False, proxies=False, credentials=False,
                paid_data=False, s3_requester_pays=False, max_runtime_sec=300, timeout_sec=10,
                per_response_bytes=CAP, total_response_bytes=19*CAP, per_file_decoded_bytes=DECODE_CAP,
                decoder='LZMA-alone, big-endian >IIIff, milliseconds within explicit UTC hour',
                price_scale=None, price_units_verified=False, volume_units_verified=False,
                instrument_adopted_for_evaluation=False, evaluation_eligible=False, fixed_run_id=RUN_ID)


def inspect_hour(raw, start_ms, check=lambda: None, decoded_cap=DECODE_CAP):
    if not isinstance(start_ms, int) or start_ms % 3600000:
        raise ValueError('Explicit UTC hour required')
    check()
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE, memlimit=64*1024**2)
    decoded = decoder.decompress(raw, max_length=decoded_cap+1)
    if len(decoded) > decoded_cap:
        raise ValueError('Decoded gold sample exceeds budget')
    if not decoder.eof or decoder.unused_data:
        raise ValueError('Incomplete or concatenated LZMA source')
    if len(decoded) % RECORD.size:
        raise ValueError('Partial 20-byte tick record')
    count, previous, locked, same_ms, max_gap = 0, None, 0, 0, 0
    first, last, bid_ohlc, ask_ohlc, min_spread, max_spread = None, None, None, None, None, None
    for offset in range(0, len(decoded), RECORD.size):
        if count % 4096 == 0:
            check()
        at, ask, bid, ask_size, bid_size = RECORD.unpack_from(decoded, offset)
        if (at >= 3600000 or (previous is not None and at < previous) or not 0 < bid <= ask or
                not all(math.isfinite(size) and size >= 0 for size in (ask_size, bid_size))):
            raise ValueError('Invalid tick time/order/quote/size')
        if previous is not None:
            max_gap = max(max_gap, at-previous)
            same_ms += int(at == previous)
        if first is None:
            first = dict(ts_ms=start_ms+at, bid_points=bid, ask_points=ask)
            bid_ohlc, ask_ohlc = [bid]*4, [ask]*4
            min_spread = max_spread = ask-bid
        bid_ohlc = [bid_ohlc[0], max(bid_ohlc[1], bid), min(bid_ohlc[2], bid), bid]
        ask_ohlc = [ask_ohlc[0], max(ask_ohlc[1], ask), min(ask_ohlc[2], ask), ask]
        min_spread, max_spread = min(min_spread, ask-bid), max(max_spread, ask-bid)
        last = dict(ts_ms=start_ms+at, bid_points=bid, ask_points=ask)
        count, previous, locked = count+1, at, locked+int(ask == bid)
    return dict(status='RAW_POINT_QUOTES_VALID' if count else 'EMPTY_ARCHIVE_NOT_CALENDAR_EVIDENCE',
                start_ms=start_ms, end_ms=start_ms+3600000, decoded_bytes=len(decoded), records=count,
                first=first, last=last, bid_ohlc_points=bid_ohlc, ask_ohlc_points=ask_ohlc,
                min_spread_points=min_spread, max_spread_points=max_spread,
                locked_quotes=locked, same_timestamp_records=same_ms, max_internal_gap_ms=max_gap,
                transfer_complete=True, quote_sequence_certified=False, no_ticks_means_closed=False,
                price_scale=None, price_units_verified=False, volume_units_verified=False,
                publication_latency_verified=False, trading_volume=None, evaluation_eligible=False)


def four_hour_diagnostics(records):
    summaries = []
    for day in DATES:
        rows = [r for r in records if r['request'].get('day') == day]
        hours = [r['request']['hour'] for r in rows]
        good = [r for r in rows if r['status'] == 'RAW_POINT_QUOTES_VALID']
        complete = len(rows) == 4 and sorted(hours) == list(HOURS) and len(good) == 4
        result = dict(day=day, start_hour_utc=12, end_hour_utc=16, files_with_ticks=len(good),
                      all_four_files_valid=complete, calendar_certified=False,
                      price_scale=None, evaluation_eligible=False)
        if complete:
            ordered = sorted(good, key=lambda r: r['request']['hour'])
            for side in ('bid', 'ask'):
                values = [r['parsed'][side+'_ohlc_points'] for r in ordered]
                result[side+'_ohlc_points'] = [values[0][0], max(v[1] for v in values),
                                              min(v[2] for v in values), values[-1][3]]
            result['records'] = sum(r['parsed']['records'] for r in good)
            result['available_not_before_ms'] = ordered[-1]['parsed']['end_ms']
        summaries.append(result)
    return summaries


def audit(output, check, remaining=False):
    output = Path(output)
    run_id = REMAINING_RUN_ID if remaining else RUN_ID
    if output.resolve() != (OUTPUT_ROOT/'runs'/run_id/'artifacts/gold-history-audit').resolve():
        raise ValueError('One-shot gold audit RunId is fixed')
    if output.exists():
        raise FileExistsError('Gold source namespace already used; no blind retry')
    plan = request_plan()
    prior_records = []
    if remaining:
        parent = remaining_preflight()
        prior_records = [dict(request=plan['requests'][0], attempts=1, status='PARENT_SOCKET_TIMEOUT_NOT_RETRIED')]
        plan.update(requests=plan['requests'][1:], max_requests=18, max_runtime_sec=240,
                    total_response_bytes=18*CAP, fixed_run_id=run_id, parent=parent,
                    cumulative_requests_cap=19, cumulative_runtime_sec_cap=300)
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records = []
    def control():
        try:
            check()
        except TimeoutError as exc:
            raise AuditStopped(str(exc)) from exc

    for index, spec in enumerate(plan['requests'], 2 if remaining else 1):
        control()
        print(f'Gold source slot {index}/19: {spec["url"]}', flush=True)
        record = dict(request=spec, attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID')
        write_immutable(output/f'{index:02d}.attempt.json', record)
        request = urllib.request.Request(spec['url'], headers={'User-Agent': 'HistoricalValidation/1.0',
                                                               'Accept-Encoding': 'identity'})
        try:
            with opener.open(request, timeout=plan['timeout_sec']) as response:
                record['http_status'] = response.status
                if response.status != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Non-200 or encoded response')
                raw, body = read_bounded(response, control)
            record['body'] = body
            if not body['complete']:
                raise ValueError('Incomplete bounded response; no retry')
            path = output/f'{index:02d}.raw'
            with path.open('xb') as f:
                f.write(raw)
            record.update(raw_file=path.name, sha256=file_hash(path))
            if spec['kind'] == 'hour_ticks':
                parsed = inspect_hour(raw, spec['start_ms'], control)
            else:
                # A fetched current page cannot certify historical fees or holidays.
                parsed = dict(status='CURRENT_DOCUMENT_REQUIRES_REVIEW', historical_terms_verified=False,
                              calendar_certified=False, evaluation_eligible=False)
            record.update(status=parsed['status'], parsed=parsed)
        except urllib.error.HTTPError as exc:
            record.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
            exc.close()
        except (urllib.error.URLError, OSError, ValueError, lzma.LZMAError) as exc:
            if isinstance(exc, AuditStopped):
                raise
            record['error'] = str(exc)
            if isinstance(exc, TimeoutError):
                record.update(status='SOURCE_TIMEOUT_NO_RETRY', bytes_read_unknown=True, reserved_response_bytes=CAP)
        records.append(record)
        write_immutable(output/f'{index:02d}.receipt.json', record)
    result = dict(schema='gold_public_history_source_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan),
                  requests=len(records), records=records, prior_records=prior_records,
                  cumulative_requests=len(records)+len(prior_records),
                  four_hour_samples=four_hour_diagnostics(prior_records+records),
                  input_status='BLOCKED_DATA', evaluation_eligible=False, metrics=None,
                  missing_not_zero=True, price_scale_inferred=False, historical_calendar_inferred=False,
                  volume_treated_as_trades=False, source_not_execution_venue=True)
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
