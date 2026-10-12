"""Offline evidence binding, not an issuer of independent research certificates."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from .contract import canonical_hash, runtime_binding
from .data import ts

FILE_CAP = 1024 * 1024
TOTAL_CAP = 16 * FILE_CAP
REF_CAP = 64
IDENTITY_CAP = 10000
FIXED_BASES = {'gold_macd': 'commodity:gold', 'dax_orb': 'index:dax',
               'aave_lending': 'asset:usdc'}


def dataset_binding(selected):
    return canonical_hash(sorted((d['entry'] for d in selected), key=lambda e: e['id']))


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key in evidence/input manifest')
            result[key] = value
        return result

    def constant(value):
        raise ValueError('Nonfinite JSON value: '+value)

    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=constant)


def _text(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError('Missing/invalid evidence text')
    return value


def load_evidence(plan, model, selected, reference, base, check=lambda: None):
    check()
    binding = dict(plan_hash=plan['plan_hash'], model_hash=model['model_hash'],
                   runtime_hash=canonical_hash(runtime_binding()), dataset_binding_hash=dataset_binding(selected))
    receipt = dict(schema='channel_research_evidence_receipt_v1', **binding,
                   status='MISSING', bundle=None, files=[], identities=[], certificates=[],
                   independent_oos_certified=False, execution_certified=False,
                   identity_semantics_independently_certified=False)
    if reference is None:
        return dict(receipt, evidence_hash=canonical_hash(receipt))
    root = Path(base).resolve()
    files, raw_cache = {}, {}
    total = 0

    def read(ref):
        nonlocal total
        check()
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('Evidence reference needs exactly path and sha256')
        name = _text(ref['path'])
        digest = ref['sha256']
        relative = Path(name)
        if (relative.is_absolute() or PureWindowsPath(name).drive or ':' in name or '\\' in name
                or '..' in relative.parts or name != relative.as_posix()
                or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('Invalid evidence path/hash')
        path = (root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Evidence path escapes input namespace or is unavailable')
        if name in files:
            if files[name]['sha256'] != digest:
                raise ValueError('Conflicting hashes for evidence file')
            return raw_cache[name]
        if len(files) >= REF_CAP or path.stat().st_size > FILE_CAP:
            raise ValueError('Evidence resource budget exceeded')
        with path.open('rb') as stream:
            raw = stream.read(FILE_CAP+1)
        total += len(raw)
        if not raw or len(raw) > FILE_CAP or total > TOTAL_CAP:
            raise ValueError('Empty or oversized evidence')
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Evidence file hash mismatch')
        files[name] = dict(path=name, sha256=digest, bytes=len(raw))
        raw_cache[name] = raw
        return raw

    def proofs(refs):
        if not isinstance(refs, list) or not 1 <= len(refs) <= REF_CAP:
            raise ValueError('Evidence references required')
        if len({canonical_hash(r) for r in refs}) != len(refs):
            raise ValueError('Duplicate evidence reference')
        for ref in refs:
            read(ref)
        return copy.deepcopy(refs)

    bundle = strict_json(read(reference))
    if not isinstance(bundle, dict) or bundle.get('schema') != 'channel_research_evidence_v1':
        raise ValueError('Unknown research evidence schema')
    if any(bundle.get(k) != v for k, v in binding.items()):
        raise ValueError('Research evidence plan/model/runtime/dataset binding mismatch')
    identities = bundle.get('identities')
    certificates = bundle.get('certificates')
    if not isinstance(identities, list) or len(identities) > IDENTITY_CAP:
        raise ValueError('Invalid identity collection')
    if not isinstance(certificates, list) or len(certificates) > 2:
        raise ValueError('Invalid certificate collection')
    keys, intervals = {}, {}
    for row in identities:
        check()
        if not isinstance(row, dict):
            raise ValueError('Invalid identity row')
        symbol, base_id, key = (_text(row.get(k)) for k in ('symbol', 'economic_base_id', 'identity_key'))
        if not re.fullmatch('[a-z0-9]+:[a-z0-9][a-z0-9:._/-]*', base_id):
            raise ValueError('Economic base must be a canonical namespaced identifier')
        expected = FIXED_BASES.get(model['id'])
        if model['id'] in ('long_put', 'cash_put', 'put_spread'):
            if symbol not in ('BTC', 'ETH'):
                raise ValueError('Options replay identity must describe BTC/ETH underlying')
            expected = 'asset:'+symbol.lower()
        if expected and base_id != expected:
            raise ValueError('Identity conflicts with fixed model underlying')
        if key in keys and keys[key] != base_id:
            raise ValueError('One identity key cannot diversify into multiple economic bases')
        keys[key] = base_id
        start, end, available = (ts(row.get(k)) for k in ('valid_from', 'valid_to', 'available_at'))
        if not start < end or available >= end:
            raise ValueError('Invalid dated identity interval')
        intervals.setdefault(symbol, []).append((start, end))
        receipt['identities'].append(dict(symbol=symbol, economic_base_id=base_id, identity_key=key,
                                          valid_from=start, valid_to=end, available_at=available,
                                          evidence_refs=proofs(row.get('evidence_refs'))))
    for spans in intervals.values():
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError('Overlapping identity intervals')
    seen = set()
    for cert in certificates:
        check()
        if not isinstance(cert, dict):
            raise ValueError('Invalid certificate')
        kind = cert.get('kind')
        claims = {'exposure': 'UNSEEN_CERTIFIED', 'execution': 'EXECUTABLE_CERTIFIED'}
        if kind not in claims or kind in seen or cert.get('claim') != claims[kind]:
            raise ValueError('Unknown/duplicate certificate kind or claim')
        seen.add(kind)
        if cert.get('periods') != plan['periods']:
            raise ValueError('Certificate period scope mismatch')
        receipt['certificates'].append(dict(kind=kind, claim=cert['claim'], periods=copy.deepcopy(cert['periods']),
            reviewer=_text(cert.get('reviewer')), method=_text(cert.get('method')),
            evidence_refs=proofs(cert.get('evidence_refs')), status='BOUND_NOT_INDEPENDENTLY_CERTIFIED'))
    # Detect mutation during a read/check callback; validation is not a file lock.
    for name, record in files.items():
        check()
        path = (root/name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Evidence path changed during validation')
        with path.open('rb') as stream:
            raw = stream.read(FILE_CAP+1)
        if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('Evidence changed during validation')
    receipt.update(status='BOUND_NOT_INDEPENDENTLY_CERTIFIED', bundle=copy.deepcopy(reference),
                   files=sorted(files.values(), key=lambda r: r['path']))
    return dict(receipt, evidence_hash=canonical_hash(receipt))


def bind_replay(replay, evidence, check=lambda: None):
    if evidence.get('evidence_hash') != canonical_hash({k: v for k, v in evidence.items() if k != 'evidence_hash'}):
        raise ValueError('Research evidence receipt hash mismatch')
    by_symbol = {}
    for row in evidence['identities']:
        by_symbol.setdefault(row['symbol'], []).append(row)
    trades = []
    for trade in replay['trades']:
        check()
        entry, end = ts(trade['entry_ts']), ts(trade['exit_ts'])
        if end < entry:
            raise ValueError('Invalid trade interval')
        matches = [r for r in by_symbol.get(trade['symbol'], [])
                   if r['valid_from'] <= entry and r['available_at'] <= entry and end < r['valid_to']]
        if len(matches) > 1:
            raise ValueError('Ambiguous trade identity')
        # Never trust identities emitted by an adapter or guessed from a ticker.
        trades.append(dict(trade, economic_base_id=matches[0]['economic_base_id'] if matches else None,
                           identity_evidence_hash=evidence['evidence_hash'] if matches else None))
    return dict(replay, trades=trades)
