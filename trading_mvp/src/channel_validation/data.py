from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from .contract import canonical_hash, file_hash

REQUIRED = {
    'bars_1m': ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'end_ts'),
    'bars_5m': ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'end_ts'),
    'bars_1h': ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'end_ts'),
    'bars_4h': ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'end_ts'),
    'bars_1d': ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'end_ts'),
    'books': ('bid', 'ask', 'bid_size', 'ask_size', 'bid_notional_top10', 'ask_notional_top10'),
    'tape': ('price', 'quantity', 'aggressor'),
    'funding': ('rate', 'period_seconds', 'settlement_ts'),
    'paired_quotes': ('long_ask', 'long_bid', 'short_ask', 'short_bid', 'long_size', 'short_size', 'long_venue', 'short_venue', 'long_market', 'short_market'),
    'inventory': ('venue', 'cash', 'base_quantity'),
    'option_chain': ('bid', 'ask', 'strike', 'expiry_ts', 'option_type', 'multiplier', 'settlement_currency', 'underlying', 'bid_size', 'ask_size'),
    'underlying_quotes': ('bid', 'ask'),
    'contract_specs': ('multiplier', 'price_currency', 'settlement_currency', 'instrument_type', 'fee_bps'),
    'pit_universe': ('members', 'window_end_ts', 'ranking_candidates', 'membership_complete', 'types_asof'),
    'pit_equity_universe': ('members', 'window_end_ts', 'ranking_candidates', 'membership_complete', 'types_asof'),
    'calendar': ('session_id', 'open_ts', 'close_ts', 'timezone'),
    'corporate_actions': ('adjustment_factor', 'effective_ts'),
    'lending_index': ('index', 'reserve', 'protocol', 'chain'),
    'gas': ('cost_usd', 'operation'),
    'token_quotes': ('bid', 'ask', 'chain', 'address'),
    'withdrawal_liquidity': ('withdrawable_usd', 'reserve', 'paused'),
    'dex_swaps': ('wallet', 'token', 'side', 'quote_usd', 'quantity', 'block_number', 'chain'),
    'token_universe': ('members', 'window_end_ts', 'ranking_candidates', 'membership_complete', 'types_asof'),
    'execution_quotes': ('bid', 'ask', 'bid_size', 'ask_size', 'block_number', 'sellable', 'token', 'gas_usd'),
}
INTERVALS = {'bars_1m': 60, 'bars_5m': 300, 'bars_1h': 3600, 'bars_4h': 14400, 'bars_1d': 86400}


def ts(value):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(value) or value < 0 or value > 4102444800:
            raise ValueError('Invalid epoch seconds (milliseconds not accepted)')
        return float(value)
    d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return d.timestamp()


def day(value):
    return datetime.fromtimestamp(ts(value), timezone.utc).date().isoformat()


def write_immutable(path, value):
    path = Path(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f'Immutable artifact differs: {path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.publish-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        # Hard-link publication is atomic and never replaces an existing artifact.
        os.link(name, path)
    finally:
        os.unlink(name)


def validate_row(row, kind):
    if not isinstance(row, dict) or kind not in REQUIRED:
        raise ValueError('Unknown normalized row kind')
    for key in ('ts', 'available_at', 'symbol', *REQUIRED[kind]):
        if key not in row:
            raise ValueError(f'{kind}: missing {key}')
    event = ts(row['ts'])
    available = ts(row['available_at'])
    if not isinstance(row['symbol'], str) or not row['symbol']:
        raise ValueError('Missing symbol')
    for value in row.values():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError('Nonfinite data')
    if kind in INTERVALS:
        if ts(row['end_ts']) != event + INTERVALS[kind] or available < ts(row['end_ts']):
            raise ValueError('Candle cannot be available before its close / wrong duration')
        o, h, l, c = [float(row[k]) for k in ('open', 'high', 'low', 'close')]
        if not 0 < l <= min(o, c) <= max(o, c) <= h or row['volume'] < 0 or row['quote_volume'] < 0:
            raise ValueError('Invalid OHLCV')
    elif kind not in ('calendar', 'contract_specs', 'corporate_actions') and available < event:
        raise ValueError('Observation published before it occurred')
    if 'bid' in row:
        if not 0 <= row['bid'] <= row['ask'] or row['ask'] <= 0:
            raise ValueError('Invalid/crossed quote')
    for key in ('bid_size', 'ask_size', 'quantity', 'cost_usd', 'gas_usd', 'fee_bps',
                'long_size', 'short_size', 'impact_per_unit', 'cash', 'base_quantity'):
        if key in row and (not isinstance(row[key], (int, float)) or row[key] < 0):
            raise ValueError(f'Invalid nonnegative field: {key}')
    if kind == 'paired_quotes':
        for leg in ('long', 'short'):
            if not 0 < row[leg+'_bid'] <= row[leg+'_ask']:
                raise ValueError('Invalid paired quote')
    if kind == 'tape' and (row['price'] <= 0 or row['aggressor'] not in ('buy', 'sell')):
        raise ValueError('Invalid trade tape')
    if kind.endswith('universe'):
        if ts(row['window_end_ts']) > event or not row['membership_complete'] or not row['types_asof']:
            raise ValueError('Unverified point-in-time universe / future ranking window')
        if len(set(row['members'])) != len(row['members']):
            raise ValueError('Duplicate universe member')
    if kind == 'option_chain' and (row['multiplier'] <= 0 or row['strike'] <= 0 or ts(row['expiry_ts']) <= event):
        raise ValueError('Invalid option contract')
    if kind == 'funding' and (row['period_seconds'] <= 0 or ts(row['settlement_ts']) < event):
        raise ValueError('Invalid funding timing')
    if kind == 'calendar' and ts(row['open_ts']) >= ts(row['close_ts']):
        raise ValueError('Invalid session')
    if kind == 'contract_specs' and row['multiplier'] <= 0:
        raise ValueError('Invalid multiplier')
    return row


def validate_manifest(manifest, base, max_bytes=2*1024**3, max_rows=2000000, check=lambda: None):
    if manifest.get('schema') != 'channel_input_v1' or manifest.get('status') != 'COMPLETE':
        raise ValueError('Input must be COMPLETE channel_input_v1, never a partial legacy run')
    if manifest.get('manifest_hash') != canonical_hash({k: v for k, v in manifest.items() if k != 'manifest_hash'}):
        raise ValueError('Manifest hash mismatch')
    base = Path(base).resolve()
    datasets = manifest.get('datasets')
    if not isinstance(datasets, list) or not datasets:
        raise ValueError('No datasets')
    seen = set()
    total_bytes = total_rows = 0
    loaded = []
    for entry in datasets:
        check()
        if entry['id'] in seen or entry['kind'] not in REQUIRED:
            raise ValueError('Duplicate dataset / unsupported schema')
        seen.add(entry['id'])
        path = (base / entry['path']).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError('Input path outside manifest namespace or unavailable')
        if entry.get('status') != 'COMPLETE' or entry.get('source_access') != 'PUBLIC':
            raise ValueError('Partial/private dataset not eligible')
        if entry.get('disposition') in ('REJECTED_INCOMPLETE', 'STOPPED_INCOMPLETE', 'CLOSED_NO_REOPEN'):
            raise ValueError('Forbidden legacy dataset')
        total_bytes += path.stat().st_size
        if total_bytes > max_bytes or file_hash(path) != entry['sha256']:
            raise ValueError('Input byte budget or hash mismatch')
        rows, previous = [], {}
        with path.open(encoding='utf-8-sig') as f:
            for line in f:
                check()
                if not line.strip():
                    continue
                r = validate_row(json.loads(line), entry['kind'])
                key = (r.get('venue', entry.get('market')), r['symbol'],
                       r.get('long_venue'), r.get('short_venue'), r.get('wallet'), r.get('sequence'))
                time = ts(r['ts'])
                if time <= previous.get(key, -1):
                    raise ValueError('Duplicate / out-of-order input')
                if entry['kind'] in INTERVALS and entry.get('market') == 'gate' and key in previous and time-previous[key] != INTERVALS[entry['kind']]:
                    raise ValueError('Internal crypto candle gap; missing bars are not flat prices')
                previous[key] = time
                rows.append(r)
                total_rows += 1
                if total_rows > max_rows:
                    raise ValueError('Input row budget exceeded')
        if not rows or len(rows) != entry['rows'] or file_hash(path) != entry['sha256']:
            raise ValueError('Empty/changed input or row count mismatch')
        loaded.append(dict(entry=entry, rows=rows))
    return loaded


def select_universe(snapshot, asof):
    validate_row(snapshot, 'pit_universe')
    if ts(snapshot['available_at']) > asof or ts(snapshot['window_end_ts']) > asof:
        raise ValueError('Universe not yet observable')
    candidates = snapshot['ranking_candidates']
    eligible = []
    for x in candidates:
        if ts(x['type_available_at']) > asof or ts(x['volume_window_end']) > asof:
            raise ValueError('Future universe evidence')
        if x['venue'] != 'gate' or x['quote'] != 'USDT' or not x['active_asof']:
            continue
        if x['asset_type'] != 'native' or len(x['daily_quote_turnover']) != 30:
            continue
        values = sorted(x['daily_quote_turnover'])
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError('Invalid lagged turnover')
        eligible.append((x['base'], (values[14]+values[15])/2))
    core = [s for s in ('BTC', 'ETH') if any(x[0] == s for x in eligible)]
    rest = sorted((x for x in eligible if x[0] not in core), key=lambda x: (-x[1], x[0]))[:8]
    selected = core + [x[0] for x in rest]
    if set(snapshot['members']) != set(selected):
        raise ValueError('Universe selection does not match frozen rank rule')
    return selected
