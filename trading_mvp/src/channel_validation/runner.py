"""Bounded, offline stages. Readiness is deliberately separate from evaluation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import unittest

from .contract import ROOT, PLAN_PATH, OUTPUT_ROOT, build_plan, canonical_hash, runtime_binding, validate_plan
from .data import ts, validate_manifest, write_immutable
from .models import candle_replay
from .adapters import MissingEvidence, run_specialized
from .portfolio import replay_opportunities
from .statistics import holm, period_metrics, walk_forward, candidate_status


def sealed(value, field):
    value[field] = canonical_hash(value)
    return value


def assert_sealed(value, field):
    if value.get(field) != canonical_hash({k: v for k, v in value.items() if k != field}):
        raise ValueError(f'{field} mismatch')


def inventory(plan, roots, check=lambda: None):
    validate_plan(plan)
    locations = []
    for root in roots:
        check()
        path = Path(root)
        # Do not follow junctions or crawl old run output. A manifest is required.
        candidates = sorted(path.glob('*.channel-input.json'))[:100] if path.is_dir() else []
        locations.append(dict(path=str(path), status='AVAILABLE' if path.is_dir() else 'UNAVAILABLE',
                              input_manifests=[str(p) for p in candidates if p.is_file()]))
    return sealed(dict(stage='inventory', plan_hash=plan['plan_hash'], roots=locations,
                       models=[dict(id=m['id'], required_kinds=m['required_kinds'], status='NOT_VALIDATED')
                               for m in plan['models']],
                       note='Availability is not data validity. Public history not downloaded by inventory.'), 'inventory_hash')


def load_inputs(plan, input_path, check):
    if input_path is None:
        return None, []
    path = Path(input_path)
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    if manifest.get('plan_hash') != plan['plan_hash']:
        raise ValueError('Input manifest bound to a different research plan')
    loaded = validate_manifest(manifest, path.parent, plan['resource_limits']['max_input_bytes'],
                               plan['resource_limits']['max_rows'], check)
    return manifest, loaded


def model_inputs(model, loaded):
    selected = [d for d in loaded if d['entry'].get('market') == model['market']
                and model['id'] in d['entry'].get('model_ids', [])]
    out = {}
    for dataset in selected:
        kind = dataset['entry']['kind']
        out.setdefault(kind, []).extend(dataset['rows'])
    for kind, rows in out.items():
        rows.sort(key=lambda r: (ts(r['ts']), r['symbol'], str(r.get('venue', ''))))
        keys = [(r['symbol'], r.get('venue'), r.get('long_venue'), r.get('short_venue'),
                 r.get('sequence'), r.get('wallet'), ts(r['ts'])) for r in rows]
        if len(keys) != len(set(keys)):
            raise ValueError('Overlapping datasets / duplicate observations')
    return out, selected


def validate(plan, inv, input_path, check=lambda: None):
    validate_plan(plan)
    assert_sealed(inv, 'inventory_hash')
    if inv['plan_hash'] != plan['plan_hash']:
        raise ValueError('Inventory plan mismatch')
    manifest, loaded = load_inputs(plan, input_path, check)
    models = []
    for model in plan['models']:
        check()
        data, selected = model_inputs(model, loaded)
        missing = [kind for kind in model['required_kinds'] if not data.get(kind)]
        coverage = {kind: dict(first=min(ts(r['ts']) for r in rows), last=max(ts(r.get('end_ts', r['ts'])) for r in rows), rows=len(rows))
                    for kind, rows in data.items()}
        models.append(dict(id=model['id'], status='BLOCKED_DATA' if missing else 'READY_TO_EVALUATE',
                           missing_kinds=missing, coverage=coverage,
                           datasets=[d['entry']['id'] for d in selected],
                           exposure='UNKNOWN_OR_PREVIOUSLY_VIEWED',
                           independent_oos_certified=False))
    return sealed(dict(stage='validate', plan_hash=plan['plan_hash'], inventory_hash=inv['inventory_hash'],
                       input_manifest_hash=manifest['manifest_hash'] if manifest else None,
                       runtime_binding=runtime_binding(), models=models, creates_trading_results=False), 'validation_hash')


def _partial_periods(plan, readiness):
    # Missing spans cannot be hidden by silently moving a testing window.
    periods = plan['periods']
    coverage = readiness['coverage']
    return [label for label in ('development', 'walk_forward', 'final')
            if any(v['first'] > ts(periods[label][0]+'T00:00:00Z') or
                   v['last'] < ts(periods[label][1]+'T00:00:00Z')-86400 for v in coverage.values())]


def restrict_observed_days(replay, model, data):
    primary = 'books' if model['id'] == 'fixed_grid' else model['required_kinds'][0]
    rows = data[primary]
    first = min(ts(r['ts']) for r in rows)
    last = max(ts(r.get('end_ts', r['ts'])) for r in rows)
    # Never turn months outside actual archive coverage into zero-return days.
    replay['daily_equity'] = {d: v for d, v in replay['daily_equity'].items()
                              if first <= ts(d+'T00:00:00Z') and ts(d+'T00:00:00Z')+86400 <= last}
    return replay


def evaluate(plan, validation, input_path, check=lambda: None):
    validate_plan(plan)
    assert_sealed(validation, 'validation_hash')
    if validation['plan_hash'] != plan['plan_hash'] or validation['runtime_binding'] != runtime_binding():
        raise ValueError('Stale validation / changed implementation')
    manifest, loaded = load_inputs(plan, input_path, check)
    if validation['input_manifest_hash'] != (manifest['manifest_hash'] if manifest else None):
        raise ValueError('Input changed since validation, even if the row count is unchanged')
    results, pvalues = [], {}
    ready_by_id = {r['id']: r for r in validation['models']}
    for model in plan['models']:
        check()
        ready = ready_by_id[model['id']]
        r = dict(id=model['id'], number=model['number'], model_hash=model['model_hash'],
                 status=ready['status'], metrics=None, tests=[], limitations=[], next_step='')
        if ready['status'] != 'READY_TO_EVALUATE':
            r.update(missing_kinds=ready['missing_kinds'],
                     next_step='Provide verified free historical files and an input manifest; no forward collector.',
                     limitations=['No eligible inputs in this environment; not a negative strategy verdict.'])
            results.append(r)
            continue
        data, _ = model_inputs(model, loaded)
        try:
            if model['number'] <= 4:
                bars = data['bars_1h' if model['number'] == 1 else 'bars_4h']
                normal = candle_replay(model, bars, data['pit_universe'], plan, check=check)
                stress = candle_replay(model, bars, data['pit_universe'], plan, stress=True, check=check)
                normal = restrict_observed_days(normal, model, data)
                stress = restrict_observed_days(stress, model, data)
                r.update(oos=period_metrics(normal, *plan['periods']['final']),
                         stress_oos=period_metrics(stress, *plan['periods']['final']), folds=walk_forward(normal),
                         metrics=period_metrics(normal, *plan['periods']['development']),
                         trades=normal['trades'], daily_equity=normal['daily_equity'],
                         open_positions=normal['open_positions'], execution_quality=normal['execution_quality'],
                         exposure=ready['exposure'], tests=['causal_replay', 'costs', 'stress', 'fixed_five_folds', 'block_bootstrap'])
                r['partial_periods'] = _partial_periods(plan, ready)
                if r['partial_periods']:
                    r['limitations'].append('Incomplete fixed historical periods: '+', '.join(r['partial_periods']))
                r['limitations'].extend(['Candle fills are exploratory, not certified executable quotes.',
                                         'Exposure history has not been independently certified as unseen.'])
                if r['oos']['bootstrap_p'] is not None:
                    pvalues[r['id']] = r['oos']['bootstrap_p']
                r['status'] = 'EXPLORATORY_ONLY'
            else:
                opportunities, exposures = run_specialized(model, data, check)
                normal = replay_opportunities(opportunities, exposures, plan, plan['periods']['development'][0], plan['periods']['final'][1], check=check)
                stress = replay_opportunities(opportunities, exposures, plan, plan['periods']['development'][0], plan['periods']['final'][1], stress=True, check=check)
                normal = restrict_observed_days(normal, model, data)
                stress = restrict_observed_days(stress, model, data)
                r.update(status='EXPLORATORY_ONLY',
                         metrics=period_metrics(normal, *plan['periods']['development']),
                         oos=period_metrics(normal, *plan['periods']['final']), folds=walk_forward(normal),
                         stress_oos=period_metrics(stress, *plan['periods']['final']),
                         trades=normal['trades'], daily_equity=normal['daily_equity'],
                         open_positions=normal['open_positions'], exposure=ready['exposure'],
                         execution_quality=normal['execution_quality'],
                         partial_periods=_partial_periods(plan, ready),
                         tests=['fixed_signal_and_leg_economics', 'cash_reserved_portfolio', 'observed_daily_valuation', 'stress', 'fixed_five_folds', 'block_bootstrap'],
                         limitations=['Normalization, as-of completeness and execution evidence need independent audit before candidacy.'])
                if r['oos']['bootstrap_p'] is not None:
                    pvalues[r['id']] = r['oos']['bootstrap_p']
            r['next_step'] = 'Resolve listed data/execution/portfolio evidence gaps without retuning the signal.'
        except (MissingEvidence, ValueError, KeyError) as exc:
            r.update(status='BLOCKED_DATA_QUALITY', metrics=None, tests=['input_validation_or_adapter_rejected'],
                     limitations=[str(exc)], next_step='Repair/complete provenance or normalized data; do not infer missing prices.')
        results.append(r)
    adjusted = holm(pvalues, plan['statistics']['family_size'])
    for r in results:
        r['holm_adjusted_p'] = adjusted.get(r['id'])
        if 'oos' in r:
            r['status'] = candidate_status(r, adjusted.get(r['id']), plan)
    return sealed(dict(stage='evaluate', plan_hash=plan['plan_hash'],
                       input_manifest_hash=validation['input_manifest_hash'], runtime_binding=runtime_binding(),
                       validation_hash=validation['validation_hash'], family_size=20, models=results,
                       financial_execution_authorized=False), 'result_hash')


def report(plan, inv, validation, evaluation):
    for value, key in ((inv, 'inventory_hash'), (validation, 'validation_hash'), (evaluation, 'result_hash')):
        assert_sealed(value, key)
        if value['plan_hash'] != plan['plan_hash']:
            raise ValueError('Report plan mismatch')
    if evaluation['validation_hash'] != validation['validation_hash']:
        raise ValueError('Report provenance mismatch')
    lines = ['# Historical Strategy Validation', '',
             'Research only. No live permission and no claim of a profitable strategy.', '',
             'A blocked model is not a rejected strategy. Readiness is not a backtest.', '',
             f"Plan: `{plan['plan_hash']}`", f"Result: `{evaluation['result_hash']}`", '',
             '| # | Model | Data / checks | Result | Limitations / next step |',
             '|---|---|---|---|---|']
    for model, r in zip(plan['models'], evaluation['models']):
        details = ', '.join(r.get('missing_kinds', r['tests']))
        limitation = '; '.join(r['limitations']).replace('|', '/')
        lines.append(f"| {model['number']} | {model['title']} | {details} | {r['status']} | {limitation} {r['next_step']} |")
    lines += ['', '## Implementation Boundary', '',
              'Models 1-4 have exploratory candle replay. Models 5-20 use instrument-specific adapters',
              'and cash-reserved portfolio replay with mandatory observed marks. Missing daily valuation,',
              'funding/contract provenance, or historical universe evidence cannot be filled with assumptions.', '',
              '## Excluded', '', 'Listing Momentum: separate project. Premarket-depth: unchanged.',
              'Old rejected runs: not reopened. AI: no reproducible specification. Prop: risk overlay only.', '',
              '## Source Availability', '', 'A local missing archive does not prove public history is unavailable.',
              'See source-availability.md. No schedule, permanent collector or paid data purchase was created.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['freeze', 'preflight', 'verify', 'sources', 'inventory', 'validate', 'evaluate', 'report', 'pipeline'])
    parser.add_argument('--input-manifest')
    parser.add_argument('--evaluation', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--archive', action='append')
    parser.add_argument('--max-runtime-sec', type=int, default=1800)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.max_runtime_sec <= 1800:
        parser.error('Runtime must be 1..1800 seconds')
    deadline = time.monotonic()+args.max_runtime_sec

    def check():
        if time.monotonic() > deadline or (args.stop_file and args.stop_file.exists()):
            raise TimeoutError('Deadline/stop request, no automatic retry')

    plan = build_plan()
    if args.stage == 'freeze':
        write_immutable(PLAN_PATH, plan)
        print(json.dumps(dict(status='FROZEN', plan_hash=plan['plan_hash'], path=str(PLAN_PATH))))
        return 0
    validate_plan(json.loads(PLAN_PATH.read_text(encoding='utf-8')))
    if args.stage == 'preflight':
        print(json.dumps(dict(status='READY_OFFLINE_ONLY', plan_hash=plan['plan_hash'], runtime=runtime_binding(),
                              network=False, model_count=20, creates_trading_results=False)))
        return 0
    if args.stage == 'verify':
        suite = unittest.defaultTestLoader.discover(str(ROOT/'trading_mvp/tests'), pattern='test_channel_validation.py')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if args.output:
            write_immutable(args.output/'tests.json', dict(tests=result.testsRun, failures=len(result.failures),
                                                         errors=len(result.errors), successful=result.wasSuccessful(),
                                                         runtime_binding=runtime_binding()))
        return 0 if result.wasSuccessful() else 1
    if not args.output:
        parser.error('Explicit isolated output namespace required')
    if args.stage == 'sources':
        from .sources import download_samples
        download_samples(args.output/'public-history-sample', check)
        return 0
    if args.stage == 'report':
        if not args.evaluation:
            parser.error('Report requires --evaluation <immutable evaluation.json>')
        origin = args.evaluation.parent
        inv = json.loads((origin/'inventory.json').read_text(encoding='utf-8'))
        val = json.loads((origin/'validation.json').read_text(encoding='utf-8'))
        ev = json.loads(args.evaluation.read_text(encoding='utf-8'))
        if ev['runtime_binding'] != runtime_binding():
            raise ValueError('Stale report code binding')
        manifest, _ = load_inputs(plan, args.input_manifest, check)
        if (manifest['manifest_hash'] if manifest else None) != ev['input_manifest_hash']:
            raise ValueError('Report input binding changed/unavailable')
        markdown = report(plan, inv, val, ev)
        args.output.mkdir(parents=True, exist_ok=True)
        with (args.output/'report.md').open('xb') as f:
            f.write(markdown.encode('utf-8'))
        write_immutable(args.output/'report-binding.json', dict(result_hash=ev['result_hash'], runtime_binding=runtime_binding()))
        return 0
    if args.input_manifest and args.output.resolve().is_relative_to(Path(args.input_manifest).parent.resolve()):
        parser.error('Output must not be inside the immutable input namespace')
    inv = inventory(plan, args.archive or [r'E:\ZolotyayLopata-data', str(ROOT/'trading_mvp/exports/trading-mvp/normalized')], check)
    write_immutable(args.output/'inventory.json', inv)
    if args.stage == 'inventory':
        return 0
    val = validate(plan, inv, args.input_manifest, check)
    write_immutable(args.output/'validation.json', val)
    if args.stage == 'validate':
        return 0
    ev = evaluate(plan, val, args.input_manifest, check)
    write_immutable(args.output/'evaluation.json', ev)
    if args.stage == 'pipeline':
        markdown = report(plan, inv, val, ev)
        path = args.output/'report.md'
        raw = markdown.encode('utf-8')
        if path.exists() and path.read_bytes() != raw:
            raise FileExistsError('Immutable report differs')
        if not path.exists():
            with path.open('xb') as f:
                f.write(raw)
    print(json.dumps(dict(status='COMPLETE', model_count=20, result_hash=ev['result_hash'],
                          statuses={r['id']: r['status'] for r in ev['models']})))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps(dict(status='STOPPED_INCOMPLETE', error=str(exc), retry_authorized=False)), flush=True)
        raise
