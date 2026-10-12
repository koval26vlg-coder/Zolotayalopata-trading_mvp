"""One full public historical file, separate from the 1 MB source-probe contract."""
import hashlib
import os
from pathlib import Path
import shutil
import ssl
import time
import urllib.request

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_catalog import checked_json
from .okx_history import DAY, DAY_MS, CAP
from .okx_stream import census, MAX_SCAN_BYTES, SAMPLE_ROWS
from .sources import NoRedirect

PARENT = OUTPUT_ROOT/'runs/history_okx_option_source_v4_20261006'
PARENT_HASH = 'e24e6c13f9af96471f507f0f2b1194e973fa13b3d634dbe4a9cb55fd0315bd23'
MAX_DOWNLOAD = 300000000
LOCAL_SOURCE = OUTPUT_ROOT/'runs/history_okx_full_btc_v5_20261006'
LOCAL_SHA = 'aa58f77452e9e2a4aa180a18c22eca4b1b1fc48127ca7d829ef87306c41ae91c'
LOCAL_SCAN_BYTES = 32*1024**3


def acquisition_plan():
    parent, sha = checked_json(PARENT/'artifacts/okx-history-audit/audit.json', 'audit_hash')
    complete, _ = checked_json(PARENT/'completion.json')
    if (parent['audit_hash'] != PARENT_HASH or complete['status'] != 'COMPLETE' or
            parent['plan_hash'] != build_plan()['plan_hash'] or complete['plan_hash'] != parent['plan_hash'] or
            complete['runtime_hash'] != canonical_hash(parent['runtime_binding'])):
        raise ValueError('Completed bound source audit required')
    sample = next(r for r in parent['records'] if r.get('raw_file') == 'BTC-USD.tar.gz.prefix')
    prefix = PARENT/'artifacts/okx-history-audit'/sample['raw_file']
    if sample['status'] != 'PREFIX_ONLY_NOT_BACKTEST_INPUT' or file_hash(prefix) != sample['sha256']:
        raise ValueError('Original archive prefix binding changed')
    return dict(schema='okx_single_full_archive_acquisition_v1', plan_hash=build_plan()['plan_hash'],
                source_audit_hash=PARENT_HASH, source_audit_file_sha256=sha,
                url=sample['url'], expected_bytes=sample['range']['total_archive_bytes'],
                first_1000000_bytes_sha256=sample['sha256'], max_http_requests=1, max_download_bytes=MAX_DOWNLOAD,
                max_stream_decoded_bytes=MAX_SCAN_BYTES, max_output_bytes=MAX_DOWNLOAD+50000000,
                max_runtime_sec=1800, family='BTC-USD', day=DAY, sample_rows_per_contract=SAMPLE_ROWS,
                source_probe=False, full_file_acquisition=True, archive_retry=False, redirects=False,
                proxies=False, credentials=False, tar_extraction=False, evaluation_eligible=False,
                research_contract_changed=False)


def stream_download(response, target, expected_bytes, prefix_sha, check,
                    cap=MAX_DOWNLOAD, prefix_bytes=CAP):
    if (response.status != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity' or
            not prefix_bytes <= expected_bytes <= cap):
        raise ValueError('Full archive response/budget mismatch')
    declared = response.headers.get('Content-Length')
    if declared is not None and int(declared) != expected_bytes:
        raise ValueError('Archive size changed from bound catalog')
    partial = Path(str(target)+'.partial')
    digest, prefix = hashlib.sha256(), hashlib.sha256()
    total, last = 0, time.monotonic()
    with partial.open('xb') as stream:
        while True:
            check()
            block = response.read(min(1048576, cap-total))
            if not block:
                break
            if total < prefix_bytes:
                prefix.update(block[:prefix_bytes-total])
            stream.write(block)
            digest.update(block)
            old, total = total, total+len(block)
            if old < prefix_bytes <= total and prefix.hexdigest() != prefix_sha:
                raise ValueError('Archive prefix changed since the bound probe')
            if total > expected_bytes:
                raise ValueError('Archive length/download budget exceeded')
            if time.monotonic()-last >= 5:
                print(f'Download: {total}/{expected_bytes} bytes', flush=True)
                last = time.monotonic()
            if total == expected_bytes and declared is not None:
                break
            if total == cap:
                raise ValueError('No EOF evidence within download budget')
        stream.flush()
        os.fsync(stream.fileno())
    if total != expected_bytes:
        raise ValueError('Truncated full archive, retain .partial; no retry')
    # Atomic publication without replacing a complete artifact.
    os.link(partial, target)
    partial.unlink()
    return dict(bytes=total, sha256=digest.hexdigest(), prefix_sha256=prefix.hexdigest(),
                complete=True, http_status=response.status)


def acquire(output, check):
    output = Path(output)
    if output.resolve() != (LOCAL_SOURCE/'artifacts/okx-full-archive').resolve():
        raise ValueError('One-shot download is bound to its original run namespace; no renamed retry')
    if output.exists():
        raise FileExistsError('One-shot acquisition namespace already used')
    plan = acquisition_plan()
    if shutil.disk_usage(OUTPUT_ROOT).free < 2*1024**3:
        raise ValueError('At least 2 GiB free space required')
    write_immutable(output/'acquisition-plan.json', dict(**plan, acquisition_hash=canonical_hash(plan),
                                                       runtime_binding=runtime_binding()))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(plan['url'], headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
    path = output/'BTC-USD-2025-01-06.tar.gz'
    print(f'One full historical file: {plan["expected_bytes"]} bytes; no retries, no evaluation', flush=True)
    check()
    with opener.open(request, timeout=30) as response:
        receipt = stream_download(response, path, plan['expected_bytes'], plan['first_1000000_bytes_sha256'], check)
    write_immutable(output/'download-receipt.json', dict(**receipt, url=plan['url'], acquisition_hash=canonical_hash(plan)))
    result = census(path, DAY, DAY_MS, check=check)
    if result['compressed_sha256'] != receipt['sha256']:
        raise ValueError('Archive changed between download and parsing')
    result.update(plan_hash=build_plan()['plan_hash'], runtime_binding=runtime_binding(),
                  acquisition_hash=canonical_hash(plan), input_file=path.name, input_sha256=receipt['sha256'])
    result['census_hash'] = canonical_hash(result)
    write_immutable(output/'census.json', result)
    return result


def local_census_plan(source=LOCAL_SOURCE):
    source = Path(source)
    root = source/'artifacts/okx-full-archive'
    receipt, receipt_sha = checked_json(root/'download-receipt.json')
    complete, complete_sha = checked_json(source/'completion.json')
    failure, _ = checked_json(source/'failure.json')
    acquisition, _ = checked_json(root/'acquisition-plan.json')
    expected = acquisition_plan()
    bound = dict(acquisition)
    binding = bound.pop('runtime_binding')
    acquisition_hash = bound.pop('acquisition_hash')
    if (bound != expected or canonical_hash(bound) != acquisition_hash or
            complete['runtime_hash'] != canonical_hash(binding) or
            complete['plan_hash'] != expected['plan_hash'] or
            complete['status'] != 'STOPPED_INCOMPLETE' or
            failure['error'] != 'Decoded stream budget exceeded' or
            receipt['acquisition_hash'] != acquisition_hash or receipt['complete'] is not True or
            receipt['bytes'] != expected['expected_bytes'] or receipt['sha256'] != LOCAL_SHA):
        raise ValueError('Only the complete download subartifact of this bounded scan is reusable')
    path = root/'BTC-USD-2025-01-06.tar.gz'
    if path.stat().st_size != receipt['bytes'] or file_hash(path) != LOCAL_SHA:
        raise ValueError('Complete local archive hash mismatch')
    return dict(schema='okx_local_complete_archive_census_v1', input_file=str(path.resolve()),
                input_sha256=LOCAL_SHA, source_completion_file_sha256=complete_sha,
                download_receipt_file_sha256=receipt_sha, acquisition_hash=acquisition_hash,
                plan_hash=expected['plan_hash'], max_http_requests=0, archive_retry=False,
                max_stream_decoded_bytes=LOCAL_SCAN_BYTES, max_runtime_sec=1800,
                max_output_bytes=50000000, sample_rows_per_contract=SAMPLE_ROWS,
                research_contract_changed=False, trading_eligible=False)


def local_census(output, check):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Local census namespace already used')
    check()
    plan = local_census_plan()
    write_immutable(output/'local-plan.json', dict(**plan, local_plan_hash=canonical_hash(plan),
                                                runtime_binding=runtime_binding()))
    result = census(plan['input_file'], DAY, DAY_MS, check=check, scan_limit=LOCAL_SCAN_BYTES)
    if result['compressed_sha256'] != LOCAL_SHA:
        raise ValueError('Archive changed during local stream parsing')
    result.update(plan_hash=plan['plan_hash'], runtime_binding=runtime_binding(),
                  local_plan_hash=canonical_hash(plan), input_sha256=LOCAL_SHA,
                  network_requests=0, source_run_status_preserved='STOPPED_INCOMPLETE')
    result['census_hash'] = canonical_hash(result)
    write_immutable(output/'census.json', result)
    return result
