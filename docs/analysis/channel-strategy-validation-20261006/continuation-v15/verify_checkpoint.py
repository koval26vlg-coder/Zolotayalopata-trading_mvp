"""Read-only metadata checks and synthetic paired-model diagnostics, no network."""
from __future__ import annotations

import json
import math
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'continuation-v14'
parent = runpy.run_path(str(PREVIOUS / 'verify_checkpoint.py'))
read, require, verify_index = (parent[k] for k in ('read', 'require', 'verify_index'))

from channel_validation.contract import PLAN_PATH, file_hash, validate_plan  # noqa: E402
from channel_validation.models import causal_funding_forecast  # noqa: E402
from channel_validation.adapters import MissingEvidence, pair_economics, paired  # noqa: E402

IDS = ['funding_carry', 'funding_cross', 'spot_dislocation', 'basis_convergence']


def paired_checks(models):
    checks = []
    known = dict(symbol='X', venue='gate', settlement_ts=0, available_at=0,
                 rate=.001, period_seconds=28800)
    for name, extra in (
        ('future_settlement_excluded', dict(known, settlement_ts=20, available_at=0, rate=.9)),
        ('late_publication_excluded', dict(known, settlement_ts=1, available_at=11, rate=.9)),
    ):
        require(math.isclose(causal_funding_forecast([known, extra], 10, 'X', 'gate'), .003), name)
        checks.append(name)
    require(causal_funding_forecast([known], 57601, 'X', 'gate') is None, 'Stale rate reused')
    checks.append('stale_funding_rejected')
    require(math.isclose(causal_funding_forecast([dict(known, period_seconds=3600)], 10, 'X', 'gate'), .024),
            'Funding period not normalized')
    checks.append('funding_period_normalized')
    entry = dict(ts=10, available_at=10, symbol='X', long_ask=100, long_bid=99,
                 short_bid=101, short_ask=102, long_venue='gate', short_venue='mexc',
                 long_market='perp', short_market='perp', long_fee_bps=10,
                 short_fee_bps=20, long_impact=0, short_impact=0,
                 fee_source='synthetic', base_units_verified=True, long_size=100, short_size=100)
    end = dict(entry, ts=30, available_at=30, long_bid=105, long_ask=106, short_ask=100, short_bid=99)
    # Independent arithmetic: long gain 5, short gain 1, four dated fees.
    base = 6-(.1+.202+.105+.2)
    require(math.isclose(pair_economics(entry, end, 1, [], 'funding_cross'), base), 'Four-leg fees wrong')
    checks.append('all_four_execution_fees')
    events = [dict(symbol='X', venue='mexc', settlement_ts=t, mark_price=120, rate=.01)
              for t in (10, 30, 31)]
    events.append(dict(symbol='X', venue='gate', settlement_ts=20, mark_price=110, rate=.005))
    require(math.isclose(pair_economics(entry, end, 1, events, 'funding_cross'), base+1.2-.55),
            'Funding time or payer sign wrong')
    checks.append('funding_entry_exclusive_exit_inclusive_both_legs')
    for name, bad, funding in (
        ('unverified_contract_units_rejected', dict(entry, base_units_verified=False), []),
        ('missing_fee_evidence_rejected', dict(entry, fee_source=''), []),
        ('missing_settlement_mark_rejected', entry, [dict(events[1], mark_price=0)]),
    ):
        try:
            pair_economics(bad, end, 1, funding, 'funding_cross')
        except MissingEvidence:
            pass
        else:
            raise ValueError(name)
        checks.append(name)
    try:
        paired(models['funding_carry'], dict(paired_quotes=[entry, end], funding=[]), lambda: None)
    except MissingEvidence as error:
        require('instrument type' in str(error), 'Unexpected route failure')
    else:
        raise ValueError('Wrong route accepted')
    checks.append('wrong_instrument_route_rejected')

    # Deliberately reproduce the frozen implementation gap; this is NOT a passing safety gate.
    signal = dict(entry, long_ask=100, long_bid=100, short_ask=100, short_bid=100,
                  short_venue='gate', long_market='spot', long_fee_bps=0, short_fee_bps=0)
    rows = [signal, dict(signal, ts=11, available_at=11), dict(signal, ts=86411, available_at=86411)]
    trades, exposure = paired(models['funding_carry'], dict(paired_quotes=rows, funding=[known]), lambda: None)
    require(len(trades) == 1 and not exposure, 'Universe-gap reproducer changed; reassess audit')
    return checks, ['PAIRED_MONTHLY_UNIVERSE_NOT_ENFORCED']


def verify():
    prior = parent['verify']()
    parent_count = verify_index(PREVIOUS)
    plan = validate_plan(read(PLAN_PATH))
    models = {m['id']: m for m in plan['models']}
    provenance = read(HERE / 'publication-provenance.json')
    require(provenance['plan_hash'] == plan['plan_hash'] and provenance['runtime_hash'] == prior['runtime_hash'],
            'Frozen binding changed')
    for item in provenance['parent_files']:
        path = (ROOT / item['path']).resolve()
        require(path.is_relative_to(ROOT) and path.stat().st_size == item['bytes'] and
                file_hash(path) == item['sha256'], 'Parent evidence changed')
    metadata = read(HERE / 'local-metadata.json')
    require(len(metadata['manifests']) == 6 and metadata['raw_market_files_read'] == 0 and
            metadata['legacy_results_read'] == 0, 'Metadata scope changed')
    archive = Path('E:/ZolotyayLopata-data/exports/trading-mvp').resolve()
    for item in metadata['manifests']:
        path = Path(item['path']).resolve()
        require(path.is_relative_to(archive) and 'listing' not in str(path).lower(), 'Bad metadata path')
        require(path.stat().st_size == item['bytes'] and file_hash(path) == item['sha256'], 'Metadata drift')
        require(not item['underlying_data_read'] and not item['underlying_data_hash_verified'], 'Overstated audit')
    queue = read(HERE / 'model-input-queue.json')
    old = {m['id']: m for m in read(PREVIOUS / 'model-input-queue.json')['models']}
    require(len(queue['models']) == 20 and {m['id'] for m in queue['models']} == set(models), 'Model lost')
    for item in queue['models']:
        key = item['id']
        require(item['model_hash'] == models[key]['model_hash'] and item['metrics'] is None and
                item['input_status'] == 'BLOCKED_DATA', 'Invented evaluation')
        if key not in IDS:
            require({k: v for k, v in item.items() if k != 'evidence'} ==
                    {k: v for k, v in old[key].items() if k != 'evidence'}, 'Other model changed')
            require([(HERE / p).resolve() for p in item['evidence']] ==
                    [(PREVIOUS / p).resolve() for p in old[key]['evidence']], 'Evidence target changed')
        for rel in item['evidence']:
            require((HERE / rel).is_file(), 'Missing evidence')
    audit = read(HERE / 'suitability-audit.json')
    require(set(audit['models']) == set(IDS), 'Missing paired audit')
    source_ids = {s['id'] for s in read(HERE / 'source-evidence.json')['sources']}
    for key, item in audit['models'].items():
        require(item['model_hash'] == models[key]['model_hash'] and not item['evaluation_allowed_now'], 'Audit mismatch')
        require(set(item['required_kinds']) == set(models[key]['required_kinds']), 'Missing input kind')
        require(set(item['source_ids']) <= source_ids and item['metrics'] is None, 'Invalid source/result')
    matrix = read(HERE / 'matrix.json')
    require(matrix['models'] == queue['models'] and matrix['plan_hash'] == plan['plan_hash'], 'Stale matrix')
    require(matrix['bounded_source_checks_recorded_count'] == 20 and not matrix['pending_source_audits'], 'Audit count')
    require(matrix['evaluated_model_count'] == matrix['candidate_count'] == matrix['rejected_count'] == 0,
            'Nonexistent strategy result')
    require(not matrix['program_complete'] and matrix['blocked_data_count'] == 20, 'Wrong completion')
    markdown = (HERE / 'matrix.md').read_text(encoding='utf-8-sig')
    require(all(markdown.count(f'`{key}`') == 1 for key in models), 'Incomplete Markdown matrix')
    require(sum(line.startswith('| ') for line in markdown.splitlines()) == 21, 'Wrong matrix rows')
    checks, gaps = paired_checks(models)
    require(audit['known_runtime_gaps'] == gaps, 'Missing known gap')
    if (HERE / 'evidence-index.json').exists():
        verify_index(HERE)
    return dict(schema='paired_source_checkpoint_verification_v1', successful=True,
                plan_hash=plan['plan_hash'], runtime_hash=prior['runtime_hash'],
                frozen_models_verified=20, runtime_binding_file_count=29,
                parent_index_files_verified=parent_count, archive_metadata_files_verified=6,
                paired_synthetic_checks_passed=len(checks), paired_synthetic_check_names=checks,
                known_runtime_gaps_reproduced=gaps, runtime_ready_for_paired_evaluation=False,
                other_model_queue_entries_unchanged=True, bounded_source_checks_recorded_models=20,
                full_unit_suite_rerun=False, market_evaluation_executed=False,
                underlying_market_files_read=0, active_writer_claim_absent=True)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, sort_keys=True))
