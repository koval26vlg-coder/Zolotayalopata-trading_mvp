"""Read-only verification of offline pairing evidence and exact input/runtime bindings."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'trading_mvp/src'))
from channel_validation.contract import PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan
from channel_validation.gate_pairing import preflight, RUN_ID, MARKETS, PARENT_HASHES


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify_index(folder):
    items = read(folder/'evidence-index.json')['files']
    for item in items:
        path = (folder/item['file']).resolve()
        require(path.is_relative_to(folder.resolve()) and path.stat().st_size == item['bytes'] and
                file_hash(path) == item['sha256'], 'Evidence index mismatch: '+str(path))
    return len(items)


def verify():
    plan = validate_plan(read(PLAN_PATH))
    runtime = runtime_binding()
    rebind = read(HERE/'runtime-rebind.json')
    inputs = preflight()
    require(rebind['runtime_binding'] == runtime and rebind['runtime_hash'] == canonical_hash(runtime), 'Runtime drift')
    require(rebind['plan_hash'] == plan['plan_hash'] and rebind['plan_file_sha256'] == file_hash(PLAN_PATH), 'Plan drift')
    require(not rebind['research_contract_changed'] and not rebind['hypothesis_signal_cost_risk_acceptance_changed'], 'Research change')
    require(read(HERE/'local-input-plan.json') == dict(inputs, input_binding_hash=canonical_hash(inputs)), 'Input freeze drift')
    require(rebind['input_binding_hash'] == canonical_hash(inputs), 'Rebind inputs drift')
    tests = read(HERE/'tests.json')
    require(tests['tests'] == 213 and tests['successful'] and tests['errors'] == tests['failures'] == 0 and
            tests['runtime_binding'] == runtime and file_hash(HERE/'tests.json') == rebind['test_result_sha256'], 'Tests mismatch')
    for name, run_id in [('test-completion.json', 'history_verify_v18_20261009'), ('pairing-completion.json', RUN_ID)]:
        completed = read(HERE/name)
        require(completed['status'] == 'COMPLETE' and completed['exit_code'] == 0 and
                completed['runtime_hash'] == rebind['runtime_hash'] and completed['plan_hash'] == plan['plan_hash'] and
                completed['run_id'] == run_id, 'Incomplete/wrong run')
        run = HERE.parent/'runs'/run_id
        require(read(run/'completion.json') == completed, 'Completion copy mismatch')
        owner, dispatch, intent = (read(run/(n+'.json')) for n in ('owner', 'dispatch', 'intent'))
        require(owner['owner_pid'] == dispatch['terminal_pid'] and owner['job_assigned'] and
                owner['token'] == dispatch['token'] == intent['token'], 'Visible ownership mismatch')
        require(intent['runtime_hash'] == rebind['runtime_hash'] and intent['max_runtime_sec'] == 300, 'Intent drift')
    audit = read(HERE/'pairing-audit.json')
    require(audit['audit_hash'] == canonical_hash({k: v for k, v in audit.items() if k != 'audit_hash'}), 'Audit hash drift')
    require(audit['runtime_binding'] == runtime and audit['input_binding_hash'] == canonical_hash(inputs) and
            audit['plan_hash'] == plan['plan_hash'], 'Audit binding drift')
    require(audit['network_requests'] == 0 and not audit['eligible_for_evaluation'] and
            not audit['historical_observation_time_verified'] and audit['metrics'] is None and
            audit['source_order_preserved'], 'False execution/evaluation claim')
    require(read(HERE.parent/'runs'/RUN_ID/'artifacts/gate-pairing/audit.json') == audit, 'Audit copy mismatch')
    old_census = read(HERE.parent/'continuation-v17/local-census.json')
    expected = [('202301', 6360, 43), ('202501', 6336, 15)]
    require(len(audit['reports']) == 2, 'Pair count drift')
    totals = {}
    for report, (month, pairs, missing) in zip(audit['reports'], expected):
        require(report['month'] == month and report['paired_frames'] == pairs and report['missing_leg_frames'] == missing,
                'Pair accounting mismatch')
        require(report['state_change_frames'] == pairs+missing and not report['eligible_for_evaluation'] and
                report['freshness_acceptance_threshold_us'] is None and report['policy'] == inputs['policy'], 'Diagnostic contract drift')
        for market in MARKETS:
            source = report['sources'][market]
            parent = next(p for p in old_census['reports'] if p['input']['month'] == month and
                          p['input']['market'] == market and p['input']['kind'] == 'orderbooks_slice')
            require(source['gzip_crc_verified'] and source['decoded_sha256'] == parent['decoded_sha256'] and
                    source['decoded_bytes'] == parent['decoded_bytes'] and source['physical_lines'] == parent['physical_lines'],
                    'Source differs from completed parent census')
            require(sum(source['dispositions'].values())+source['blank_lines'] == source['physical_lines'], 'Lost source rows')
            for key, count in source['dispositions'].items():
                totals[key] = totals.get(key, 0)+count
            for kind in ('capture', 'exchange_update'):
                d = report['age_us'][market][kind]
                require(d['count'] == pairs and 0 <= d['min'] <= d['p50'] <= d['p95'] <= d['p99'] <= d['max'], 'Age summary invalid')
        require(report['ignored_events'] == sum(s['dispositions'].get('DUPLICATE_NOT_APPLIED', 0)+
                s['dispositions'].get('LATE_NOT_APPLIED', 0) for s in report['sources'].values()), 'Ignored events mismatch')
        for sample in report['samples']:
            require(not sample['eligible_for_evaluation'] and set(sample['legs']) == set(MARKETS), 'Unsafe sample')
            for leg in sample['legs'].values():
                at = sample['synthetic_frontier_us']
                require('available_at' not in leg and leg['event_time_us'] <= at and leg['exchange_update_us'] <= leg['event_time_us'] and
                        leg['capture_age_us'] == at-leg['event_time_us'] and leg['update_age_us'] == at-leg['exchange_update_us'], 'Future/invalid age')
    require(totals == dict(ACCEPTED=12753, DUPLICATE_NOT_APPLIED=354, LATE_NOT_APPLIED=130,
                          INVALID_RECORD_INVALIDATED=3, TIME_CONFLICT_INVALIDATED=13, UPDATE_REGRESSION_INVALIDATED=4), 'Disposition drift')
    matrix = read(HERE/'matrix.json')
    require(matrix['blocked_data_count'] == len(matrix['models']) == 20 and
            matrix['candidate_count'] == matrix['evaluated_model_count'] == matrix['rejected_count'] == 0, 'False model verdict')
    for model, row in zip(plan['models'], matrix['models']):
        require(model['id'] == row['id'] and model['model_hash'] == row['model_hash'] and
                row['metrics'] is None and row['input_status'] == 'BLOCKED_DATA', 'Changed model')
        for reference in row['evidence']:
            require((HERE/reference).is_file(), 'Missing referenced evidence: '+reference)
    require(read(HERE/'model-input-queue.json')['models'] == matrix['models'], 'Queue not reconciled')
    for item in read(HERE/'publication-provenance.json')['source_files']:
        require(file_hash(Path(item['path'])) == item['sha256'], 'Run provenance changed')
    require(read(HERE/'publication-provenance.json')['parent_evidence_index_sha256'] == PARENT_HASHES['evidence-index.json'], 'Parent index drift')
    return dict(status='VERIFIED', tests_passed=213, crc_verified_files=4, diagnostic_pairs=12696,
                missing_leg_frames=58, dispositions=totals, runtime_hash=rebind['runtime_hash'],
                network_requests=0, real_data_evaluation_run=False,
                parent_evidence_files_verified=verify_index(HERE.parent/'continuation-v17'),
                checkpoint_files_verified=verify_index(HERE) if (HERE/'evidence-index.json').exists() else 0)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
