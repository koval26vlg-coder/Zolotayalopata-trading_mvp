"""Bounded complete-container validation and explicitly sampled option book census."""
from datetime import date
import gzip
import hashlib
import json
from pathlib import PurePosixPath
import re

from .gate_history import number
from .gate_metadata import unique_keys

CHUNK = 65536
MAX_SCAN_BYTES = 8*1024**3
MAX_LINE_BYTES = 1024**2
SAMPLE_ROWS = 200


def contract_id(symbol, family='BTC-USD'):
    match = re.fullmatch(re.escape(family)+r'-(\d{6})-(\d+(?:\.\d+)?)-([CP])', symbol)
    if not match or number(match[2]) <= 0:
        raise ValueError('Invalid option instrument')
    expiry = date.fromisoformat('20'+match[1][:2]+'-'+match[1][2:4]+'-'+match[1][4:])
    return dict(symbol=symbol, family=family, expiry_date=expiry.isoformat(),
                strike=match[2], option_type=match[3], expiry_time_verified=False,
                multiplier=None, premium_currency=None, settlement_currency=None)


class Book:
    def __init__(self, symbol, start_ms, end_ms):
        self.symbol, self.start, self.end = symbol, start_ms, end_ms
        self.sides = {'bids': {}, 'asks': {}}
        self.timestamp = None
        self.sequence = None
        self.sequence_complete = True
        self.rows = 0

    def apply(self, record):
        if not isinstance(record, dict) or record.get('instId') != self.symbol:
            raise ValueError('Wrong book instrument')
        stamp = number(record.get('ts'))
        if stamp != int(stamp) or not self.start <= stamp < self.end:
            raise ValueError('Book timestamp outside UTC day')
        if self.timestamp is not None and stamp < self.timestamp:
            raise ValueError('Out-of-order book timestamp')
        action = record.get('action')
        if action not in ('snapshot', 'update') or (self.rows == 0 and action != 'snapshot'):
            raise ValueError('Snapshot must precede updates')
        changes = {}
        for side in self.sides:
            levels = record.get(side)
            if not isinstance(levels, list) or len(levels) > 5000:
                raise ValueError('Missing/oversized book side')
            changes[side] = {}
            for row in levels:
                if not isinstance(row, list) or len(row) != 3:
                    raise ValueError('Expected price, quantity, order count')
                price, quantity, orders = map(number, row)
                if (price <= 0 or quantity < 0 or orders < 0 or orders != int(orders) or
                        (quantity > 0 and orders == 0) or price in changes[side]):
                    raise ValueError('Invalid/duplicate book level')
                changes[side][price] = quantity
        sequence = record.get('seqId')
        if sequence is None:
            self.sequence_complete = False
        else:
            sequence = number(sequence)
            if sequence != int(sequence) or sequence < 0:
                raise ValueError('Invalid sequence id')
            if action == 'update':
                previous = number(record.get('prevSeqId'))
                if self.sequence is None or previous != self.sequence or sequence < previous:
                    raise ValueError('Book sequence gap')
                if sequence == previous and any(changes.values()):
                    raise ValueError('Sequence did not advance for changed book')
        if action == 'snapshot':
            self.sides = {'bids': {}, 'asks': {}}
        for side, levels in changes.items():
            for price, quantity in levels.items():
                if quantity == 0:
                    self.sides[side].pop(price, None)
                else:
                    self.sides[side][price] = quantity
            if len(self.sides[side]) > 5000:
                raise ValueError('Reconstructed book exceeds level budget')
        self.timestamp, self.sequence = int(stamp), sequence
        self.rows += 1
        bid = max(self.sides['bids'], default=None)
        ask = min(self.sides['asks'], default=None)
        status = 'EMPTY_SIDE' if bid is None or ask is None else ('CROSSED_OR_LOCKED' if bid >= ask else 'TWO_SIDED_UNCROSSED')
        return dict(ts_ms=self.timestamp, status=status, bid=str(bid) if bid is not None else None,
                    ask=str(ask) if ask is not None else None,
                    bid_size=str(self.sides['bids'][bid]) if bid is not None else None,
                    ask_size=str(self.sides['asks'][ask]) if ask is not None else None,
                    available_at=None, historical_units_verified=False)


class DecodedStream:
    def __init__(self, stream, check, limit):
        self.stream, self.check, self.limit = stream, check, limit
        self.count = 0
        self.hash = hashlib.sha256()

    def read(self, count):
        self.check()
        if count < 0 or count > CHUNK or self.count+count > self.limit:
            raise ValueError('Decoded stream budget exceeded')
        raw = self.stream.read(count)
        self.count += len(raw)
        self.hash.update(raw)
        return raw

    def exact(self, count):
        raw = self.read(count)
        if len(raw) != count:
            raise ValueError('Truncated TAR structure')
        return raw


class HashedInput:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()

    def read(self, count=-1):
        if count < 0:
            raise ValueError('Unbounded compressed read prohibited')
        raw = self.stream.read(count)
        self.hash.update(raw)
        return raw


def tar_header(raw):
    checksum = int(raw[148:156].rstrip(b'\0 ').strip() or b'0', 8)
    if sum(raw[:148])+8*32+sum(raw[156:]) != checksum:
        raise ValueError('TAR checksum mismatch')
    name = raw[:100].split(b'\0')[0].decode('utf-8')
    prefix = raw[345:500].split(b'\0')[0].decode('utf-8')
    if prefix:
        name = prefix+'/'+name
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or len(path.parts) != 1:
        raise ValueError('Unsafe/non-flat TAR path')
    if raw[156:157] not in (b'0', b'\0'):
        raise ValueError('Only regular option files accepted; no links or TAR extensions')
    size = int(raw[124:136].rstrip(b'\0 ').strip() or b'0', 8)
    if size <= 0:
        raise ValueError('Empty/invalid TAR member')
    return name, size


def sample_member(stream, size, book, sample_rows):
    remaining, buffer = size, b''
    counts = {'EMPTY_SIDE': 0, 'CROSSED_OR_LOCKED': 0, 'TWO_SIDED_UNCROSSED': 0}
    first, first_two_sided, error = None, None, None
    while remaining:
        block = stream.exact(min(CHUNK, remaining))
        remaining -= len(block)
        if error or book.rows >= sample_rows:
            continue
        buffer += block
        while b'\n' in buffer or (remaining == 0 and buffer):
            line, sep, rest = buffer.partition(b'\n')
            buffer = rest if sep else b''
            try:
                if len(line) > MAX_LINE_BYTES or not line:
                    raise ValueError('Empty/oversized JSON line')
                quote = book.apply(json.loads(line, object_pairs_hook=unique_keys))
                counts[quote['status']] += 1
                first = first or quote
                if quote['status'] == 'TWO_SIDED_UNCROSSED':
                    first_two_sided = first_two_sided or quote
            except (ValueError, TypeError, KeyError) as exc:
                error = str(exc)
                break
            if book.rows >= sample_rows:
                buffer = b''
                break
        if len(buffer) > MAX_LINE_BYTES:
            error, buffer = 'Oversized JSON line', b''
    padding = (-size) % 512
    if padding and stream.exact(padding) != bytes(padding):
        raise ValueError('Nonzero TAR member padding')
    return dict(sample_status='INVALID_BOOK_SAMPLE' if error else 'BOOK_PREFIX_CHECKED', error=error,
                sampled_rows=book.rows, sample_limit=sample_rows, first_quote=first,
                first_two_sided_uncrossed=first_two_sided, quote_status_counts=counts,
                sampled_sequence_verified=bool(book.rows and book.sequence_complete and not error),
                entire_member_book_validated=False, trading_eligible=False)


def census(path, day, start_ms, family='BTC-USD', check=lambda: None,
           scan_limit=MAX_SCAN_BYTES, sample_rows=SAMPLE_ROWS):
    if not 1 <= sample_rows <= 2000:
        raise ValueError('Invalid book sample budget')
    with open(path, 'rb') as source:
        hashed = HashedInput(source)
        with gzip.GzipFile(fileobj=hashed, mode='rb') as compressed:
            return _scan_tar(compressed, hashed, day, start_ms, family, check, scan_limit, sample_rows)


def _scan_tar(compressed, hashed, day, start_ms, family, check, scan_limit, sample_rows):
    seen, members = set(), []
    suffix = '-L2orderbook-400lv-'+day+'.data'
    stream = DecodedStream(compressed, check, scan_limit)
    while True:
        header = stream.exact(512)
        if header == bytes(512):
            if stream.exact(512) != bytes(512):
                raise ValueError('Two TAR EOF blocks required')
            # Drain to gzip EOF: validates CRC/ISIZE, not just the TAR terminator.
            while True:
                tail = stream.read(CHUNK)
                if not tail:
                    break
                if any(tail):
                    raise ValueError('Unexpected data after TAR EOF')
            break
        name, size = tar_header(header)
        if name in seen or not name.endswith(suffix) or len(seen) >= 2000:
            raise ValueError('Duplicate/wrong-date member or member budget exceeded')
        seen.add(name)
        contract = contract_id(name[:-len(suffix)], family)
        book = Book(contract['symbol'], start_ms, start_ms+86400000)
        sample = sample_member(stream, size, book, sample_rows)
        members.append(dict(name=name, raw_member_bytes=size, contract=contract, **sample))
        if len(members) % 25 == 0:
            print(f'Archive scan: {len(members)} contracts, {stream.count//1048576} MiB decoded', flush=True)
    if not members:
        raise ValueError('No option contracts in archive')
    return dict(schema='okx_complete_container_sampled_books_v1', container_complete=True,
                gzip_crc_checked=True, tar_eof_checked=True, decompressed_bytes=stream.count,
                compressed_sha256=hashed.hash.hexdigest(),
                decompressed_sha256=stream.hash.hexdigest(), members=members,
                contract_count=len(members), put_count=sum(m['contract']['option_type'] == 'P' for m in members),
                sampled_rows=sum(m['sampled_rows'] for m in members),
                invalid_book_samples=sum(m['error'] is not None for m in members),
                historical_specs_verified=False, entire_day_books_validated=False,
                exchange_completeness_certified=False, evaluation_eligible=False)
