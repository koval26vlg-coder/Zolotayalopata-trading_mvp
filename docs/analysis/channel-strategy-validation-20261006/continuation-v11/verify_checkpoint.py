"""Read-only provenance checks; no network, price scan, or trading evaluation."""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / 'trading_mvp' / 'src'))

from channel_validation.contract import (  # noqa: E402
    PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan,
)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_index(directory):
    index = read(directory / 'evidence-index.json')
    seen = set()
    for item in index['files']:
        path = (directory / item['file']).resolve()
        require(path.is_relative_to(directory.resolve()), 'Index path escaped directory')
        require(item['file'] not in seen, 'Duplicate index path')
        seen.add(item['file'])
        require(path.stat().st_size == item['bytes'], f'Size mismatch: {path}')
        require(file_hash(path) == item['sha256'], f'Hash mismatch: {path}')
    return len(seen)


def verify():
    plan = validate_plan(read(PLAN_PATH))
    binding = runtime_binding()
    runtime_hash = canonical_hash(binding)
    previous = HERE.parent / 'continuation-v10'
    prior_test_record = read(HERE.parent / 'continuation-v9' / 'verification.json')
    require(binding == prior_test_record['runtime_binding'], 'Frozen runtime changed')
    require(prior_test_record['successful'] and prior_test_record['tests'] == 180,
            'Historical test record mismatch')
    parent_index_files = verify_index(previous)
    provenance = read(HERE / 'publication-provenance.json')
    require(provenance['plan_hash'] == plan['plan_hash'], 'Plan binding mismatch')
    require(provenance['runtime_hash'] == runtime_hash, 'Runtime binding mismatch')
    for item in provenance['parent_files']:
        path = (ROOT / item['path']).resolve()
        require(path.is_relative_to(ROOT), 'Parent path escaped repository')
        require(path.stat().st_size == item['bytes'], f'Parent size mismatch: {path}')
        require(file_hash(path) == item['sha256'], f'Parent hash mismatch: {path}')

    old_queue = read(previous / 'model-input-queue.json')
    queue = read(HERE / 'model-input-queue.json')
    require(queue['plan_hash'] == plan['plan_hash'], 'Queue plan mismatch')
    require(len(queue['models']) == queue['model_count'] == 20, 'Incomplete queue')
    require(queue['next_priority'] == ['gap_continue', 'gap_fade'], 'Wrong next priority')
    by_id = {m['id']: m for m in plan['models']}
    require(len({m['id'] for m in queue['models']}) == 20, 'Duplicate model')
    old_by_id = {m['id']: m for m in old_queue['models']}
    for model in queue['models']:
        require(model['model_hash'] == by_id[model['id']]['model_hash'], 'Model binding mismatch')
        require(model['metrics'] is None and model['input_status'] == 'BLOCKED_DATA',
                'Unexpected trading result')
        old = old_by_id[model['id']]
        if model['id'] != 'dax_orb':
            require({k: v for k, v in model.items() if k != 'evidence'} ==
                    {k: v for k, v in old.items() if k != 'evidence'}, 'Unrelated model changed')
            require([(HERE / p).resolve() for p in model['evidence']] ==
                    [(previous / p).resolve() for p in old['evidence']], 'Evidence target changed')
        for relative in model['evidence']:
            require((HERE / relative).is_file(), f'Missing queue evidence: {relative}')

    sources = read(HERE / 'source-evidence.json')
    ids = {s['id'] for s in sources['sources']}
    require(len(ids) == len(sources['sources']), 'Duplicate source identifier')
    audit = read(HERE / 'suitability-audit.json')
    ready = read(HERE / 'data-readiness.json')
    require(audit['plan_hash'] == plan['plan_hash'], 'Audit plan mismatch')
    require(audit['runtime_hash'] == runtime_hash, 'Audit runtime mismatch')
    require(audit['model_hash'] == by_id['dax_orb']['model_hash'], 'Audit model mismatch')
    require(not audit['evaluation_allowed_now'] and not ready['backtest_executed'],
            'Audit must not imply a backtest')
    require(not ready['strategy_rejected'] and ready['metrics'] is None,
            'Data gap must not become a rejection')
    for item in audit['requirements']:
        require(set(item.get('evidence_ids', [])) <= ids, 'Unknown source reference')
    claim_absent = not (ROOT / 'docs/agent-log/active-market-data-writer-claim.json').exists()
    require(claim_absent, 'Writer claim present: obtain a fresh scoped gate before publication')
    if (HERE / 'evidence-index.json').exists():
        verify_index(HERE)
    return dict(schema='documentation_checkpoint_verification_v1', successful=True,
                plan_hash=plan['plan_hash'], runtime_hash=runtime_hash,
                runtime_binding_file_count=len(binding), frozen_models_verified=20,
                model_parameters_unchanged=True, other_model_queue_entries_unchanged=True,
                parent_index_files_verified=parent_index_files,
                parent_file_bindings_verified=len(provenance['parent_files']),
                all_queue_evidence_paths_exist=True, all_source_references_resolved=True,
                active_writer_claim_absent=claim_absent,
                runtime_binding_matches_prior_180_test_record=True,
                tests_rerun_this_checkpoint=False, historical_test_record='../continuation-v9/verification.json',
                raw_market_inputs_rescanned=False, market_data_downloads=0,
                evaluation_executed=False, source_evidence_is_analyst_summary_not_http_snapshot=True)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, sort_keys=True))
