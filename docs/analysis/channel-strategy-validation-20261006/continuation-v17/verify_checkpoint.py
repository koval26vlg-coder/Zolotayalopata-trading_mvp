"""Read-only checkpoint verification, with no legacy runtime execution."""
import json
import gzip
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'trading_mvp/src'))
from channel_validation.contract import PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan
from channel_validation.gate_paired_local import preflight, RUN_ID


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
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
    binding = read(HERE/'runtime-rebind.json')
    require(binding['plan_hash'] == plan['plan_hash'] and binding['plan_file_sha256'] == file_hash(PLAN_PATH), 'Plan changed')
    require(binding['runtime_binding'] == runtime_binding() and
            binding['runtime_hash'] == canonical_hash(runtime_binding()), 'Runtime changed')
    inputs = preflight()
    require(read(HERE/'local-input-plan.json') == dict(inputs, input_binding_hash=canonical_hash(inputs)), 'Local input drift')
    require(binding['input_binding_hash'] == canonical_hash(inputs), 'Rebind input mismatch')
    tests = read(HERE/'tests.json')
    require(tests['tests'] == 200 and tests['successful'] and tests['errors'] == tests['failures'] == 0 and
            tests['runtime_binding'] == runtime_binding(), 'Tests not passed on this runtime')
    require(file_hash(HERE/'tests.json') == binding['test_result_sha256'], 'Test bytes changed')
    for name in ('test-completion.json', 'local-completion.json'):
        c = read(HERE/name)
        require(c['status'] == 'COMPLETE' and c['exit_code'] == 0 and c['runtime_hash'] == binding['runtime_hash'] and
                c['plan_hash'] == plan['plan_hash'], 'Wrong or incomplete run')
    require(read(HERE/'local-completion.json')['run_id'] == RUN_ID, 'Wrong local run id')
    audit = read(HERE/'local-census.json')
    require(audit['audit_hash'] == canonical_hash({k: v for k, v in audit.items() if k != 'audit_hash'}), 'Audit content hash')
    require(audit['runtime_binding'] == runtime_binding() and audit['input_binding_hash'] == canonical_hash(inputs), 'Audit bindings')
    require(audit['network_requests'] == 0 and not audit['eligible_for_evaluation'] and audit['metrics'] is None, 'Unexpected evaluation')
    require(len(audit['reports']) == audit['full_file_crc_checks'] == 6, 'Wrong file count')
    require([r['input'] for r in audit['reports']] == inputs['inputs'], 'Wrong inputs scanned')
    for r in audit['reports']:
        require(r['gzip_crc_verified'] and r['decoded_bytes'] <= inputs['max_decoded_bytes_per_file'], 'Incomplete archive census')
        require(r['physical_lines'] == r['valid_rows']+r['invalid_rows']+r['blank_lines'], 'Line accounting mismatch')
        require(not r['eligible_for_evaluation'], 'Unsafe data eligibility')
        for sample in r['samples']:
            require(not sample['row']['eligible_for_evaluation'] and 'available_at' not in sample['row'], 'Invented causal observation time')
    require(sum(r['valid_rows'] for r in audit['reports']) == audit['total_valid_rows'] == 13440, 'Row count mismatch')
    require(sum(r['decoded_bytes'] for r in audit['reports']) == audit['total_decoded_bytes'] == 9868186, 'Decoded bytes mismatch')
    require(sum(r['duplicate_record_count'] for r in audit['reports']) == 354 and
            sum(r['time_reversal_count'] for r in audit['reports']) == 130 and
            sum(r['invalid_rows'] for r in audit['reports']) == 3, 'Anomaly counts mismatch')
    anomaly = read(HERE/'spot-anomaly-review.json')['server_errors']
    spec = next(x for x in inputs['inputs'] if x['market'] == 'spot' and x['month'] == anomaly['month'])
    matched = 0
    with gzip.open(spec['path'], 'rb') as stream:
        for line, raw in enumerate(stream, 1):
            if line in anomaly['lines']:
                require(json.loads(raw) == anomaly['content'], 'Server-error excerpt mismatch')
                matched += 1
            if line >= max(anomaly['lines']):
                break
    require(matched == 3, 'Missing bound anomaly lines')
    samples = read(HERE/'diagnostic-samples.json')
    require(samples['audit_hash'] == audit['audit_hash'] and samples['eligible_for_evaluation'] is False and
            samples['files'] == [dict(input=r['input'], samples=r['samples']) for r in audit['reports']], 'Sample binding mismatch')
    matrix = read(HERE/'matrix.json')
    require(len(matrix['models']) == matrix['blocked_data_count'] == 20 and
            matrix['evaluated_model_count'] == matrix['candidate_count'] == 0, 'False model verdicts')
    for row, model in zip(matrix['models'], plan['models']):
        require(row['id'] == model['id'] and row['model_hash'] == model['model_hash'] and row['metrics'] is None, 'Changed model')
    provenance = read(HERE/'publication-provenance.json')
    parent = HERE.parent/'continuation-v16'
    require(file_hash(parent/'evidence-index.json') == provenance['parent_evidence_index_sha256'], 'Parent changed')
    for item in provenance['source_files']:
        require(file_hash(Path(item['path'])) == item['sha256'], 'Visible run metadata changed')
    run = HERE.parent/'runs'/RUN_ID
    owner, dispatch = read(run/'owner.json'), read(run/'dispatch.json')
    require(owner['owner_pid'] == dispatch['terminal_pid'] and owner['token'] == dispatch['token'] and owner['job_assigned'], 'Owner mismatch')
    return dict(status='VERIFIED', tests_passed=200, valid_rows=13440, crc_verified_files=6,
                parent_evidence_files_verified=verify_index(parent),
                checkpoint_files_verified=verify_index(HERE) if (HERE/'evidence-index.json').exists() else 0,
                runtime_hash=binding['runtime_hash'], real_data_evaluation_run=False, network_requests=0)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
