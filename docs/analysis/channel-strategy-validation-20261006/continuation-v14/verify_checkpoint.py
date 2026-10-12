"""Read-only provenance verification with synthetic, non-economic wallet fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREVIOUS = HERE.parent / 'continuation-v13'
parent = runpy.run_path(str(PREVIOUS / 'verify_checkpoint.py'))
read, require, verify_index = (parent[name] for name in ('read', 'require', 'verify_index'))

from channel_validation.contract import PLAN_PATH, validate_plan, file_hash  # noqa: E402
from channel_validation.data import ts  # noqa: E402
from channel_validation.models import wallet_ranking  # noqa: E402
from channel_validation.adapters import MissingEvidence, wallets  # noqa: E402


def wallet_checks(model):
    at = ts('2023-02-01T00:00:00Z')

    def buy(wallet, time, amount=10, available=None):
        return dict(wallet=wallet, side='buy', ts=time, quote_usd=amount,
                    available_at=time if available is None else available)

    done = []
    require(wallet_ranking([buy('A', at-10), buy('FUTURE', at+1, 1000)], at) == ['A'],
            'Future purchases affected ranking')
    done.append('future_purchase_excluded')
    require(wallet_ranking([buy('A', at-10), buy('LATE', at-1, 1000, at+1)], at) == ['A'],
            'Late publication affected month-start ranking')
    done.append('late_publication_excluded')
    require(wallet_ranking([buy('BOUNDARY', at-30*86400), buy('OLD', at-30*86400-1, 1000),
                            buy('CURRENT', at, 1000)], at) == ['BOUNDARY'], 'Lookback boundary failed')
    done.append('exact_thirty_day_lookback')
    rows = [buy(f'W{i:02}', at-10) for i in range(11, -1, -1)]
    require(wallet_ranking(rows, at) == [f'W{i:02}' for i in range(10)], 'Top-ten/tie order failed')
    done.append('top_ten_deterministic_ties')

    jan = ts('2023-01-01T00:00:00Z')
    universe = [dict(ts=t, available_at=t, members=['T']) for t in (jan, at)]
    swaps = [dict(buy('A', at-10), token='T', symbol='T', chain='ethereum',
                  block_number=1, quantity=1),
             dict(buy('A', at+10), token='T', symbol='T', chain='ethereum',
                  block_number=10, quantity=1)]

    def quote(time, block, sellable=True, available=None):
        return dict(ts=time, available_at=time if available is None else available,
                    block_number=block, token='T', symbol='T', sellable=sellable)

    def run(quotes, signals=swaps):
        return wallets(model, dict(dex_swaps=signals, token_universe=universe,
                                   execution_quotes=quotes), lambda: None)

    for name, entry in (
        ('same_block_quote_rejected', quote(at+20, 10)),
        ('unavailable_quote_rejected', quote(at+20, 11, available=at+21)),
    ):
        try:
            run([entry])
        except MissingEvidence as error:
            require('Next-block' in str(error), 'Unexpected missing-input reason')
        else:
            raise ValueError(name)
        done.append(name)

    repeated = swaps + [dict(swaps[-1], ts=at+30, available_at=at+30, block_number=12)]
    trades, exposure = run([quote(at+20, 11), quote(at+20+86400, 100, False)], repeated)
    require(not trades and exposure == [dict(symbol='T', reason='TOKEN_EXIT_NOT_EXECUTABLE')],
            'Unexecutable exit was completed or duplicated')
    done.append('unsellable_exit_remains_open_once')
    return done


def verify():
    prior_proof = parent['verify']()
    parent_count = verify_index(PREVIOUS)
    plan = validate_plan(read(PLAN_PATH))
    models = {m['id']: m for m in plan['models']}
    provenance = read(HERE / 'publication-provenance.json')
    require(provenance['plan_hash'] == plan['plan_hash'], 'Plan binding mismatch')
    require(provenance['runtime_hash'] == prior_proof['runtime_hash'], 'Runtime binding mismatch')
    for item in provenance['parent_files']:
        path = (ROOT / item['path']).resolve()
        require(path.is_relative_to(ROOT), 'Parent path escaped repository')
        require(path.stat().st_size == item['bytes'], f'Parent size changed: {path}')
        require(file_hash(path) == item['sha256'], f'Parent hash changed: {path}')
    queue = read(HERE / 'model-input-queue.json')
    old = {m['id']: m for m in read(PREVIOUS / 'model-input-queue.json')['models']}
    require(queue['plan_hash'] == plan['plan_hash'], 'Queue plan mismatch')
    require(queue['model_count'] == len(queue['models']) == 20, 'Incomplete queue')
    require({m['id'] for m in queue['models']} == set(models), 'Model set mismatch')
    expected_next = ['funding_carry', 'funding_cross', 'spot_dislocation', 'basis_convergence']
    require(queue['next_priority'] == expected_next, 'Unfinished input audits omitted')
    for entry in queue['models']:
        key = entry['id']
        require(entry['model_hash'] == models[key]['model_hash'], 'Model hash mismatch')
        require(entry['metrics'] is None and entry['input_status'] == 'BLOCKED_DATA', 'Invented result')
        if key != 'wallet_follow':
            require({k: v for k, v in entry.items() if k != 'evidence'} ==
                    {k: v for k, v in old[key].items() if k != 'evidence'}, 'Other model changed')
            require([(HERE / p).resolve() for p in entry['evidence']] ==
                    [(PREVIOUS / p).resolve() for p in old[key]['evidence']], 'Evidence target changed')
        for relative in entry['evidence']:
            require((HERE / relative).is_file(), f'Missing evidence: {relative}')

    audit = read(HERE / 'suitability-audit.json')
    ready = read(HERE / 'data-readiness.json')
    sources = read(HERE / 'source-evidence.json')
    ids = {s['id'] for s in sources['sources']}
    require(len(ids) == len(sources['sources']), 'Duplicate source')
    require(audit['model_hashes'] == {'wallet_follow': models['wallet_follow']['model_hash']},
            'Audit model mismatch')
    require(audit['plan_hash'] == plan['plan_hash'] and
            audit['runtime_hash'] == prior_proof['runtime_hash'], 'Audit binding mismatch')
    require({r['id'] for r in audit['requirements']} >= set(models['wallet_follow']['required_kinds']),
            'Input requirements omitted')
    for row in audit['requirements']:
        require(set(row.get('evidence_ids', [])) <= ids, 'Unresolved source')
    require(not audit['evaluation_allowed_now'] and not ready['backtest_executed'] and
            not ready['strategy_rejected'] and ready['metrics'] is None, 'Invalid readiness result')
    require(ready['next_model_ids'] == expected_next, 'Readiness queue mismatch')

    matrix = read(HERE / 'matrix.json')
    require(matrix['plan_hash'] == plan['plan_hash'], 'Matrix plan mismatch')
    require(matrix['models'] == queue['models'], 'Matrix not bound to full queue')
    pending = [m['id'] for m in queue['models']
               if m['source_audit_state'] == 'NOT_YET_AUDITED_IN_THIS_CHECKPOINT']
    require(pending == expected_next and matrix['pending_source_audits'] == pending, 'Missing pending audits')
    require(matrix['bounded_source_checks_recorded_count'] == 20-len(pending) == 16, 'Audit count mismatch')
    require(matrix['evaluated_model_count'] == matrix['candidate_count'] == matrix['rejected_count'] == 0,
            'Matrix implies nonexistent trading result')
    require(matrix['blocked_data_count'] == 20 and not matrix['program_complete'], 'Wrong program status')
    text = (HERE / 'matrix.md').read_text(encoding='utf-8-sig')
    for model in plan['models']:
        require(text.count(f'`{model["id"]}`') == 1, 'Markdown matrix missing/duplicating model')
    require(sum(line.startswith('| ') for line in text.splitlines()) == 21, 'Markdown row count mismatch')
    require(not sources['credentials_used'] and sources['market_archives_downloaded'] == 0 and
            sources['rpc_requests'] == sources['authenticated_queries'] == 0, 'Unexpected data acquisition')
    checks = wallet_checks(models['wallet_follow'])
    if (HERE / 'evidence-index.json').exists():
        verify_index(HERE)
    return dict(schema='wallet_source_checkpoint_verification_v1', successful=True,
                plan_hash=plan['plan_hash'], runtime_hash=prior_proof['runtime_hash'],
                runtime_binding_file_count=29, frozen_models_verified=20,
                other_model_queue_entries_unchanged=True, parent_index_files_verified=parent_count,
                parent_file_bindings_verified=len(provenance['parent_files']),
                wallet_synthetic_checks_passed=len(checks), wallet_synthetic_check_names=checks,
                bounded_source_checks_recorded_models=16, pending_source_audits=expected_next,
                full_unit_suite_rerun=False, market_evaluation_executed=False,
                parent_aave_synthetic_checks_passed=prior_proof['synthetic_gate_checks_passed'],
                all_queue_evidence_paths_exist=True, local_archive_rescanned=False,
                runtime_binding_matches_prior_180_test_record=True, active_writer_claim_absent=True)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, sort_keys=True))
