"""Bounded full-CSV validation of the existing gold ZIP, never a trading input."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import heapq
from pathlib import Path
import zipfile

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_catalog import checked_json
from .histdata import ARCHIVE_RUN_ID, MEMBER, DECODE_CAP, quote
from .histdata_local import RAW_SHA, REPORT_MEMBER

RUN_ID = 'history_histdata_month_v9_20261007'
PARENT_AUDIT = 'e1b68af02fbf1edb374b97670f2f001c15cc304908d4b576199a687cfd851ba6'
PARENT_RUNTIME = '5dafb54946c2d79e42bae683b572e9c8240b02d1d8b67747d5875ed304b2cd5a'
CHUNK_ROWS = 100000
MAX_ROWS = 4000000


def preflight():
    parent = OUTPUT_ROOT/'continuation-v8'
    audit, audit_sha = checked_json(parent/'local-audit.json', 'audit_hash')
    complete, complete_sha = checked_json(parent/'local-completion.json')
    raw = OUTPUT_ROOT/'runs'/ARCHIVE_RUN_ID/'artifacts/histdata-sample/XAUUSD-202301.zip'
    if (audit['audit_hash'] != PARENT_AUDIT or complete['status'] != 'COMPLETE' or
            complete['exit_code'] != 0 or complete['runtime_hash'] != PARENT_RUNTIME or
            canonical_hash(audit['runtime_binding']) != PARENT_RUNTIME or
            audit['plan_hash'] != build_plan()['plan_hash'] or complete['plan_hash'] != audit['plan_hash'] or
            not audit['zip_crc_verified'] or audit['physical_csv_rows'] != 3609301 or
            audit['input_binding']['raw_file_sha256'] != RAW_SHA or file_hash(raw) != RAW_SHA or
            raw.stat().st_size != audit['input_binding']['raw_bytes']):
        raise ValueError('Exact completed prefix audit and unchanged ZIP required')
    binding = dict(parent_audit_hash=PARENT_AUDIT, parent_audit_file_sha256=audit_sha,
                   parent_completion_sha256=complete_sha, parent_runtime_hash=PARENT_RUNTIME,
                   raw_file_sha256=RAW_SHA, raw_bytes=raw.stat().st_size,
                   expected_rows=audit['physical_csv_rows'], expected_csv_bytes=audit['decoded_bytes'],
                   plan_hash=audit['plan_hash'], runtime_hash=canonical_hash(runtime_binding()),
                   chunk_rows=CHUNK_ROWS, max_rows=MAX_ROWS, max_decoded_bytes=DECODE_CAP,
                   max_runtime_sec=600, network_requests=0, evaluation_eligible=False)
    return raw, binding


def verify_chunks(chunks):
    rows, size, previous, last, binding = 0, 0, None, None, None
    for number, chunk in enumerate(chunks, 1):
        digest = canonical_hash({k: v for k, v in chunk.items() if k != 'chunk_hash'})
        if (chunk['chunk_hash'] != digest or chunk['sequence'] != number or
                chunk['previous_chunk_hash'] != previous or chunk['row_start'] != rows+1 or
                chunk['rows'] <= 0 or chunk['row_end'] != rows+chunk['rows'] or
                chunk['byte_start'] != size or chunk['byte_end'] <= size or
                chunk['first_ms'] > chunk['last_ms'] or
                (last is not None and chunk['first_ms'] < last) or
                (binding is not None and chunk['input_binding_hash'] != binding)):
            raise ValueError('Invalid, missing or reordered chunk evidence')
        rows, size, previous, last, binding = (chunk['row_end'], chunk['byte_end'], digest,
                                              chunk['last_ms'], chunk['input_binding_hash'])
    if not chunks:
        raise ValueError('Empty chunk evidence')
    return dict(rows=rows, bytes=size, last_chunk_hash=previous, input_binding_hash=binding)


def scan(path, expected_rows, *, chunk_rows=CHUNK_ROWS, max_decoded_bytes=DECODE_CAP,
         check=lambda: None, on_chunk=lambda chunk: None, binding_hash=None):
    if not 1 <= expected_rows <= MAX_ROWS or not 1 <= chunk_rows <= CHUNK_ROWS:
        raise ValueError('Bounded nonempty row and chunk counts required')
    check()
    binding_hash = binding_hash or canonical_hash({'synthetic_fixture': True})
    total_hash, chunk_digest = hashlib.sha256(), hashlib.sha256()
    chunks, largest = [], []
    days, hours, buckets = Counter(), set(), Counter()
    rows = decoded = equal = gaps = hour_gaps = day_gaps = 0
    first = previous = chunk_first = low_bid = high_bid = low_ask = high_ask = None
    chunk_start_row, chunk_start_byte = 1, 0

    def finish_chunk():
        nonlocal chunk_digest, chunk_first, chunk_start_row, chunk_start_byte
        item = dict(sequence=len(chunks)+1, row_start=chunk_start_row, row_end=rows,
                    rows=rows-chunk_start_row+1, byte_start=chunk_start_byte, byte_end=decoded,
                    first_ms=chunk_first, last_ms=previous, raw_chunk_sha256=chunk_digest.hexdigest(),
                    previous_chunk_hash=chunks[-1]['chunk_hash'] if chunks else None,
                    input_binding_hash=binding_hash)
        item['chunk_hash'] = canonical_hash(item)
        check()
        on_chunk(item)
        chunks.append(item)
        chunk_digest, chunk_first = hashlib.sha256(), None
        chunk_start_row, chunk_start_byte = rows+1, decoded
        check()

    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if (set(names) not in ({MEMBER}, {MEMBER, REPORT_MEMBER}) or len(names) != len(set(names)) or
                any(m.flag_bits & 1 or m.is_dir() or (m.external_attr >> 16) & 0o170000 == 0o120000 or
                    m.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for m in members) or
                sum(m.file_size for m in members) > max_decoded_bytes):
            raise ValueError('Archive members, codec or decompression budget invalid')
        member = archive.getinfo(MEMBER)
        with archive.open(member) as stream:
            while True:
                # Check the stop file in batches rather than millions of filesystem calls.
                if rows % 1000 == 0:
                    check()
                line = stream.readline(257)
                if not line:
                    break
                if len(line) > 256 or decoded+len(line) > max_decoded_bytes or rows >= expected_rows:
                    raise ValueError('CSV row count, line length or decoded budget exceeded')
                try:
                    at, bid, ask = quote(line)
                except (ValueError, ArithmeticError) as exc:
                    raise ValueError(f'Invalid quote at row {rows+1}: {exc}') from exc
                if previous is not None:
                    if at < previous:
                        raise ValueError(f'Time reversal at row {rows+1}, including chunk boundary')
                    delta = at-previous
                    equal += delta == 0
                    gaps += delta > 60000
                    hour_gaps += delta > 3600000
                    day_gaps += delta > 86400000
                    if delta > 60000:
                        heapq.heappush(largest, (delta, previous, at))
                        if len(largest) > 20:
                            heapq.heappop(largest)
                first = at if first is None else first
                chunk_first = at if chunk_first is None else chunk_first
                previous = at
                rows += 1
                decoded += len(line)
                total_hash.update(line)
                chunk_digest.update(line)
                days[at//86400000] += 1
                hours.add(at//3600000)
                buckets[at//14400000] += 1
                low_bid = bid if low_bid is None else min(low_bid, bid)
                high_bid = bid if high_bid is None else max(high_bid, bid)
                low_ask = ask if low_ask is None else min(low_ask, ask)
                high_ask = ask if high_ask is None else max(high_ask, ask)
                if rows-chunk_start_row+1 == chunk_rows:
                    finish_chunk()
        if decoded != member.file_size or rows != expected_rows:
            raise ValueError('Incomplete CSV: decoded length or expected row count mismatch')
        if rows >= chunk_start_row:
            finish_chunk()
        if REPORT_MEMBER in names:
            check()
            if archive.getinfo(REPORT_MEMBER).file_size > 1000000:
                raise ValueError('Auxiliary report budget exceeded')
            # Read through EOF for CRC; provider text is not calendar evidence.
            with archive.open(REPORT_MEMBER) as stream:
                while stream.read(65536):
                    check()
    check()
    chain = verify_chunks(chunks)
    if chain['rows'] != rows or chain['bytes'] != decoded:
        raise ValueError('Chunk chain does not cover full CSV')
    utc_days = {datetime.fromtimestamp(day*86400, timezone.utc).date().isoformat(): count
                for day, count in sorted(days.items())}
    return dict(validated_rows=rows, decoded_bytes=decoded, csv_sha256=total_hash.hexdigest(),
                first_ms=first, last_ms=previous, equal_time_ticks=equal,
                gaps_over_1m=gaps, gaps_over_1h=hour_gaps, gaps_over_24h=day_gaps,
                largest_gaps=[dict(duration_ms=d, before_ms=b, after_ms=a) for d, b, a in sorted(largest, reverse=True)],
                observed_utc_days=utc_days, observed_hour_buckets=len(hours),
                observed_four_hour_buckets=len(buckets),
                four_hour_row_counts={str(k*14400000): v for k, v in sorted(buckets.items())},
                bid_range=list(map(str, (low_bid, high_bid))), ask_range=list(map(str, (low_ask, high_ask))),
                chunk_count=len(chunks), chunk_chain=chain,
                zip_crc_verified=True, full_csv_quote_semantics_verified=True,
                timezone='FIXED_UTC_MINUS_05_NO_DST', calendar_certified=False,
                missing_gaps_filled=False, costs_verified=False, metrics=None, evaluation_eligible=False)


def audit(output, check):
    output = Path(output)
    if output.resolve() != (OUTPUT_ROOT/'runs'/RUN_ID/'artifacts/histdata-month').resolve() or output.exists():
        raise ValueError('Fresh fixed full-month namespace required; no renamed retry')
    path, binding = preflight()
    write_immutable(output/'input-binding.json', binding)
    bound = canonical_hash(binding)
    print(f'Offline full-month validation: {binding["expected_rows"]} rows, chunks of {CHUNK_ROWS}; no network', flush=True)

    def publish(chunk):
        write_immutable(output/'chunks'/f'{chunk["sequence"]:03d}.json', chunk)
        print(f'Validated {chunk["row_end"]}/{binding["expected_rows"]} rows; chunk {chunk["sequence"]} saved', flush=True)

    result = scan(path, binding['expected_rows'], check=check, on_chunk=publish, binding_hash=bound)
    check()
    if file_hash(path) != RAW_SHA or result['decoded_bytes'] != binding['expected_csv_bytes']:
        raise ValueError('Input changed or decoded CSV size differs from prior census')
    result.update(schema='histdata_full_month_audit_v1', input_binding=binding,
                  plan_hash=build_plan()['plan_hash'], runtime_binding=runtime_binding(), input_status='BLOCKED_DATA')
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
