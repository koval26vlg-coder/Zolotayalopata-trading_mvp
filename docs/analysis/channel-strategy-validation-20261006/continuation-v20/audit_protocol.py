"""Offline protocol audit. Synthetic assertions only, never a historical replay."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PARENT = HERE.parent / 'continuation-v19'
sys.path.insert(0, str(ROOT / 'trading_mvp/src'))
from channel_validation import adapters, portfolio, runner, statistics
from channel_validation.contract import PLAN_PATH, canonical_hash, file_hash, runtime_binding, validate_plan
from channel_validation.data import ts, write_immutable


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def previous_check():
    spec = importlib.util.spec_from_file_location('protocol_parent', PARENT / 'verify_checkpoint.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify()


def source(function):
    lines, start = inspect.getsourcelines(function)
    return dict(path=Path(inspect.getsourcefile(function)).relative_to(ROOT).as_posix(),
                function=function.__name__, line=start, end_line=start+len(lines)-1)


def synthetic_checks(plan):
    checks = []

    def check(name, ok, evidence):
        require(ok, name)
        checks.append(dict(name=name, passed=True, evidence=evidence))

    first, last = [datetime.fromisoformat(s).replace(tzinfo=timezone.utc) for s in plan['periods']['final']]
    days = (last-first).days
    mondays = []
    at = first
    while at < last:
        if at.weekday() == 0 and at+timedelta(days=7) < last:
            mondays.append(at.timestamp())
        at += timedelta(days=1)
    start = first.timestamp()

    def trades(bases, count=40, spacing=3*86400, holding=3600):
        return [dict(symbol=bases[i % len(bases)], entry_ts=start+i*spacing,
                     exit_ts=start+i*spacing+holding, pnl=1.0) for i in range(count)]

    shares = {n: statistics.summarize(trades([f'BASE{i}' for i in range(n)]), {})['single_base_positive_share']
              for n in (1, 2, 4)}
    check('one_economic_base_conflicts_with_quarter_cap', shares[1] == 1, dict(share=shares[1], cap=.25))
    check('two_economic_bases_conflict_with_quarter_cap', shares[2] == .5, dict(best_balanced_share=shares[2], cap=.25))
    check('four_balanced_bases_reach_cap_boundary', shares[4] == .25, dict(share=shares[4]))
    ideal = dict(open_positions=[], partial_periods=[], exposure='UNSEEN_CERTIFIED',
        execution_quality='EXECUTABLE_CERTIFIED',
        oos=dict(trades=40, temporal_groups=40, calendar_days=273, calendar_complete=True,
                 single_event_positive_share=.025, single_base_positive_share=.25,
                 mtm_net=1, expectancy=1, profit_factor_unbounded=False, profit_factor=2, max_daily_drawdown=.01),
        folds=[dict(mtm_net=1) for _ in range(5)], stress_oos=dict(mtm_net=0))
    check('candidate_gate_has_a_synthetic_passing_boundary',
          statistics.candidate_status(ideal, .001, plan) == 'HISTORICAL_CANDIDATE_NOT_LIVE',
          'Fabricated assertion fixture only; not a model result or profitability estimate')
    unknown = deepcopy(ideal); unknown['exposure'] = 'UNKNOWN_OR_PREVIOUSLY_VIEWED'
    check('unknown_exposure_cannot_become_candidate',
          statistics.candidate_status(unknown, .001, plan) == 'EXPLORATORY_ONLY', 'Exposure is mandatory')
    unverified = deepcopy(ideal); unverified['execution_quality'] = 'NORMALIZED_EVIDENCE_NOT_INDEPENDENTLY_CERTIFIED'
    check('normalized_quotes_do_not_certify_execution',
          statistics.candidate_status(unverified, .001, plan) == 'EXPLORATORY_ONLY', 'Execution evidence is mandatory')
    inv = runner.sealed(dict(plan_hash=plan['plan_hash']), 'inventory_hash')
    with patch.object(runner, 'load_inputs', return_value=({'manifest_hash': 'synthetic', 'exposure': 'UNSEEN_CERTIFIED'}, [])):
        validation = runner.validate(plan, inv, None)
    check('validate_always_assigns_unknown_exposure',
          len(validation['models']) == 20 and all(r['exposure'] == 'UNKNOWN_OR_PREVIOUSLY_VIEWED' for r in validation['models']),
          'Mock input metadata only; load_inputs patched, no historical rows loaded')
    weekly = [dict(symbol=base, entry_ts=t, exit_ts=t+7*86400) for t in mondays for base in ('BTC', 'ETH')]
    selected = []
    end = float('-inf')
    for t in mondays:
        if t > end:
            selected.append(dict(entry_ts=t, exit_ts=t+7*86400))
            end = t+7*86400
    check('weekly_options_have_38_completed_entry_slots', len(mondays) == 38,
          dict(slots_per_base=len(mondays), two_base_trade_ceiling=2*len(mondays), final_days=days))
    check('touching_weekly_positions_merge_transitively', statistics.temporal_groups(weekly) == 1,
          dict(continuous_fixture_trades=len(weekly), groups=statistics.temporal_groups(weekly)))
    check('weekly_options_have_at_most_19_separated_groups',
          len(selected) == statistics.temporal_groups(selected) == 19,
          dict(best_separated_groups=len(selected), required=plan['statistics']['min_temporal_groups'],
               proof='Equal weekly entry grid and at least 7-day hold: each later group must skip the next touching slot. Additional assets cannot split a component.'))
    touching = trades(['A'], count=2, spacing=86400, holding=86400)
    separated = deepcopy(touching); separated[1]['entry_ts'] += .001; separated[1]['exit_ts'] += .001
    check('strict_endpoint_rule_is_visible', statistics.temporal_groups(touching) == 1 and statistics.temporal_groups(separated) == 2,
          dict(touching_groups=1, positive_gap_groups=2, contract_not_changed=True))
    same_day = trades(['A'], count=2, spacing=7200, holding=3600)
    check('same_entry_day_is_not_two_independent_groups', statistics.temporal_groups(same_day) == 1, 'Two non-overlapping intraday positions')
    check('serial_lending_sample_ceiling_is_nine', days//30 == 9 < plan['statistics']['min_oos_trades'],
          dict(final_days=days, holding_days=30, upper_bound=days//30, required=plan['statistics']['min_oos_trades']))
    alias_rows = trades(['XAU_ALIAS_1', 'XAU_ALIAS_2', 'XAU_ALIAS_3', 'XAU_ALIAS_4'])
    canonical_rows = [dict(r, symbol='XAU') for r in alias_rows]
    alias_share = statistics.summarize(alias_rows, {})['single_base_positive_share']
    canonical_share = statistics.summarize(canonical_rows, {})['single_base_positive_share']
    check('symbol_aliases_can_hide_economic_concentration', alias_share == .25 and canonical_share == 1,
          dict(raw_symbol_share=alias_share, canonical_economic_base_share=canonical_share,
               note='Synthetic naming counterexample, not four independent assets'))
    check('blocked_models_do_not_shrink_holm_family', statistics.holm({'one': .001}, family_size=20)['one'] == .02,
          dict(family_size=20, submitted_tests=1, adjusted_p=.02))
    return checks, dict(final_days=days, option_weekly_completed_slots_per_base=len(mondays),
        option_two_base_trade_ceiling=2*len(mondays), option_max_separated_groups=len(selected),
        serial_lending_trade_ceiling=days//30, concentration_cap=.25, min_positive_bases_required=4)


def build():
    parent = previous_check()
    plan = validate_plan(read(PLAN_PATH))
    runtime = canonical_hash(runtime_binding())
    require(runtime == parent['runtime_hash'], 'Unexpected runtime change')
    checks, bounds = synthetic_checks(plan)
    options = {'long_put', 'cash_put', 'put_spread'}
    singles = {'gold_macd', 'dax_orb', 'aave_lending'}
    constrained = options | singles
    specific = {
        'relative_strength': 'PIT ranks/types/turnover, BTC benchmark, next-hour execution; correlated market shocks are not independent per ticker.',
        'trend_pullback': 'EMA200 warmup, causal 4h bars, stop/target ordering; overlapping holds merge into event groups.',
        'structure_break': 'Pivots available only after two right bars; overlapping holds and market shocks remain grouped.',
        'normalized_line': 'Anchor and ATR fixed at confirmation, no retrospective line; overlaps require grouping.',
        'book_continue': 'Top-10 books and classified tape need causal synchronization, executable size and arrival evidence.',
        'book_reclaim': 'Books and 1m ATR need causal synchronization; repeated 60-second trades within a day are not separate groups.',
        'funding_carry': 'Dated units/fees, funding timestamps and full cash reserve for both legs; continuous 24h exposure can merge groups.',
        'funding_cross': 'Both venues, synchronized units/funding, prefunded capital; two legs of one base are not two independent bases.',
        'spot_dislocation': 'Prefunded inventory and costed reverse route; venue legs do not diversify the economic base.',
        'basis_convergence': 'Causal 24h basis history, both-leg costs, units and funding; continuous positions can merge groups.',
        'long_put': 'Only BTC/ETH; 7-day Monday schedule conflicts with both concentration and current group-count rules. Verify native settlement, reserve and contract lots.',
        'cash_put': 'Only BTC/ETH; same concentration/group conflicts. Full strike reserve and whole-contract sizing may yield zero affordable positions; do not assume margin.',
        'put_spread': 'Only BTC/ETH; same concentration/group conflicts. Paired expiry, fills and native currency conversion required.',
        'fixed_grid': 'Weekly inventory, actual fills and final liquidation; count complete weekly positions, not each fill as an independent trade.',
        'gold_macd': 'One economic base despite rolled contract symbols. Instrument/lot/calendar required; closed-session valuation cannot be fabricated.',
        'dax_orb': 'One economic index despite contract symbols. Current session adapter rejects non-USD specs; native EUR signals and USD accounting need audited FX support.',
        'gap_continue': 'PIT equity universe, adjusted previous close, sessions and short borrow. Many same-session stocks do not create independent time groups.',
        'gap_fade': 'Same equity requirements; previous-close target and gap direction must be causal. Daily event groups, not ticker count.',
        'aave_lending': 'Single USDC reserve; serial 30-day positions give at most nine completed final trades. Liquidity/gas and depeg data remain necessary for a descriptive study.',
        'wallet_follow': 'Economic-wallet attribution and hop deduplication; PIT tokens, next-block selling evidence, gas/impact. Ten wallets are not ten economic bases.'}
    matrix = deepcopy(read(PARENT / 'matrix.json'))
    for row in matrix['models']:
        key = row['id']
        row['evidence'] = [r if r.startswith('../') else '../continuation-v19/'+r for r in row['evidence']]
        row['evidence'].append('protocol-audit.json')
        row['protocol_status'] = 'STRUCTURAL_ACCEPTANCE_CONFLICT' if key in constrained else 'NOT_RULED_OUT_NOT_YET_VALIDATED'
        row['candidate_path_status'] = 'UNAVAILABLE_IN_CURRENT_IMPLEMENTATION'
        row['protocol_issues'] = ['NO_INDEPENDENT_EXPOSURE_CERTIFICATION_PATH', 'NO_EXECUTION_CERTIFICATION_PATH']
        if key in constrained:
            row['protocol_issues'].append('ECONOMIC_BASE_CONCENTRATION_INCOMPATIBLE')
        if key in options:
            row['protocol_issues'].append('WEEKLY_GROUP_CEILING_19_BELOW_20')
        if key == 'aave_lending':
            row['protocol_issues'].append('SERIAL_SAMPLE_CEILING_9_BELOW_30')
        if key == 'dax_orb':
            row['protocol_issues'].append('NATIVE_CURRENCY_ACCOUNTING_UNRESOLVED')
        row['protocol_note'] = specific[key]
        row['next_step'] = ('Retain BLOCKED_DATA; no bulk acquisition for an unreachable candidate. Any model-specific acceptance revision needs a separate substantive decision.'
                            if key in constrained else 'Repair certification and canonical economic-base evidence handling first; do not repeat source probes or retune the signal.')
    matrix.update(protocol_audit_complete=True, bounded_source_and_protocol_audit_complete=True,
                  structural_acceptance_conflict_count=6, not_ruled_out_model_count=14,
                  candidate_path_implementation_blocked_count=20, program_complete=False,
                  research_goal_achieved=False, program_phase='BOUNDED_AUDIT_COMPLETE_NO_HISTORICAL_CANDIDATE')
    queue = deepcopy(read(PARENT / 'model-input-queue.json'))
    queue.update(models=matrix['models'], next_action_kind='TECHNICAL_CERTIFICATION_AND_BASE_IDENTITY_REPAIR_DESIGN',
                 next_priority=['canonical_economic_base_binding', 'independent_input_certification_contract'],
                 new_market_downloads_needed_for_next_action=False, all_model_protocol_audit_repeat_needed=False,
                 contract_revision_not_activated=sorted(constrained))
    audit = dict(schema='all_model_protocol_feasibility_v1', plan_hash=plan['plan_hash'],
        runtime_hash=runtime, model_count=20, bounds=bounds, synthetic_checks=checks,
        structural_conflict_models=[m['id'] for m in plan['models'] if m['id'] in constrained],
        unknown_feasibility_models=[m['id'] for m in plan['models'] if m['id'] not in constrained],
        all_models_candidate_path_blocked=True,
        findings=[
            dict(id='CONCENTRATION', severity='CONTRACT', description='With positive gross profits, at most two bases imply a largest share of at least 50%; one implies 100%. Both exceed 25%. This is a mathematical bound, not observed PnL.', evidence=[source(statistics.summarize), source(statistics.candidate_status), source(adapters.options)]),
            dict(id='WEEKLY_GROUPS', severity='CONTRACT', description='The option adapter starts Mondays at 00:00 and holds at least 7 days. Touching intervals merge. Thirty-eight completed weekly slots permit at most nineteen separated components in the fixed final period.', evidence=[source(adapters.options), source(statistics.temporal_group_ids), source(statistics.period_metrics)]),
            dict(id='LENDING_SAMPLE', severity='CONTRACT', description='Serial 30-day positions fit at most nine full times in 273 final days. No trade splitting or combining WF with final changes the frozen requirement.', evidence=[source(adapters.lending), source(statistics.period_metrics)]),
            dict(id='CERTIFICATION_PATH', severity='IMPLEMENTATION', description='validate always assigns unknown exposure. Replay returns proxy/uncertified execution. No implemented promotion path exists; directly flipping flags is not a valid repair.', evidence=[source(runner.validate), source(runner.evaluate), source(portfolio.replay_opportunities), source(statistics.candidate_status)]),
            dict(id='ECONOMIC_BASE_IDENTITY', severity='IMPLEMENTATION', description='Concentration uses raw symbol, not verified economic base. Contract rolls, venue aliases or token wrappers must not count as diversification.', evidence=[source(statistics.summarize)]),
            dict(id='NATIVE_INSTRUMENT_ACCOUNTING', severity='READINESS', description='Sessions reject non-USD specifications. Instrument/lot and native-currency signal versus USD valuation evidence must precede any DAX run. Gold and options also require exact instrument and settlement terms.', evidence=[source(adapters.sessions), source(adapters.gold), source(adapters.options)])],
        network_requests=0, historical_rows_read=0, market_evaluation_run=False,
        changes=dict(signal=False, periods=False, costs=False, risk=False, acceptance=False, runtime=False),
        caveats=['14 not ruled out is not 14 feasible/profitable/ready models.',
                 'Group count is an operational clustering rule, not proof of statistical independence.',
                 'Concentration is semantic: single-index contract aliases do not create new bases.',
                 'No historical returns, new data source search, or closed OOS were consumed.'])
    audit['audit_hash'] = canonical_hash(audit)
    proposal = dict(schema='protocol_repair_recommendation_v1', activated=False,
        same_scope_technical_next_steps=[
            'Bind canonical economic_base_id to verified instrument metadata; fail closed for missing or ambiguous mappings; regression for aliases and changed metadata.',
            'Design independently audited, hash-bound exposure/execution certificates. Unknown or previously used data must stay exploratory; never promote by a boolean alone.',
            'Require input/certificate/code hashes and coverage at the acceptance boundary. Preserve all existing signal/cost/risk/acceptance thresholds.'],
        separate_substantive_decisions=[
            dict(models=sorted(constrained), proposal='Keep these six models descriptive-only under the current program. If candidacy is desired, preregister model-appropriate concentration/sample rules separately before outcomes.', auto_apply=False),
            dict(models=sorted(options), proposal='Explicitly decide the temporal grouping contract; changing > to >= just to obtain twenty groups is not an authorized technical fix.', auto_apply=False),
            dict(models=['aave_lending'], proposal='Do not split one 30-day deposit into pseudo-trades or extend final dates to manufacture sample size.', auto_apply=False)],
        prohibited_shortcuts=['lowering thresholds silently', 'current metadata substituted for historical', 'dropping blocked tests from Holm family', 'new long collectors', 'paid data or private credentials'])
    provenance = dict(schema='protocol_audit_provenance_v1', parent_commit='1cd08ea70356025da8efc8c7f0b0a9a95522ea9e',
        parent_index_sha256=file_hash(PARENT/'evidence-index.json'), plan_file_sha256=file_hash(PLAN_PATH),
        plan_hash=plan['plan_hash'], runtime_hash=runtime, runtime_binding=runtime_binding(),
        audit_code_sha256=file_hash(Path(__file__)), full_previous_suite_rerun=False,
        inherited_suite_tests=213, fresh_synthetic_assertions=len(checks),
        financial_execution_authorized=False, listing_project_untouched=True,
        source='Only frozen local plan/code and completed documentary checkpoints')
    return {'protocol-audit.json': audit, 'matrix.json': matrix, 'model-input-queue.json': queue,
            'decision-proposal.json': proposal, 'publication-provenance.json': provenance}


def main():
    require(sys.argv[1:] in (['--write'], ['--check']), 'Use --write or --check')
    records = build()
    if sys.argv[1] == '--write':
        for name, value in records.items():
            write_immutable(HERE/name, value)
    else:
        for name, expected in records.items():
            require(read(HERE/name) == expected, 'Checkpoint drift: '+name)
    print(json.dumps(dict(status='VERIFIED', fresh_synthetic_assertions=len(records['protocol-audit.json']['synthetic_checks']),
        structural_conflicts=6, other_models_not_proven_feasible=14, candidate_path_blocked=20,
        market_evaluation_run=False, runtime_changed=False, audit_hash=records['protocol-audit.json']['audit_hash']), indent=2))


if __name__ == '__main__':
    main()
