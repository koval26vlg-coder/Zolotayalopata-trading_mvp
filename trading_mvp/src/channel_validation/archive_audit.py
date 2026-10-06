"""Read-only archive discovery. Never reads price/PnL/OOS payloads."""
import json
import os
from pathlib import Path
import re

from .contract import build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable

ARCHIVE_ROOT = Path(r'E:\ZolotyayLopata-data\exports\trading-mvp')
SCOPES = ('universe', 'pit-universe-v2', 'normalized', 'daily', 'funding',
          'historical-basis', 'historical-basis-1h-v2', 'gate-spot-perp-v2')
EXCLUDED = ('listing_momentum', 'listing-momentum', 'evaluation', 'backtest', 'replay', 'oos', 'holdout')


def discover(root, check=lambda: None, max_files=20000, max_entries=40000):
    root = Path(root)
    result = dict(root=str(root), exists=root.is_dir(), inventory_complete=True, files=[],
                  omitted=[], visited_entries=0, data_payloads_read=False, evaluation_eligible=False)
    if not root.is_dir():
        result['inventory_complete'] = False
        result['reason'] = 'ARCHIVE_UNAVAILABLE'
        return result
    stack = [(root/name, 0) for name in reversed(SCOPES) if (root/name).is_dir()]
    while stack:
        check()
        directory, depth = stack.pop()
        if directory.is_symlink() or directory.is_junction():
            result['omitted'].append(dict(path=str(directory), reason='LINK_NOT_FOLLOWED'))
            continue
        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    check()
                    result['visited_entries'] += 1
                    if result['visited_entries'] > max_entries or len(result['files']) >= max_files:
                        result.update(inventory_complete=False, reason='INVENTORY_BUDGET')
                        return result
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    if any(token in relative.lower() for token in EXCLUDED):
                        continue
                    if entry.is_symlink() or path.is_junction():
                        result['omitted'].append(dict(path=relative, reason='LINK_NOT_FOLLOWED'))
                    elif entry.is_dir(follow_symlinks=False):
                        if depth < 5:
                            stack.append((path, depth+1))
                        else:
                            result['inventory_complete'] = False
                            result['omitted'].append(dict(path=relative, reason='DEPTH_BUDGET'))
                    elif entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        result['files'].append(dict(path=relative, bytes=stat.st_size, modified_ns=stat.st_mtime_ns,
                                                    content_verified=False))
        except OSError as exc:
            result['inventory_complete'] = False
            result['omitted'].append(dict(path=str(directory), reason=str(exc)))
    result['files'].sort(key=lambda r: r['path'])
    return result


def inspect_pit_state(path, check=lambda: None):
    """Inspect known universe metadata only, with before/after hash verification."""
    path = Path(path)
    if path.stat().st_size > 8*1024**2:
        raise ValueError('Universe metadata exceeds read budget')
    before = file_hash(path)
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('schema') != 'pit_universe_state_v1' or not isinstance(value.get('symbols'), dict):
        raise ValueError('Unexpected PIT metadata schema')
    kinds, times = {}, []
    for item in value['symbols'].values():
        check()
        row = item.get('row', {})
        key = str(row.get('exchange'))+':'+str(row.get('contract_type'))
        kinds[key] = kinds.get(key, 0)+1
        if row.get('snapshot_ts'):
            times.append(row['snapshot_ts'])
    if file_hash(path) != before:
        raise ValueError('Universe metadata changed during inspection')
    return dict(path=str(path), sha256=before, run_id=value.get('run_id'), schema=value['schema'],
                symbols=len(value['symbols']), instrument_counts=kinds,
                snapshot_first=min(times) if times else None, snapshot_last=max(times) if times else None,
                monthly_spot_membership_certified=False,
                reason='Forward instrument snapshots are not a complete 2023-2026 spot membership ledger')


def archive_audit(output, check, root=ARCHIVE_ROOT):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Archive audit namespace already exists')
    print(f'Read-only archive metadata inventory: {root}', flush=True)
    found = discover(root, check)
    counts = {}
    for row in found['files']:
        group = row['path'].split('/')[0]
        counts[group] = counts.get(group, 0)+1
    states = [row for row in found['files'] if row['path'].endswith('/universe_state.json')]
    metadata = []
    for row in ([states[0], states[-1]] if len(states) > 1 else states):
        check()
        metadata.append(inspect_pit_state(Path(root)/row['path'], check))
    result = dict(schema='historical_archive_discovery_v1', plan_hash=build_plan()['plan_hash'],
                  runtime_binding=runtime_binding(), discovery=found, files_by_scope=counts,
                  inspected_pit_metadata=metadata, scoped_directories=list(SCOPES),
                  excluded_names=list(EXCLUDED), trading_results_created=False,
                  eligibility='DISCOVERY_ONLY_NOT_VALIDATED_INPUT',
                  filename_years_not_coverage=sorted(set(y for r in found['files'] for y in re.findall(r'20(?:22|23|24|25|26)', r['path']))),
                  next_step='Validate hashes/status/schema/periods of selected complete sources before any normalization or replay')
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    print(json.dumps(dict(files=len(found['files']), scopes=counts, metadata_records=len(metadata))), flush=True)
    return result
