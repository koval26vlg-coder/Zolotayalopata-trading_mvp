"""Read-only verification of this checkpoint; no network or strategy evaluation."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'trading_mvp/src'))
from channel_validation.contract import PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan
from channel_validation.gate_paired import request_plan, RUN_ID


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_index(folder):
    entries = read(folder/'evidence-index.json')['files']
    for entry in entries:
        path = (folder/entry['file']).resolve()
        require(path.is_relative_to(folder.resolve()), 'Unsafe index path')
        require(path.stat().st_size == entry['bytes'] and file_hash(path) == entry['sha256'],
                'Changed checkpoint evidence: '+str(path))
    return len(entries)


def verify():
    plan = validate_plan(read(PLAN_PATH))
    binding = read(HERE/'runtime-rebind.json')
    require(binding['plan_hash'] == plan['plan_hash'] and
            binding['plan_file_sha256'] == file_hash(PLAN_PATH), 'Frozen plan changed')
    require(binding['runtime_binding'] == runtime_binding() and
            binding['runtime_hash'] == canonical_hash(runtime_binding()), 'Changed runtime')
    require(not binding['research_contract_changed'], 'Unexpected research contract change')
    require(binding['request_plan_hash'] == canonical_hash(request_plan()), 'Request plan changed')
    require(read(HERE/'probe-plan.json') == dict(request_plan(), request_plan_hash=canonical_hash(request_plan())),
            'Frozen request file differs')
    tests = read(HERE/'tests.json')
    require(tests['successful'] and tests['failures'] == tests['errors'] == 0 and tests['tests'] == 191,
            'Test suite did not pass')
    require(tests['runtime_binding'] == binding['runtime_binding'] and
            file_hash(HERE/'tests.json') == binding['test_result_sha256'], 'Test evidence mismatch')
    for name in ('test-completion.json', 'probe-completion.json'):
        completion = read(HERE/name)
        require(completion['status'] == 'COMPLETE' and completion['exit_code'] == 0 and
                completion['runtime_hash'] == binding['runtime_hash'], 'Run did not finish with bound code')
    require(read(HERE/'probe-completion.json')['run_id'] == RUN_ID, 'Wrong probe run')
    audit = read(HERE/'gate-paired-audit.json')
    require(audit['audit_hash'] == canonical_hash({k: v for k, v in audit.items() if k != 'audit_hash'}),
            'Probe audit hash mismatch')
    require(audit['request_plan_hash'] == binding['request_plan_hash'], 'Wrong request binding')
    require(len(audit['records']) == audit['requests_attempted'] == 10, 'Unexpected request count')
    require([r['url'] for r in audit['records']] == [r['url'] for r in request_plan()['requests']], 'URL mismatch')
    source = HERE.parent/'runs'/RUN_ID/'artifacts/gate-paired-audit'
    for r in audit['records']:
        require(r['attempts'] == 1 and not r['eligible_for_evaluation'] and
                r['body']['bytes_read'] <= 1000000, 'Unsafe archive disposition')
        if r.get('raw_file'):
            path = (source/r['raw_file']).resolve()
            require(path.is_relative_to(source.resolve()) and file_hash(path) == r['raw_sha256'] and
                    path.stat().st_size == r['body']['bytes_read'], 'Downloaded archive changed')
    require(audit['bytes_read'] == sum(r['body']['bytes_read'] for r in audit['records']) <= 10000000,
            'Response budget mismatch')
    matrix = read(HERE/'matrix.json')
    require(len(matrix['models']) == matrix['blocked_data_count'] == 20 and
            matrix['evaluated_model_count'] == matrix['candidate_count'] == 0, 'False strategy verdict')
    for row, model in zip(matrix['models'], plan['models']):
        require(row['id'] == model['id'] and row['model_hash'] == model['model_hash'] and row['metrics'] is None,
                'Changed model or fabricated metrics')
        if 7 <= row['number'] <= 10:
            require('pit_universe' in row['required_kinds'], 'Paired PIT requirement missing')
    provenance = read(HERE/'publication-provenance.json')
    for entry in provenance['source_files']:
        require(file_hash(Path(entry['path'])) == entry['sha256'], 'Visible run evidence changed')
    owner = read(source.parents[1]/'owner.json')
    dispatch = read(source.parents[1]/'dispatch.json')
    require(owner['owner_pid'] == dispatch['terminal_pid'] and owner['token'] == dispatch['token'] and
            owner['job_assigned'], 'Visible owner binding mismatch')
    parent = HERE.parent/'continuation-v15'
    require(file_hash(parent/'evidence-index.json') == provenance['parent_evidence_index_sha256'], 'Parent index changed')
    parent_count = verify_index(parent)
    count = verify_index(HERE) if (HERE/'evidence-index.json').exists() else 0
    return dict(status='VERIFIED', runtime_hash=binding['runtime_hash'], tests_passed=191,
                parent_evidence_files_verified=parent_count, checkpoint_files_verified=count,
                requests=10, bytes_read=audit['bytes_read'], eligible_models=0,
                real_data_evaluation_run=False, network=False)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
