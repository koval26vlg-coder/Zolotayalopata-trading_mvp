"""Bounded offline review of evidence content; no certification from assertions."""
import argparse
from collections import Counter
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'trading_mvp/src'))
from channel_validation.contract import canonical_hash, file_hash, build_plan, runtime_binding, PLAN_PATH
from channel_validation.data import write_immutable
from channel_validation.evidence import strict_json
from global_market_writer_claim import claim_global_market_writer, release_global_market_writer

RUN_ID = 'history_evidence_content_v22_20261009'
CAP = 4*1024*1024
SOURCES = [
    'evidence-registry.md', 'gate-source-audit.json',
    'continuation-v3/survivorship-audit.json', 'continuation-v4/gate-metadata-audit.json',
    'continuation-v6/data-readiness.json', 'continuation-v6/source-notes.json',
    'continuation-v9/audit.json',
    *[f'continuation-v{i}/suitability-audit.json' for i in range(10, 15)],
    'continuation-v15/local-metadata.json', 'continuation-v18/data-readiness.json',
    'continuation-v19/source-evidence.json', 'continuation-v19/data-readiness.json',
    'continuation-v21/readiness.json', 'continuation-v21/runtime-rebind.json',
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    require(path.stat().st_size <= CAP, 'Audit input too large')
    with path.open('rb') as stream:
        raw = stream.read(CAP+1)
    require(len(raw) <= CAP, 'Audit input grew past bound')
    return strict_json(raw)


def parent_verify():
    spec = importlib.util.spec_from_file_location('v21_verify', BASE/'continuation-v21/verify_checkpoint.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify()


def reference(path):
    path = path.resolve()
    require(path.is_relative_to(ROOT) and path.is_file(), 'Reference outside repository')
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size, sha256=file_hash(path))


def prepare():
    parent_verify()
    files = [BASE/p for p in SOURCES]
    runs = sorted((BASE/'runs').iterdir())
    require(len(runs) <= 100, 'Run inventory exceeds bounded audit')
    histories = []
    for run in runs:
        require(run.is_dir() and (run/'intent.json').is_file(), 'Unclassified run in inventory')
        intent = read(run/'intent.json')
        require(intent['stage'] in {
            'verify', 'pipeline', 'report', 'sources', 'archive-audit', 'gate-history-audit',
            'gate-catalog-audit', 'gate-metadata-audit', 'gate-survivorship-audit', 'gate-trades-audit',
            'gate-paired-audit', 'gate-paired-local', 'gate-pairing', 'gold-history-audit',
            'gold-history-remaining', 'histdata-sample', 'histdata-archive', 'histdata-local',
            'histdata-month', 'okx-history-audit', 'okx-full-archive', 'okx-archive-census', 'okx-dependencies'
        }, 'Unreviewed stage in local history')
        require(not intent.get('input_manifest'), 'Historical input in observed run: review separately')
        files.append(run/'intent.json')
        record = dict(run_id=run.name, stage=intent['stage'], intent=reference(run/'intent.json'),
                      completion=None, evaluation=None)
        if (run/'completion.json').exists():
            files.append(run/'completion.json')
            record['completion'] = reference(run/'completion.json')
        if intent['stage'] == 'pipeline':
            files.append(run/'artifacts/evaluation.json')
            record['evaluation'] = reference(files[-1])
        if intent['stage'] == 'report':
            require(intent.get('evaluation_path'), 'Unbound historical report')
            files.append(Path(intent['evaluation_path']))
            record['evaluation'] = reference(files[-1])
        histories.append(record)
    files.extend([PLAN_PATH, HERE/'audit_evidence.py', HERE/'run_audit_visible.ps1'])
    refs = [reference(p) for p in sorted(set(files))]
    require(sum(r['bytes'] for r in refs) <= 16*1024*1024, 'Audit byte budget')
    value = dict(schema='content_audit_inputs_v1', files=refs, runs=histories,
                 plan_hash=build_plan()['plan_hash'], runtime_hash=canonical_hash(runtime_binding()),
                 max_runtime_sec=120, max_bytes=16*1024*1024, network=False)
    value['binding_hash'] = canonical_hash(value)
    write_immutable(HERE/'input-binding.json', value)
    return dict(status='PREPARED_OFFLINE', files=len(refs), run_count=len(histories), binding_hash=value['binding_hash'])


def bindings(check=lambda: None):
    value = read(HERE/'input-binding.json')
    require(value['binding_hash'] == canonical_hash({k:v for k,v in value.items() if k != 'binding_hash'}), 'Input binding changed')
    require(value['runtime_hash'] == canonical_hash(runtime_binding()), 'Runtime changed')
    require(value['plan_hash'] == build_plan()['plan_hash'], 'Plan changed')
    for ref in value['files']:
        check()
        require(reference(ROOT/ref['path']) == ref, 'Bound input changed: '+ref['path'])
    return value


def pointer(value, path):
    for key in path.split('/'):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def exact_fact(value, path, expected):
    actual = pointer(value, path)
    # JSON false must not be replaced by 0 or a string that looks boolean.
    require(type(actual) is type(expected) and actual == expected, 'Changed source fact: '+path)
    return copy.deepcopy(actual)


def empty_evaluation(value):
    require(value.get('result_hash') == canonical_hash({k:v for k,v in value.items() if k != 'result_hash'}), 'Evaluation seal changed')
    require(value['input_manifest_hash'] is None and len(value['models']) == 20, 'Not an empty-input evaluation')
    require(all(m['status'] == 'BLOCKED_DATA' and m['metrics'] is None and not m.get('trades')
                and 'oos' not in m for m in value['models']), 'Historical outcomes present; do not certify unseen')
    return 'EMPTY_INPUT_MATRIX_NO_MARKET_METRICS'


def certificate_disposition(proofs):
    mandatory = {'dated_identity', 'dated_all_leg_costs', 'historical_units', 'causal_availability',
                 'full_scope_coverage', 'fill_evidence', 'exposure_history'}
    missing = sorted(k for k in mandatory if proofs.get(k) != 'INDEPENDENTLY_VERIFIED')
    return dict(status='INSUFFICIENT_EVIDENCE' if missing else 'REQUIRES_INDEPENDENT_REVIEW',
                missing=missing, certificate_issued=False)


def self_tests():
    passed = []
    def reject(name, fn):
        try: fn()
        except (ValueError, KeyError, IndexError): passed.append(name)
        else: raise ValueError('Synthetic assertion did not reject: '+name)
    exact_fact({'v':False}, 'v', False); passed.append('exact_false')
    for value in (0, 'false', True, None):
        reject('no_boolean_coercion_'+repr(value), lambda v=value: exact_fact({'v':v}, 'v', False))
    reject('missing_proof', lambda: exact_fact({}, 'v', False))
    reject('changed_content', lambda: exact_fact({'v':2}, 'v', 1))
    fixture = dict(input_manifest_hash=None, models=[dict(status='BLOCKED_DATA',metrics=None) for _ in range(20)])
    fixture['result_hash'] = canonical_hash(fixture)
    empty_evaluation(fixture); passed.append('empty_result_not_market_test')
    for field, value in (('metrics',{'fake_pnl':1}), ('status','EVALUATED'), ('trades',[{}]), ('oos',{})):
        bad = copy.deepcopy(fixture); bad['models'][0][field] = value
        bad['result_hash'] = canonical_hash({k:v for k,v in bad.items() if k != 'result_hash'})
        reject('no_false_unseen_'+field, lambda b=bad: empty_evaluation(b))
    forged = dict(fixture, input_manifest_hash='newhash')
    reject('stale_result_hash', lambda: empty_evaluation(forged))
    for value in ({}, {'dated_identity':'UNSEEN_CERTIFIED'}, {k:'INDEPENDENTLY_VERIFIED' for k in
            ('dated_identity','dated_all_leg_costs','historical_units','causal_availability','full_scope_coverage','fill_evidence','exposure_history')}):
        require(not certificate_disposition(value)['certificate_issued'], 'Audit must never self-certify')
        passed.append('no_self_issued_certificate_'+str(len(value)))
    return dict(tests=len(passed), failures=0, errors=0, checks=passed)


def build(check=lambda: None):
    bound = bindings(check)
    parent_verify()
    findings = []
    def fact(key, file, field, expected, meaning):
        check()
        value = exact_fact(read(BASE/file), field, expected)
        findings.append(dict(id=key, source=reference(BASE/file), pointer=field, observed=value,
                             conclusion=meaning, evidence_level='LOCAL_REVIEW_OR_RECEIPT_NOT_REMOTE_REVALIDATION'))
    fact('gate_identity', 'continuation-v4/gate-metadata-audit.json', 'historical_universe_certified', False,
         'Current symbols/archive filenames do not establish dated membership and canonical asset types.')
    fact('gate_metadata_body', 'continuation-v4/gate-metadata-audit.json', 'record/body/bytes_read', 0,
         'No complete provider metadata body was retained; this response cannot identify the universe.')
    fact('gate_quote_time', 'continuation-v18/data-readiness.json', 'historical_observation_time_verified', False,
         'Synthetic pairing frontier does not prove historical receipt time.')
    fact('gate_units', 'continuation-v18/data-readiness.json', 'size_unit_verified', False,
         'Observed book sizes cannot be converted to executable base quantity without dated units.')
    fact('gate_terms', 'continuation-v19/data-readiness.json', 'accepted_historical_parameter_rows', 0,
         'No dated multiplier/fee rows were accepted for either January sample.')
    fact('gate_document_archiving', 'continuation-v19/source-evidence.json', 'raw_pages_archived', False,
         'Analyst notes are not retained primary page bytes or historical tariff snapshots.')
    fact('gate_spot_fee_interval', 'continuation-v19/source-evidence.json', 'sources/0/accepted_for_dataset_binding', False,
         '2024 notice does not establish January 2023 or uninterrupted 2025 validity/account eligibility.')
    fact('gate_perp_date_conflict', 'continuation-v19/source-evidence.json', 'sources/1/publication_dates_consistent', False,
         'Saved review reports a 2024 header and 2023 footer; do not choose the convenient year.')
    fact('gate_example_not_state', 'continuation-v19/source-evidence.json', 'sources/4/accepted_for_dataset_binding', False,
         'A later example contract response cannot prove earlier contract state.')
    fact('okx_exit', 'continuation-v6/data-readiness.json', 'exit_quotes_verified', False,
         'An exit catalog is not a validated exit quote.')
    fact('okx_terms', 'continuation-v6/data-readiness.json', 'dated_terms_complete', False,
         'Current terms and later fee announcements do not establish the selected historical terms.')
    fact('gold_format', 'continuation-v9/audit.json', 'full_csv_quote_semantics_verified', True,
         'All local CSV quote rows were checked; this verifies file semantics, not a trading instrument.')
    fact('gold_identity', 'continuation-v10/suitability-audit.json', 'requirements/1/status', 'UNVERIFIED',
         'XAUUSD label lacks a dated executable venue/instrument/lot mapping.')
    fact('dax_identity', 'continuation-v11/suitability-audit.json', 'requirements/0/status', 'CANDIDATES_IDENTIFIED_NOT_BOUND',
         'Index, futures and CFD candidates are not interchangeable execution instruments.')
    fact('equity_identity', 'continuation-v12/suitability-audit.json', 'requirements/1/status', 'REFERENCE_ROUTES_DOCUMENTED_NOT_VALIDATED',
         'No dated full security-id universe including delisted securities is bound.')
    fact('aave_lifetime', 'continuation-v13/suitability-audit.json', 'requirements/4/status', 'STRUCTURAL_PRELAUNCH_ABSENCE',
         'Reported Ethereum v3 launch is later than the development start; do not fabricate prelaunch data.')
    fact('wallet_attribution', 'continuation-v14/suitability-audit.json', 'requirements/4/status', 'NORMALIZATION_DEFINITION_UNRESOLVED',
         'Router/transaction sender cannot silently replace the economic owner.')
    stages, history = Counter(), []
    for r in bound['runs']:
        check()
        stages[r['stage']] += 1
        completion = read(ROOT/r['completion']['path']) if r['completion'] else None
        disposition = empty_evaluation(read(ROOT/r['evaluation']['path'])) if r['evaluation'] else 'NO_MARKET_EVALUATION_STAGE'
        history.append(dict(run_id=r['run_id'], stage=r['stage'],
                            completion_status=completion.get('status') if completion else 'MISSING_RECEIPT',
                            outcome_inspection=disposition))
    registry = (BASE/'evidence-registry.md').read_text(encoding='utf-8')
    require('UNKNOWN_OR_PREVIOUSLY_VIEWED' in registry, 'Exposure declaration changed')
    exposure = dict(schema='bounded_exposure_review_v1', runs=history, stage_counts=dict(sorted(stages.items())),
        status='UNKNOWN_OR_PREVIOUSLY_VIEWED', independently_unseen=False,
        engineering_inspection_is_not_proven_strategy_selection=True,
        program_empty_results_are_not_backtests=True, all_human_or_external_access_history_available=False,
        legacy_raw_or_results_reopened=False, historical_raw_files_read=False,
        scope='Only the frozen local program receipts. No global access ledger and no proof of non-access.')
    groups = {
        'gate_spot': ('gate_identity gate_metadata_body gate_quote_time', 'Complete dated Gate membership/types/turnover plus causal historical quotes and costs.'),
        'paired': ('gate_identity gate_quote_time gate_units gate_terms gate_document_archiving gate_spot_fee_interval gate_perp_date_conflict gate_example_not_state', 'Joint dated unit/cost/availability ledger for both legs and periods; cross-venue models additionally need MEXC.'),
        'options': ('okx_exit okx_terms', 'Complete entry/exit option books with dated contract/fee/settlement terms and executable underlying quotes.'),
        'gold': ('gold_format gold_identity', 'Bind retained quotes to a dated actual instrument, units, sessions and costs before acquiring more months.'),
        'dax': ('dax_identity', 'One dated execution instrument, regular sessions, complete history and causal FX/lot-reserve checks.'),
        'equities': ('equity_identity', 'Dated security IDs, delistings, corporate actions, sessions, 5m history and borrowability.'),
        'aave': ('aave_lifetime', 'Exact deployment/activation, historical reserve indices/flags/liquidity, gas and executable USDC quotes.'),
        'wallets': ('wallet_attribution', 'Pre-outcome economic-owner/route semantics plus canonical blocks, dated token identities and executable next-block quotes.')}
    rows = []
    parent = read(BASE/'continuation-v21/readiness.json')
    for m in parent['models']:
        n = m['number']
        group = ('gate_spot' if n <= 6 or n == 14 else 'paired' if n <= 10 else
                 'options' if n <= 13 else 'gold' if n == 15 else 'dax' if n == 16 else
                 'equities' if n <= 18 else 'aave' if n == 19 else 'wallets')
        keys, need = groups[group]
        rows.append(dict(id=m['id'], number=n, model_hash=m['model_hash'], input_status='BLOCKED_DATA',
            strategy_verdict=m['strategy_verdict'], protocol_status=m['protocol_status'],
            findings=keys.split(), required_new_evidence=need, exposure_status=exposure['status'],
            independent_oos_certified=False, execution_certified=False, metrics=None))
    audit = dict(schema='existing_evidence_content_audit_v1', status='REVIEW_COMPLETE_NO_CERTIFIABLE_INPUT',
        binding_hash=bound['binding_hash'], runtime_hash=bound['runtime_hash'], plan_hash=bound['plan_hash'],
        findings=findings, exposure_review=exposure, models=rows,
        tested_on_real_history=0, new_candidates=0, new_strategy_rejections=0, accepted_identity_records=0,
        certificates_issued=0, network_requests=0, audit_scope_exhaustive=False,
        automation_disposition='DO_NOT_REPEAT_WITHOUT_NEW_EVIDENCE_OR_SUBSTANTIVE_CONTRACT_DECISION',
        substantive_contract_conflicts=[m['id'] for m in rows if m['protocol_status']=='STRUCTURAL_ACCEPTANCE_CONFLICT'])
    audit['audit_hash'] = canonical_hash(audit)
    tests = self_tests()
    bindings(check)
    return audit, tests


def verify():
    audit, tests = build()
    require(read(HERE/'audit.json') == audit and read(HERE/'tests.json') == tests, 'Audit result drift')
    done, owner, dispatch = [read(HERE/(n+'.json')) for n in ('completion','owner','dispatch')]
    require(done['status']=='COMPLETE' and done['exit_code']==0 and owner['job_assigned']
            and owner['owner_pid']==dispatch['terminal_pid'] and owner['worker_pid']==done['worker_pid'], 'Run ownership/completion mismatch')
    return dict(status='VERIFIED', audit_hash=audit['audit_hash'], tests=tests['tests'],
                audited_findings=len(audit['findings']), inspected_program_runs=len(audit['exposure_review']['runs']),
                blocked_models=len(audit['models']), certificates_issued=0, runtime_unchanged=True)


def run(token):
    until = time.monotonic()+30
    while not (HERE/'owner.json').exists():
        require(time.monotonic()<until, 'Visible owner handshake timeout')
        time.sleep(.1)
    owner, dispatch = read(HERE/'owner.json'), read(HERE/'dispatch.json')
    require(owner['worker_pid']==os.getpid() and owner['token']==token==dispatch['token']
            and owner['owner_pid']==dispatch['terminal_pid'] and owner['job_assigned'], 'Visible owner mismatch')
    deadline = time.monotonic()+115
    def check():
        if time.monotonic()>deadline or (HERE/'stop.json').exists():
            raise TimeoutError('Bounded audit stopped')
    claim_path = ROOT/'docs/agent-log/active-market-data-writer-claim.json'
    plan = build_plan()
    claim = claim_global_market_writer(claim_path, run_id=RUN_ID, owner_pid=os.getpid(),
        owner_kind='visible_offline_evidence_audit', plan_hash=plan['plan_hash'],
        output_namespace=HERE, writer_pid=os.getpid(), terminal_pid=owner['owner_pid'])
    status, code = 'STOPPED_INCOMPLETE', 2
    try:
        print('Checking existing source claims and local exposure history. No network or market replay.', flush=True)
        audit, tests = build(check)
        write_immutable(HERE/'audit.json', audit)
        write_immutable(HERE/'tests.json', tests)
        print(json.dumps(dict(status=audit['status'], findings=len(audit['findings']), tests=tests['tests'],
                              runs=len(audit['exposure_review']['runs']), certificates_issued=0)), flush=True)
        status, code = 'COMPLETE', 0
    finally:
        release_global_market_writer(claim_path, run_id=RUN_ID, owner_pid=os.getpid(),
            ownership_token=claim['ownership_token'], final_status=status,
            expected_plan_hash=plan['plan_hash'], archive_dir=HERE/'claim-archive')
        write_immutable(HERE/'completion.json', dict(status=status, exit_code=code, worker_pid=os.getpid(),
            run_id=RUN_ID, max_runtime_sec=120, no_market_replay=True))
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--token')
    args = parser.parse_args()
    if args.token:
        sys.exit(run(args.token))
    if args.preflight:
        bound = bindings()
        parent_verify()
        print(json.dumps(dict(status='READY_OFFLINE', binding_hash=bound['binding_hash'])))
        sys.exit(0)
    print(json.dumps(prepare() if args.prepare else verify(), indent=2))
