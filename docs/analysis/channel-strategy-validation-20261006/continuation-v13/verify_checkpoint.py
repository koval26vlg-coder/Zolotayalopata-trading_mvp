"""Read-only audit verification and synthetic gate checks; no market evaluation."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / 'trading_mvp' / 'src'))

from channel_validation.contract import (  # noqa: E402
    PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan,
)
from channel_validation.statistics import candidate_status  # noqa: E402


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
    require(seen == {p.name for p in directory.iterdir()
                     if p.is_file() and p.name != 'evidence-index.json'}, 'Incomplete evidence index')
    return len(seen)


def check_feasibility(plan):
    model = next(m for m in plan['models'] if m['id'] == 'aave_lending')
    hold = model['parameters']['hold_days']
    start, end = map(date.fromisoformat, plan['periods']['final'])
    wf_start = date.fromisoformat(plan['periods']['walk_forward'][0])
    days, combined_days = (end-start).days, (end-wf_start).days
    final_max, combined_max = days // hold, combined_days // hold
    require((hold, days, final_max, combined_days, combined_max) == (30, 273, 9, 638, 21),
            'Frozen sample upper bound changed')
    record = read(HERE / 'feasibility.json')
    expected = dict(final_period_days=days, hold_days=hold,
                    max_completed_nonoverlapping_final_positions=final_max,
                    wf_plus_final_days=combined_days,
                    wf_plus_final_upper_bound_diagnostic_only=combined_max,
                    required_oos_trades=plan['statistics']['min_oos_trades'],
                    required_temporal_groups=plan['statistics']['min_temporal_groups'],
                    single_base_share_if_positive=1.0,
                    allowed_single_base_share=plan['statistics']['max_positive_pnl_single_base'])
    require(record['derived_constraints'] == expected, 'Feasibility derivation mismatch')
    require(record['status'] == 'CANDIDATE_UNREACHABLE_UNDER_FROZEN_IMPLEMENTATION_AND_CRITERIA',
            'Feasibility result changed')
    require(record['plan_hash'] == plan['plan_hash'] and record['model_hash'] == model['model_hash'],
            'Feasibility binding mismatch')
    require(not record['real_market_metrics_computed'] and not record['acceptance_contract_changed'],
            'No trading metrics or contract edits allowed in this audit')

    # Deliberately synthetic metadata reaches the existing pre-metric guards only.
    def gate_fixture(trades):
        return dict(open_positions=[], partial_periods=[], exposure='UNSEEN_CERTIFIED',
                    execution_quality='EXECUTABLE_CERTIFIED',
                    oos=dict(trades=trades, temporal_groups=20, calendar_days=273,
                             calendar_complete=True, single_event_positive_share=0.1,
                             single_base_positive_share=1.0))

    fixtures = [
        ('final_window_upper_bound', final_max, 'INSUFFICIENT_DATA'),
        ('combined_period_diagnostic_not_an_allowed_oos', combined_max, 'INSUFFICIENT_DATA'),
        ('counterfactual_enough_trades_single_asset', 30, 'INCONCLUSIVE_CONCENTRATION'),
    ]
    outcomes = []
    for name, count, expected_status in fixtures:
        result = candidate_status(gate_fixture(count), None, plan)
        require(result == expected_status, f'Synthetic gate regression: {name}')
        outcomes.append(dict(name=name, status=result, synthetic=True))
    return outcomes


def verify():
    plan = validate_plan(read(PLAN_PATH))
    binding = runtime_binding()
    runtime_hash = canonical_hash(binding)
    previous = HERE.parent / 'continuation-v12'
    prior_tests = read(HERE.parent / 'continuation-v9' / 'verification.json')
    require(binding == prior_tests['runtime_binding'], 'Frozen runtime changed')
    require(prior_tests['successful'] and prior_tests['tests'] == 180, 'Prior test record mismatch')
    parent_count = verify_index(previous)
    provenance = read(HERE / 'publication-provenance.json')
    require(provenance['plan_hash'] == plan['plan_hash'], 'Plan binding mismatch')
    require(provenance['runtime_hash'] == runtime_hash, 'Runtime binding mismatch')
    for item in provenance['parent_files']:
        path = (ROOT / item['path']).resolve()
        require(path.is_relative_to(ROOT), 'Parent path escaped repository')
        require(path.stat().st_size == item['bytes'], f'Parent size mismatch: {path}')
        require(file_hash(path) == item['sha256'], f'Parent hash mismatch: {path}')

    old = read(previous / 'model-input-queue.json')
    queue = read(HERE / 'model-input-queue.json')
    require(queue['plan_hash'] == plan['plan_hash'], 'Queue binding mismatch')
    require(len(queue['models']) == queue['model_count'] == 20, 'Incomplete queue')
    require(queue['next_priority'] == ['wallet_follow'], 'Wrong next priority')
    models = {m['id']: m for m in plan['models']}
    require({m['id'] for m in queue['models']} == set(models), 'Model set mismatch')
    prior = {m['id']: m for m in old['models']}
    for model in queue['models']:
        key = model['id']
        require(model['model_hash'] == models[key]['model_hash'], 'Model hash mismatch')
        require(model['metrics'] is None and model['input_status'] == 'BLOCKED_DATA',
                'Unexpected trading result')
        if key != 'aave_lending':
            require({k: v for k, v in model.items() if k != 'evidence'} ==
                    {k: v for k, v in prior[key].items() if k != 'evidence'}, 'Unrelated model changed')
            require([(HERE / p).resolve() for p in model['evidence']] ==
                    [(previous / p).resolve() for p in prior[key]['evidence']], 'Evidence target changed')
        for path in model['evidence']:
            require((HERE / path).is_file(), f'Missing evidence: {path}')

    sources = read(HERE / 'source-evidence.json')
    ids = {s['id'] for s in sources['sources']}
    require(len(ids) == len(sources['sources']), 'Duplicate source')
    require(sources['rpc_requests'] == sources['market_archives_downloaded'] == 0,
            'Unexpected acquisition')
    audit = read(HERE / 'suitability-audit.json')
    readiness = read(HERE / 'data-readiness.json')
    require(audit['plan_hash'] == plan['plan_hash'] and audit['runtime_hash'] == runtime_hash,
            'Audit binding mismatch')
    require(audit['model_hashes'] == {'aave_lending': models['aave_lending']['model_hash']},
            'Audit model mismatch')
    require(readiness['model_ids'] == ['aave_lending'], 'Readiness model mismatch')
    require(readiness['next_model_hash'] == models['wallet_follow']['model_hash'], 'Next binding mismatch')
    require(not audit['evaluation_allowed_now'] and not readiness['backtest_executed'] and
            not readiness['strategy_rejected'] and readiness['metrics'] is None, 'Invalid verdict')
    require({r['id'] for r in audit['requirements']} >= set(models['aave_lending']['required_kinds']),
            'Required data kind omitted')
    for row in audit['requirements']:
        require(set(row.get('evidence_ids', [])) <= ids, 'Unknown source reference')
    local = read(HERE / 'local-inventory.json')
    require(len(local['roots']) == 6 and local['recursive_scan'] is False, 'Inventory scope mismatch')
    require(all(r['accessible'] and not r['direct_input_manifests'] for r in local['roots']),
            'Inventory finding mismatch')
    require(local['raw_market_files_read'] == 0 and not local['entire_archive_absence_claimed'],
            'Overstated local inventory')
    fixtures = check_feasibility(plan)
    require(not (ROOT / 'docs/agent-log/active-market-data-writer-claim.json').exists(),
            'Writer claim present: obtain a fresh scoped gate')
    if (HERE / 'evidence-index.json').exists():
        verify_index(HERE)
    return dict(schema='documentation_checkpoint_verification_v1', successful=True,
                plan_hash=plan['plan_hash'], runtime_hash=runtime_hash,
                runtime_binding_file_count=len(binding), frozen_models_verified=20,
                model_parameters_unchanged=True, other_model_queue_entries_unchanged=True,
                parent_index_files_verified=parent_count,
                parent_file_bindings_verified=len(provenance['parent_files']),
                all_queue_evidence_paths_exist=True, all_source_references_resolved=True,
                synthetic_gate_checks_passed=len(fixtures), synthetic_gate_outcomes=fixtures,
                runtime_binding_matches_prior_180_test_record=True,
                full_unit_suite_rerun=False, historical_test_record='../continuation-v9/verification.json',
                active_writer_claim_absent=True, raw_market_inputs_rescanned=False,
                market_data_downloads=0, rpc_requests=0, market_evaluation_executed=False)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, sort_keys=True))
