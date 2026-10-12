"""Verify the protocol audit, visible completion, bindings and complete evidence index."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audit_protocol import ROOT, build, file_hash, read, require


def verify(check_index=True):
    expected = build()
    for name, value in expected.items():
        require(read(HERE/name) == value, 'Audit content drift: '+name)
    dispatch, owner, done = [read(HERE/name) for name in ('audit-dispatch.json', 'audit-owner.json', 'audit-completion.json')]
    require(dispatch['window_style'] == 'Normal' and dispatch['no_exit'] and
            dispatch['terminal_pid'] == owner['owner_pid'] == done['owner_pid'], 'Visible owner mismatch')
    require(dispatch['script_sha256'] == file_hash(HERE/'run_audit_visible.ps1') and
            not dispatch['earlier_worker_started'], 'Launcher provenance mismatch')
    require(done['status'] == 'COMPLETE' and done['exit_code'] == 0 and
            done['max_runtime_sec'] == owner['max_runtime_sec'] == 120 and
            done['market_evaluation_run'] is False and owner['network_allowed'] is False, 'Incomplete/incorrect run')
    matrix, queue = expected['matrix.json'], expected['model-input-queue.json']
    require(matrix['models'] == queue['models'] and matrix['blocked_data_count'] == 20 and
            matrix['candidate_count'] == matrix['evaluated_model_count'] == matrix['rejected_count'] == 0,
            'False historical result')
    for row in matrix['models']:
        require(row['metrics'] is None, 'Invented market metrics')
        for ref in row['evidence']:
            path = (HERE/ref).resolve()
            require(path.is_relative_to(HERE.parent.resolve()) and path.is_file(), 'Missing referenced evidence')
    require(expected['decision-proposal.json']['activated'] is False, 'Unauthorized contract revision')
    result = dict(status='VERIFIED', plan_hash=expected['protocol-audit.json']['plan_hash'],
        runtime_hash=expected['protocol-audit.json']['runtime_hash'], audit_hash=expected['protocol-audit.json']['audit_hash'],
        fresh_synthetic_assertions=len(expected['protocol-audit.json']['synthetic_checks']),
        structural_conflict_count=6, other_models_not_proven_feasible=14, candidate_path_blocked_count=20,
        frozen_models_verified=20, visible_owner_verified=True, no_market_evaluation=True,
        runtime_unchanged=True, acceptance_contract_unchanged=True, full_previous_suite_rerun=False)
    if check_index:
        require(read(HERE/'verification.json') == result, 'Verification receipt drift')
        items = read(HERE/'evidence-index.json')['files']
        names = {p.name for p in HERE.iterdir() if p.is_file() and p.name != 'evidence-index.json'}
        require(len(items) == len(names) and {r['file'] for r in items} == names, 'Evidence inventory mismatch')
        for item in items:
            path = (HERE/item['file']).resolve()
            require(path.parent == HERE and path.stat().st_size == item['bytes'] and
                    file_hash(path) == item['sha256'], 'Evidence bytes drift')
    return result


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
