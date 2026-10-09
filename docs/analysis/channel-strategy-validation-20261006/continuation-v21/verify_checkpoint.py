"""Freeze/verify technical evidence only; never replay historical market data."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'trading_mvp/src'))
from channel_validation.contract import build_plan, canonical_hash, file_hash, runtime_binding, PLAN_PATH
from channel_validation.data import write_immutable

PARENT = HERE.parent/'continuation-v20'
FINAL = 'history_verify_v21_final_20261009'
RED = 'history_verify_v21_red_20261009'
CHANGED = {
    'trading_mvp/src/channel_validation/evidence.py',
    'trading_mvp/src/channel_validation/statistics.py',
    'trading_mvp/src/channel_validation/runner.py',
    'trading_mvp/tests/test_channel_validation.py',
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_index(directory):
    items = read(directory/'evidence-index.json')['files']
    names = {p.name for p in directory.iterdir() if p.is_file() and p.name != 'evidence-index.json'}
    require(len(items) == len(names) and {r['file'] for r in items} == names, 'Evidence inventory drift')
    for item in items:
        path = (directory/item['file']).resolve()
        require(path.parent == directory and file_hash(path) == item['sha256']
                and path.stat().st_size == item['bytes'], 'Evidence bytes drift: '+item['file'])


def run_receipt(prefix, expected_id, tests_count, failures):
    done, owner, dispatch, intent, tests = [read(HERE/(prefix+'-'+name+'.json'))
        for name in ('completion', 'owner', 'dispatch', 'intent', 'tests')]
    require(done['run_id'] == expected_id and intent['stage'] == 'verify'
            and intent['max_runtime_sec'] == 300 and not intent['input_manifest']
            and not intent['evaluation_path'], 'Wrong test scope')
    require(owner['job_assigned'] and dispatch['terminal_pid'] == owner['owner_pid']
            and dispatch['token'] == owner['token'] == intent['token'], 'Visible ownership mismatch')
    require(done['runtime_hash'] == intent['runtime_hash'] == canonical_hash(tests['runtime_binding'])
            and intent['runtime'] == tests['runtime_binding'], 'Test code binding mismatch')
    require(done['plan_hash'] == intent['plan_hash'] == build_plan()['plan_hash'], 'Test plan mismatch')
    require(tests['tests'] == tests_count and tests['failures'] == failures and tests['errors'] == 0
            and tests['successful'] == (failures == 0), 'Unexpected test result')
    require(done['status'] == ('COMPLETE' if failures == 0 else 'STOPPED_INCOMPLETE')
            and done['exit_code'] == (0 if failures == 0 else 1), 'Completion mismatch')
    if failures:
        require(len(tests['failure_details']) == 3 and all('EconomicConcentrationRegressionTests.' in f['test']
                for f in tests['failure_details']), 'RED failed for a different reason')
    return tests


def build():
    check_index(PARENT)
    old = read(PARENT/'publication-provenance.json')
    prior = read(HERE/'parent-verification.json')
    require(prior == read(PARENT/'verification.json'), 'Prior verified snapshot drift')
    current = runtime_binding()
    changed = {k for k in current.keys() | old['runtime_binding'].keys()
               if current.get(k) != old['runtime_binding'].get(k)}
    require(changed == CHANGED, 'Unexpected runtime change')
    require(file_hash(PLAN_PATH) == old['plan_file_sha256'] and build_plan()['plan_hash'] == old['plan_hash'],
            'Research contract changed')
    run_receipt('red', RED, 216, 3)
    final = run_receipt('final', FINAL, 242, 0)
    require(final['runtime_binding'] == current, 'Current code differs from final tested code')
    binding = dict(schema='channel_runtime_rebind_v21', parent_commit='a9b297849d275d6a00cb70141a9b0aeddec55d83',
        parent_index_sha256=file_hash(PARENT/'evidence-index.json'),
        parent_runtime_hash=canonical_hash(old['runtime_binding']), runtime_binding=current,
        runtime_hash=canonical_hash(current), plan_hash=build_plan()['plan_hash'], plan_file_sha256=file_hash(PLAN_PATH),
        changed_files=[dict(path=k, before=old['runtime_binding'].get(k), after=current.get(k)) for k in sorted(changed)],
        research_contract_unchanged=True, independent_certification_implemented=False,
        historical_evaluation_run=False, network_requests=0, financial_execution_authorized=False,
        test_run_id=FINAL, synthetic_tests=242, new_tests=29)
    binding['rebind_hash'] = canonical_hash(binding)
    parent_models = read(PARENT/'matrix.json')['models']
    rows = [dict(id=r['id'], number=r['number'], model_hash=r['model_hash'],
                 input_status=r['input_status'], strategy_verdict=r['strategy_verdict'], metrics=None,
                 protocol_status=r['protocol_status'], protocol_issues=r['protocol_issues'],
                 economic_base_binding='IMPLEMENTED_NOT_POPULATED_WITH_REAL_EVIDENCE',
                 certificate_reader='BOUND_NOT_INDEPENDENTLY_CERTIFIED',
                 independent_oos_certified=False, execution_certified=False) for r in parent_models]
    readiness = dict(schema='channel_technical_readiness_v21', rebind_hash=binding['rebind_hash'],
        plan_hash=binding['plan_hash'], runtime_hash=binding['runtime_hash'],
        model_count=20, blocked_data_count=20, evaluated_model_count=0, candidate_count=0, rejected_count=0,
        structural_conflict_count=6, models=rows,
        next_step='Implement source-specific verification of existing exposure/identity/execution evidence; '
                  'missing evidence stays blocked. Six contract conflicts require a separate substantive decision.',
        no_repeat_source_probes=True, no_contract_revision=True, no_schedules=True)
    readiness['readiness_hash'] = canonical_hash(readiness)
    verification = dict(status='VERIFIED', runtime_hash=binding['runtime_hash'], rebind_hash=binding['rebind_hash'],
        readiness_hash=readiness['readiness_hash'], synthetic_tests=242, failures=0, errors=0,
        expected_red_failures=3, visible_owner_verified=True, old_evidence_bytes_verified=True,
        historical_evaluation_run=False, research_contract_unchanged=True,
        independent_certification_implemented=False)
    return {'runtime-rebind.json': binding, 'readiness.json': readiness, 'verification.json': verification}


def freeze():
    for prefix, run in (('red', RED), ('final', FINAL)):
        origin = HERE.parent/'runs'/run
        for name in ('completion', 'owner', 'dispatch', 'intent', 'tests'):
            source = origin/('artifacts/tests.json' if name == 'tests' else name+'.json')
            target = HERE/(prefix+'-'+name+'.json')
            raw = source.read_bytes()
            if target.exists():
                require(target.read_bytes() == raw, 'Immutable test receipt differs')
            else:
                with target.open('xb') as stream:
                    stream.write(raw)
    for name, value in build().items():
        write_immutable(HERE/name, value)
    files = [dict(file=p.name, bytes=p.stat().st_size, sha256=file_hash(p))
             for p in sorted(HERE.iterdir()) if p.is_file() and p.name != 'evidence-index.json']
    write_immutable(HERE/'evidence-index.json', dict(files=files))


def verify():
    check_index(HERE)
    expected = build()
    for name, value in expected.items():
        require(read(HERE/name) == value, 'Checkpoint content drift: '+name)
    return expected['verification.json']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
    print(json.dumps(verify(), indent=2))
