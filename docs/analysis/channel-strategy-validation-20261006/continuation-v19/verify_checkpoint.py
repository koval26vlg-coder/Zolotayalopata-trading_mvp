"""Read-only verification of a documentary checkpoint; no market evaluation."""
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PARENT = HERE.parent / 'continuation-v18'
sys.path.insert(0, str(ROOT / 'trading_mvp/src'))
from channel_validation.contract import PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(check_index=True):
    spec = importlib.util.spec_from_file_location('checkpoint_v18', PARENT / 'verify_checkpoint.py')
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    parent_result = previous.verify()
    plan = validate_plan(read(PLAN_PATH))
    runtime_hash = canonical_hash(runtime_binding())
    provenance = read(HERE / 'publication-provenance.json')
    require(runtime_hash == provenance['runtime_hash'] == parent_result['runtime_hash'], 'Runtime drift')
    require(plan['plan_hash'] == provenance['plan_hash'] and
            file_hash(PLAN_PATH) == provenance['plan_file_sha256'], 'Plan drift')
    require(provenance['parent_evidence_index_sha256'] == file_hash(PARENT / 'evidence-index.json'), 'Parent drift')
    for item in provenance['local_evidence']:
        path = (HERE / item['file']).resolve()
        require(path.is_relative_to(HERE.parent.resolve()) and file_hash(path) == item['sha256'], 'Local evidence drift')
    require(provenance['runtime_changed'] is False and provenance['full_unit_suite_rerun'] is False,
            'False implementation/test claim')

    evidence = read(HERE / 'source-evidence.json')
    sources = {s['id']: s for s in evidence['sources']}
    require(len(sources) == len(evidence['sources']) == 6, 'Wrong source set')
    for source in sources.values():
        u = urlsplit(source['url'])
        require(u.scheme == 'https' and u.netloc == 'www.gate.com', 'Non-official source')
        require(source['accepted_for_dataset_binding'] is False and bool(source['exclusion']), 'Unsafe parameter promotion')
    require(evidence['raw_pages_archived'] is False and evidence['remote_response_sha256_available'] is False,
            'False remote snapshot claim')
    spot = sources['spot_fee_34105']
    require(spot['announced_effective_date'] == '2024-01-29' and spot['publication_dates_consistent'] is True and
            spot['documented_terms']['base_taker_percent'] == '0.1000', 'Lost partial dated evidence')
    conflict = sources['perp_fee_36485']
    require(conflict['publication_header_utc'][:4] != conflict['publication_footer_date'][:4] and
            conflict['publication_dates_consistent'] is False and conflict['accepted_effective_from'] is None,
            'Date conflict incorrectly resolved')

    readiness = read(HERE / 'data-readiness.json')
    require(readiness['status'] == 'BLOCKED_DATA' and readiness['evaluation_allowed'] is False and
            readiness['accepted_historical_parameter_rows'] == 0 and readiness['partial_dated_fee_notices'] == 1,
            'Incorrect readiness')
    require(readiness['market_archive_downloads'] == 0 and readiness['public_document_research_performed'] is True,
            'Incorrect network scope')
    require(readiness['source_evidence_sha256'] == file_hash(HERE / 'source-evidence.json'), 'Source binding drift')
    require([p['start_utc'] for p in readiness['sample_checks']] ==
            ['2023-01-01T00:00:00Z', '2025-01-01T00:00:00Z'], 'Changed samples')
    for sample in readiness['sample_checks']:
        require(sample['verified_multiplier'] is None and sample['verified_all_leg_fees'] is None and
                sample['eligible_for_evaluation'] is False, 'Invented historical terms')
    require(readiness['protocol_periods'] == plan['periods'], 'Period drift')

    matrix, queue = read(HERE / 'matrix.json'), read(HERE / 'model-input-queue.json')
    require(matrix['model_count'] == matrix['blocked_data_count'] == len(matrix['models']) == 20 and
            matrix['candidate_count'] == matrix['evaluated_model_count'] == matrix['rejected_count'] == 0,
            'False trading verdict')
    require(matrix['models'] == queue['models'] and matrix['plan_hash'] == queue['plan_hash'] == plan['plan_hash'],
            'Queue mismatch')
    require(queue['next_action_kind'] == 'ALL_MODEL_PROTOCOL_FEASIBILITY_RECONCILIATION' and
            queue['next_priority'] == [m['id'] for m in plan['models']] and
            queue['dated_contract_cost_probe_repeat_authorized'] is False, 'Wrong next action')
    old_rows = read(PARENT / 'matrix.json')['models']
    changed_ids = {'funding_carry', 'basis_convergence'}
    for model, row, old in zip(plan['models'], matrix['models'], old_rows):
        require(row['id'] == model['id'] and row['model_hash'] == model['model_hash'] and
                row['metrics'] is None and row['input_status'] == 'BLOCKED_DATA', 'Changed model/outcome')
        expected = dict(old, evidence=[r if r.startswith('../') else '../continuation-v18/' + r for r in old['evidence']])
        if row['id'] in changed_ids:
            require(row['source_audit_state'] == 'BOUNDED_INPUT_SEARCH_CLOSED_UNVERIFIED_DATED_TERMS', 'Search not closed')
            require(row['evidence'] == expected['evidence'] + ['source-evidence.json', 'data-readiness.json', 'search-disposition.json'],
                    'Lost evidence lineage')
            for key in set(expected) - {'next_step', 'source_audit_state', 'evidence'}:
                require(row[key] == expected[key], 'Unexpected row change: ' + key)
        else:
            require(row == expected, 'Unrelated model changed')
        for reference in row['evidence']:
            path = (HERE / reference).resolve()
            require(path.is_relative_to(HERE.parent.resolve()) and path.is_file(), 'Missing evidence')

    disposition = read(HERE / 'search-disposition.json')
    require(disposition['input_search_status'] == 'CLOSED_BLOCKED_DATA' and
            set(disposition['models']) == changed_ids and disposition['strategy_rejected'] is False and
            disposition['repeat_same_search'] is False and disposition['bulk_download_authorized'] is False and
            disposition['next_action_kind'] == queue['next_action_kind'], 'Incorrect disposition')
    result = dict(status='VERIFIED', plan_hash=plan['plan_hash'], runtime_hash=runtime_hash,
                  runtime_changed=False, full_unit_suite_rerun=False, inherited_tests_bound=213,
                  official_source_records=6, partial_dated_fee_notices=1, accepted_historical_parameter_rows=0,
                  frozen_models_verified=20, unrelated_model_rows_unchanged=18, market_evaluation_run=False,
                  market_archive_downloads=0, network_called_by_verifier=False,
                  scope='Local consistency and hash verification, not independent authentication of remote page history')
    if check_index:
        require(read(HERE / 'verification.json') == result, 'Verification snapshot differs')
        index = read(HERE / 'evidence-index.json')
        expected_names = {p.name for p in HERE.iterdir() if p.is_file() and p.name != 'evidence-index.json'}
        require(len(index['files']) == len(expected_names) and
                {r['file'] for r in index['files']} == expected_names, 'Incomplete evidence index')
        previous.verify_index(HERE)
    return result


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
