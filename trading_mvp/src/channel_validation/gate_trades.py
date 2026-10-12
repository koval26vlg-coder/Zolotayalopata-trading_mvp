"""Recover observed quote turnover from archived trades, including delisted pairs."""
import csv
from decimal import Decimal
import gzip
import io
from pathlib import Path
import ssl
import urllib.error
import urllib.request

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_catalog import checked_json
from .gate_history import CAP, number, read_bounded
from .gate_survivorship import PAIRS
from .sources import NoRedirect

PARENT = OUTPUT_ROOT/'runs/history_gate_survivorship_v3_20261006'
PARENT_HASH = 'cf2621ddc591e2ac3b1202779d392f2f79d336339416734bef72078e9fb7095f'


def csv_rows(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(32*1024**2+1)
    if len(decoded) > 32*1024**2:
        raise ValueError('Decompression budget exceeded')
    return csv.reader(io.StringIO(decoded.decode('utf-8-sig')))


def summarize_trades(raw, spec, check=lambda: None):
    hours, days, identifiers = {}, {}, set()
    count = 0
    first, last = None, None
    for row in csv_rows(raw):
        check()
        count += 1
        if count > 250000 or len(row) != 5:
            raise ValueError('Trade schema/row budget mismatch')
        at, ident, price, amount, side = map(number, row)
        if not spec['start'] <= at < spec['end'] or ident != int(ident) or ident <= 0 or side not in (1, 2):
            raise ValueError('Invalid trade timestamp/id/side')
        if price <= 0 or amount <= 0 or ident in identifiers:
            raise ValueError('Invalid/duplicate trade')
        identifiers.add(ident)
        first = at if first is None else min(first, at)
        last = at if last is None else max(last, at)
        for buckets, step in ((hours, 3600), (days, 86400)):
            key = int(at)//step*step
            bucket = buckets.setdefault(key, dict(base=Decimal(0), quote=Decimal(0), trades=0))
            bucket['base'] += amount
            bucket['quote'] += amount*price
            bucket['trades'] += 1
    if not count:
        raise ValueError('Empty trade archive')
    def export(buckets):
        return [dict(ts=t, base_volume=str(v['base']), quote_turnover=str(v['quote']), trades=v['trades'])
                for t, v in sorted(buckets.items())]
    return dict(rows=count, first=str(first), last=str(last), hours=export(hours), days=export(days),
                turnover_method='SUM_ARCHIVED_TRADE_PRICE_TIMES_AMOUNT',
                historical_completeness_certified=False,
                empty_buckets='NOT_FILLED_WITH_ZERO_WITHOUT_COMPLETENESS_EVIDENCE',
                evaluation_eligible=False)


def reconcile(trades, archive_raw, spec):
    candles = {int(row[0]): number(row[1]) for row in csv_rows(archive_raw)}
    hours = {row['ts']: number(row['base_volume']) for row in trades['hours']}
    shared = sorted(candles.keys() & hours.keys())
    mismatches = [at for at in shared if candles[at] != hours[at]]
    absent_both = sorted(set(range(spec['start'], spec['end'], 3600))-candles.keys()-hours.keys())
    return dict(shared_hours=len(shared), base_volume_matches=len(shared)-len(mismatches),
                volume_mismatch_hours=mismatches, candles_without_trades=sorted(candles.keys()-hours.keys()),
                trades_without_candles=sorted(hours.keys()-candles.keys()),
                hours_absent_from_both=len(absent_both),
                interpretation='Two archives may share missing data; consistency is not a completeness proof',
                historical_completeness_certified=False)


def audit(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('One-shot namespace already used')
    parent, parent_file_hash = checked_json(PARENT/'artifacts/gate-survivorship-audit/audit.json', 'audit_hash')
    complete, _ = checked_json(PARENT/'completion.json')
    if (parent['audit_hash'] != PARENT_HASH or complete['status'] != 'COMPLETE' or
            parent['plan_hash'] != build_plan()['plan_hash'] or complete['plan_hash'] != parent['plan_hash'] or
            complete['runtime_hash'] != canonical_hash(parent['runtime_binding'])):
        raise ValueError('Completed exact parent audit required')
    requests = []
    for base in PAIRS:
        record = next(r for r in parent['records'] if r['kind'] == 'hourly_archive' and r['base'] == base)
        if record.get('status') != 'ARCHIVE_SCHEMA_CHECKED':
            raise ValueError('No validated candle archive for comparison')
        path = PARENT/'artifacts/gate-survivorship-audit'/record['raw_file']
        if path.parent != PARENT/'artifacts/gate-survivorship-audit' or file_hash(path) != record['sha256']:
            raise ValueError('Parent candle binding mismatch')
        requests.append(dict(base=base, start=record['start'], end=record['end'],
                             candle_path=str(path), candle_sha256=record['sha256'],
                             url=f'https://download.gatedata.org/spot/deals/202608/{base}_USDT-202608.csv.gz'))
    plan = dict(requests=requests, parent_audit_file_sha256=parent_file_hash, parent_audit_hash=PARENT_HASH,
                max_requests=2, retries=0, per_response_bytes=CAP, total_response_bytes=2*CAP,
                max_runtime_sec=300, redirects=False, proxies=False, credentials=False,
                purpose='Diagnose delisted-asset turnover coverage; no PnL, signal or universe selection')
    write_immutable(output/'request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records = []
    for index, spec in enumerate(requests, 1):
        check()
        receipt = dict(**spec, attempts=1, status='SOURCE_UNAVAILABLE_OR_INVALID')
        print(f"Archived trade turnover {index}/2: {spec['base']}", flush=True)
        try:
            request = urllib.request.Request(spec['url'], headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
            with opener.open(request, timeout=15) as response:
                receipt['http_status'] = response.status
                raw, body = read_bounded(response, check)
            receipt['body'] = body
            if not body['complete']:
                raise ValueError('Partial source body')
            raw_path = output/f"{spec['base']}.csv.gz"
            with raw_path.open('xb') as stream:
                stream.write(raw)
            receipt.update(raw_file=raw_path.name, sha256=file_hash(raw_path))
            summary = summarize_trades(raw, spec, check)
            candle_path = Path(spec['candle_path'])
            candle_raw = candle_path.read_bytes()
            if file_hash(candle_path) != spec['candle_sha256']:
                raise ValueError('Candle source changed')
            receipt.update(summary=summary, reconciliation=reconcile(summary, candle_raw, spec),
                           status='OBSERVED_TURNOVER_RECONSTRUCTED_NOT_CERTIFIED')
        except urllib.error.HTTPError as exc:
            receipt.update(http_status=exc.code, error='HTTP_ERROR_NO_RETRY')
            exc.close()
        except (urllib.error.URLError, ValueError, OSError, EOFError, UnicodeError) as exc:
            if isinstance(exc, TimeoutError):
                raise
            receipt['error'] = str(exc)
        records.append(receipt)
        write_immutable(output/f'{index:02d}.receipt.json', receipt)
    result = dict(schema='gate_archived_trade_turnover_audit_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), request_plan_hash=canonical_hash(plan),
                  requests=2, records=records, evaluation_eligible=False, historical_universe_certified=False)
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
