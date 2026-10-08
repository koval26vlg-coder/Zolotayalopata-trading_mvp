import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from channel_validation.contract import build_plan, canonical_hash, validate_plan, file_hash
from channel_validation.data import validate_manifest, write_immutable, select_universe, validate_row, ts
from channel_validation.models import (confirmed_pivots, atr, bar_exit, option_pnl, pair_pnl, grid_fill,
                                      candle_replay, causal_funding_forecast, choose_option, wallet_ranking, lending_pnl)
from channel_validation.adapters import (MissingEvidence, pair_economics, paired, wallets, grid, run_specialized, first_after)
from channel_validation.statistics import holm, bootstrap_pvalue, summarize, temporal_groups, candidate_status
from channel_validation.runner import inventory, validate, evaluate, report, main
from channel_validation.sources import sample_requests, inspect_csv_gzip
from channel_validation.portfolio import replay_opportunities
from channel_validation.gate_history import requests_plan, normalize_rest, archive_comparison, read_bounded
from channel_validation.archive_audit import discover, inspect_pit_state
from channel_validation.gate_catalog import parse_catalog, aggregate_archive, checked_json
from channel_validation.gate_survivorship import (request_plan as survivorship_plan, parse_symbols,
                                                  parse_archive, conclusions)
from channel_validation.gate_trades import summarize_trades, reconcile as reconcile_trades
from channel_validation.gate_metadata import parse_metadata, request_plan as metadata_plan
from channel_validation.okx_history import (parse_catalog as parse_okx_catalog, validate_range, inspect_prefix,
                                            request_plan as okx_plan, DAY, DAY_MS, CAP)
from channel_validation.okx_stream import Book, census, contract_id
from channel_validation.okx_acquire import stream_download, MAX_DOWNLOAD


def universe(at, members=('BTC', 'ETH')):
    return dict(ts=at, available_at=at, symbol='GATE_UNIVERSE', members=list(members), window_end_ts=at,
                membership_complete=True, types_asof=True,
                ranking_candidates=[dict(base=s, venue='gate', quote='USDT', active_asof=True, asset_type='native',
                                         type_available_at=at-1, volume_window_end=at,
                                         daily_quote_turnover=[100.]*30) for s in members])


def quote(at, symbol='X', bid=99, ask=100, **extra):
    return dict(ts=at, available_at=at, symbol=symbol, bid=bid, ask=ask, bid_size=1000, ask_size=1000,
                fee_bps=10, fee_source='synthetic-dated-schedule', **extra)


class ContractTests(unittest.TestCase):
    def test_exact_twenty_and_no_execution(self):
        p = build_plan()
        self.assertEqual(list(range(1, 21)), [m['number'] for m in p['models']])
        self.assertEqual(20, p['statistics']['family_size'])
        self.assertFalse(p['permissions']['live_orders'])
        self.assertFalse(p['permissions']['schedules'])
        validate_plan(p)

    def test_changed_contract_rejected(self):
        p = build_plan()
        p['models'][0]['parameters']['market_drop'] = -0.02
        with self.assertRaises(ValueError):
            validate_plan(p)


class ModelTests(unittest.TestCase):
    def test_pivot_only_after_two_right_bars(self):
        rows = [dict(high=x+1, low=x, close=x+0.5) for x in [4, 3, 1, 3, 4, 5]]
        lows, highs = confirmed_pivots(rows)
        self.assertIsNone(lows[3])
        self.assertEqual((2, 1), lows[4])
        self.assertEqual(lows[:5], confirmed_pivots(rows[:5])[0])

    def test_atr_warmup_no_backfill(self):
        rows = [dict(high=12, low=10, close=11) for _ in range(20)]
        a = atr(rows)
        self.assertIsNone(a[12])
        self.assertEqual(2, a[13])

    def test_stop_wins_ambiguous_and_gap(self):
        self.assertEqual((90, 'STOP'), bar_exit(dict(open=100, high=120, low=80), 90, 110, 1))
        self.assertEqual((80, 'STOP'), bar_exit(dict(open=80, high=120, low=70), 90, 110, 1))

    def test_short_gap(self):
        self.assertEqual((125, 'STOP'), bar_exit(dict(open=125, high=130, low=70), 110, 90, -1))

    def test_option_contract_multiplier_and_all_legs(self):
        legs = [dict(side=1, quantity=2, multiplier=0.1, entry_ask=10, entry_bid=9,
                     exit_bid=15, exit_ask=16, entry_fee=0.1, exit_fee=0.1)]
        self.assertAlmostEqual(0.6, option_pnl(legs))
        legs[0]['multiplier'] = 0
        with self.assertRaises(ValueError):
            option_pnl(legs)

    def test_pair_all_orders_funding_timing(self):
        result = pair_pnl(100, 100, 101, 99, 1, 0.001, [(10, 0.01), (20, 0.02)], 10, 20)
        self.assertAlmostEqual(3.6, result)

    def test_grid_touch_not_fill(self):
        self.assertFalse(grid_fill('buy', 100, dict(low=99, high=101)))
        self.assertTrue(grid_fill('buy', 100, dict(ask=99, ask_size=2), quantity=1))


class StatisticsTests(unittest.TestCase):
    def test_missing_hypotheses_still_family_twenty(self):
        self.assertAlmostEqual(0.02, holm({'m1': 0.001}, 20)['m1'])
        self.assertEqual(1, holm({'m1': 0.2}, 20)['m1'])

    def test_bootstrap_deterministic_and_nonpositive(self):
        self.assertEqual(bootstrap_pvalue([-1.0]*30), 1)
        self.assertEqual(bootstrap_pvalue([1.0]*30), bootstrap_pvalue([1.0]*30))

    def test_no_trades_not_zero_expectancy(self):
        r = summarize([], {}, 10000)
        self.assertIsNone(r['expectancy'])
        self.assertIsNone(r['profit_factor'])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = build_plan()

    def test_missing_archive_is_not_created(self):
        missing = self.root/'missing'
        r = inventory(self.plan, [missing])
        self.assertFalse(missing.exists())
        self.assertEqual('UNAVAILABLE', r['roots'][0]['status'])
        self.assertEqual(20, len(r['models']))

    def test_full_twenty_blocked_not_fake_metrics(self):
        i = inventory(self.plan, [self.root/'missing'])
        v = validate(self.plan, i, None)
        e = evaluate(self.plan, v, None)
        self.assertEqual(20, len(e['models']))
        self.assertTrue(all(m['status'] == 'BLOCKED_DATA' and m['metrics'] is None for m in e['models']))
        self.assertIn('BLOCKED_DATA', report(self.plan, i, v, e))
        self.assertEqual(e, evaluate(self.plan, v, None))

    def test_exclusive_artifact_write(self):
        p = self.root/'one.json'
        write_immutable(p, {'a': 1})
        write_immutable(p, {'a': 1})
        with self.assertRaises(FileExistsError):
            write_immutable(p, {'a': 2})

    def test_partial_dataset_rejected(self):
        with self.assertRaises(ValueError):
            validate_manifest({'schema': 'channel_input_v1', 'status': 'STOPPED_INCOMPLETE'}, self.root)

    def make_manifest(self, close=10):
        path = self.root/'bars.jsonl'
        row = dict(ts=ts('2023-01-01T00:00:00Z'), available_at=ts('2023-01-01T01:00:00Z'),
                   end_ts=ts('2023-01-01T01:00:00Z'), symbol='BTC', open=10, high=12, low=9,
                   close=close, volume=1, quote_volume=10)
        path.write_text(json.dumps(row)+'\n', encoding='utf-8')
        manifest = dict(schema='channel_input_v1', status='COMPLETE', plan_hash=self.plan['plan_hash'],
                        datasets=[dict(id='btc', kind='bars_1h', market='gate', model_ids=['relative_strength'],
                                       status='COMPLETE', source_access='PUBLIC', path='bars.jsonl', rows=1,
                                       sha256=file_hash(path))])
        manifest['manifest_hash'] = canonical_hash(manifest)
        mp = self.root/'one.channel-input.json'
        mp.write_text(json.dumps(manifest), encoding='utf-8')
        return mp, manifest

    def test_same_rows_changed_content_invalidates_result(self):
        path, _ = self.make_manifest()
        inv = inventory(self.plan, [self.root])
        val = validate(self.plan, inv, path)
        first = evaluate(self.plan, val, path)
        self.make_manifest(11)
        with self.assertRaisesRegex(ValueError, 'changed since validation'):
            evaluate(self.plan, val, path)
        second = evaluate(self.plan, validate(self.plan, inv, path), path)
        self.assertNotEqual(first['result_hash'], second['result_hash'])

    def test_corrupted_input_same_rows_rejected(self):
        path, manifest = self.make_manifest()
        (self.root/'bars.jsonl').write_text((self.root/'bars.jsonl').read_text().replace('10', '11'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            validate_manifest(manifest, self.root)

    def test_inventory_and_validate_do_not_create_trade_artifacts(self):
        path, _ = self.make_manifest()
        before = sorted(p.name for p in self.root.iterdir())
        validate(self.plan, inventory(self.plan, [self.root]), path)
        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))

    def test_report_rejects_unbound_result(self):
        inv = inventory(self.plan, [])
        val = validate(self.plan, inv, None)
        result = evaluate(self.plan, val, None)
        result['models'][0]['status'] = 'HISTORICAL_CANDIDATE_NOT_LIVE'
        with self.assertRaises(ValueError):
            report(self.plan, inv, val, result)

    def test_private_input_rejected(self):
        path, manifest = self.make_manifest()
        manifest['datasets'][0]['source_access'] = 'PRIVATE'
        manifest.pop('manifest_hash')
        manifest['manifest_hash'] = canonical_hash(manifest)
        with self.assertRaisesRegex(ValueError, 'Partial/private'):
            validate_manifest(manifest, self.root)

    def test_timeout_callback_not_swallowed(self):
        def stop():
            raise TimeoutError('synthetic budget stop')
        with self.assertRaises(TimeoutError):
            inventory(self.plan, [self.root], stop)

    def test_report_stage_does_not_evaluate_again(self):
        from unittest.mock import patch
        inv = inventory(self.plan, [])
        val = validate(self.plan, inv, None)
        ev = evaluate(self.plan, val, None)
        for name, value in [('inventory', inv), ('validation', val), ('evaluation', ev)]:
            write_immutable(self.root/(name+'.json'), value)
        with patch('channel_validation.runner.evaluate', side_effect=AssertionError('report must not run trades')):
            self.assertEqual(0, main(['report', '--evaluation', str(self.root/'evaluation.json'), '--output', str(self.root/'reported')]))
        self.assertTrue((self.root/'reported/report.md').is_file())
        self.assertFalse((self.root/'reported/evaluation.json').exists())

    def test_stale_code_binding_rejected(self):
        from unittest.mock import patch
        val = validate(self.plan, inventory(self.plan, []), None)
        with patch('channel_validation.runner.runtime_binding', return_value={'changed': '0'*64}):
            with self.assertRaisesRegex(ValueError, 'Stale validation'):
                evaluate(self.plan, val, None)


class CausalTests(unittest.TestCase):
    def test_future_universe_evidence_rejected(self):
        u = universe(100)
        u['ranking_candidates'][0]['type_available_at'] = 101
        with self.assertRaisesRegex(ValueError, 'Future'):
            select_universe(u, 100)

    def test_delisted_removed_not_survivor_backfilled(self):
        old = universe(100, ('BTC', 'ETH', 'OLD'))
        new = universe(200, ('BTC', 'ETH'))
        new['ranking_candidates'].append(dict(old['ranking_candidates'][2], active_asof=False))
        self.assertIn('OLD', select_universe(old, 100))
        self.assertNotIn('OLD', select_universe(new, 200))
        self.assertIn('OLD', select_universe(old, 100))

    def test_stablecoin_excluded(self):
        u = universe(100)
        u['ranking_candidates'].append(dict(u['ranking_candidates'][0], base='USDC', asset_type='stablecoin'))
        self.assertNotIn('USDC', select_universe(u, 100))

    def test_signal_enters_next_bar_not_signal_close(self):
        from unittest.mock import patch
        plan = build_plan()
        start = ts('2023-01-01T00:00:00Z')
        bars = [dict(ts=start+i*3600, end_ts=start+(i+1)*3600, available_at=start+(i+1)*3600,
                     symbol=s, open=100, close=100, high=101, low=99) for s in ('BTC', 'ETH') for i in range(65)]
        with patch('channel_validation.models.candle_signal', side_effect=lambda k,r,f,i,b: 1 if i == 25 and r[0]['symbol'] == 'ETH' else None):
            result = candle_replay(plan['models'][0], bars, [universe(start)], plan)
        self.assertEqual(start+26*3600, result['trades'][0]['entry_ts'])
        self.assertEqual(start+50*3600, result['trades'][0]['exit_ts'])

    def test_entry_rejects_future_benchmark_publication(self):
        plan = build_plan()
        start = ts('2023-01-01T00:00:00Z')
        bars = []
        for symbol in ('BTC', 'ETH'):
            for i in range(50):
                price = 100-i if symbol == 'BTC' else 100
                bars.append(dict(ts=start+i*3600, end_ts=start+(i+1)*3600,
                                 available_at=start+(i+1)*3600+(864000 if symbol == 'BTC' else 0),
                                 symbol=symbol, open=price, close=price, high=price+1, low=price-1))
        result = candle_replay(plan['models'][0], bars, [universe(start)], plan)
        self.assertFalse(result['trades'])
        self.assertFalse(result['open_positions'])

    def test_delayed_historical_bar_not_used_in_indicator(self):
        from unittest.mock import patch
        plan = build_plan()
        start = ts('2023-01-01T00:00:00Z')
        bars = [dict(ts=start+i*3600, end_ts=start+(i+1)*3600, available_at=start+(i+1)*3600,
                     symbol=s, open=100, close=100, high=101, low=99) for s in ('BTC', 'ETH') for i in range(65)]
        next(r for r in bars if r['symbol'] == 'ETH' and r['ts'] == start+5*3600)['available_at'] = start+100*3600
        with patch('channel_validation.models.candle_signal', side_effect=lambda k,r,f,i,b: 1 if i == 25 and r[0]['symbol'] == 'ETH' else None):
            result = candle_replay(plan['models'][0], bars, [universe(start)], plan)
        self.assertFalse(result['trades'])
        self.assertFalse(result['open_positions'])

    def test_funding_forecast_uses_settled_published_period_only(self):
        rows = [dict(symbol='X', venue='gate', rate=.01, period_seconds=28800, settlement_ts=100, available_at=100),
                dict(symbol='X', venue='gate', rate=.50, period_seconds=28800, settlement_ts=200, available_at=200)]
        self.assertAlmostEqual(.03, causal_funding_forecast(rows, 150, 'X', 'gate'))

    def test_session_dst_offsets_preserved(self):
        a = ts('2026-03-27T09:00:00+01:00')
        b = ts('2026-03-30T09:00:00+02:00')
        self.assertEqual(71*3600, b-a)
        with self.assertRaises(ValueError):
            ts('2026-03-30T09:00:00')

    def test_late_quote_is_not_used_retroactively(self):
        row = quote(100)
        row['available_at'] = 101
        self.assertIsNone(first_after([row], 100))


class EconomicsTests(unittest.TestCase):
    def test_pair_per_leg_fees_and_actual_mark_funding(self):
        entry = dict(ts=10, symbol='X', long_ask=100, long_bid=99, short_bid=101, short_ask=102,
                     long_venue='gate', short_venue='mexc', long_market='perp', short_market='perp',
                     long_fee_bps=10, short_fee_bps=20, long_impact=0, short_impact=0,
                     fee_source='fixture', base_units_verified=True)
        end = dict(entry, ts=30, long_bid=105, long_ask=106, short_ask=100, short_bid=99)
        events = [dict(symbol='X', venue='mexc', settlement_ts=10, rate=.9, mark_price=500),
                  dict(symbol='X', venue='mexc', settlement_ts=20, rate=.01, mark_price=120),
                  dict(symbol='X', venue='gate', settlement_ts=25, rate=.005, mark_price=110)]
        self.assertAlmostEqual(6+1.2-.55-.1-.202-.105-.2, pair_economics(entry, end, 1, events, 'funding_cross'))
        self.assertLess(pair_economics(entry, end, 1, events, 'funding_cross', True),
                        pair_economics(entry, end, 1, events, 'funding_cross'))
        del events[1]['mark_price']
        with self.assertRaises(MissingEvidence):
            pair_economics(entry, end, 1, events, 'funding_cross')

    def test_option_selection_no_future_chain(self):
        chain = [dict(underlying='BTC', option_type='put', ts=100, available_at=100,
                      expiry_ts=100+30*86400, strike=100, underlying_spot=100, symbol='ATM'),
                 dict(underlying='BTC', option_type='put', ts=100, available_at=101,
                      expiry_ts=100+30*86400, strike=90, underlying_spot=100, symbol='FUTURE')]
        self.assertEqual('ATM', choose_option(chain, 'BTC', 100, .9)['symbol'])

    def test_lending_depeg_and_unavailable_withdrawal(self):
        self.assertAlmostEqual(-51.5, lending_pnl(1000, 1, 1.01, 1, .95, 11, 2000))
        with self.assertRaisesRegex(ValueError, 'Withdrawal'):
            lending_pnl(1000, 1, 1.01, 1, 1, 1, 999)

    def test_future_wallet_purchases_do_not_affect_rank(self):
        rows = [dict(wallet='A', side='buy', ts=100, available_at=100, quote_usd=10),
                dict(wallet='B', side='buy', ts=201, available_at=201, quote_usd=1000)]
        self.assertEqual(['A'], wallet_ranking(rows, 200))

    def test_unsellable_token_stays_open_once(self):
        at = ts('2023-02-01T00:00:00Z')
        swaps = [dict(wallet='A', token='T', symbol='T', chain='ethereum', side='buy', ts=at-10,
                      available_at=at-10, quote_usd=100, quantity=1, block_number=1),
                 dict(wallet='A', token='T', symbol='T', chain='ethereum', side='buy', ts=at+10,
                      available_at=at+10, quote_usd=100, quantity=1, block_number=10)]
        # The first month has no prior selected wallet; second month ranks A.
        u = [dict(ts=ts('2023-01-01T00:00:00Z'), available_at=ts('2023-01-01T00:00:00Z'), members=['T']),
             dict(ts=at, available_at=at, members=['T'])]
        q1 = quote(at+20, 'T', token='T', block_number=11, sellable=True, gas_usd=1)
        q2 = quote(at+20+86400, 'T', token='T', block_number=100, sellable=False, gas_usd=1)
        trades, exposed = wallets(build_plan()['models'][19], dict(dex_swaps=swaps, execution_quotes=[q1,q2], token_universe=u), lambda: None)
        self.assertFalse(trades)
        self.assertEqual(1, len(exposed))

    def test_grid_truncated_week_not_profit(self):
        start = ts('2023-01-02T00:00:00Z')
        bars = [dict(ts=start-(15-i)*86400, end_ts=start-(14-i)*86400, available_at=start-(14-i)*86400,
                     symbol='BTC', open=100, close=100, high=101, low=99) for i in range(14)]
        quotes = [quote(start, 'BTC', bid=99.9, ask=100.1), quote(start+3600, 'BTC', bid=101, ask=101.1)]
        trades, exposed = grid(build_plan()['models'][13], dict(bars_1d=bars, books=quotes, pit_universe=[universe(start)]), lambda: None)
        self.assertFalse(trades)
        self.assertEqual(1, len(exposed))

    def test_negative_depth_rejected(self):
        r = quote(100, bid_notional_top10=1, ask_notional_top10=1)
        r['ask_size'] = -1
        with self.assertRaises(ValueError):
            validate_row(r, 'books')

    def test_all_specialized_models_have_dispatch(self):
        for model in build_plan()['models'][4:]:
            data = {kind: [] for kind in model['required_kinds']}
            self.assertEqual(([], []), run_specialized(model, data))


class PairedUniverseTests(unittest.TestCase):
    def fixture(self, model, at=None):
        at = at or ts('2023-02-02T00:00:00Z')
        row = dict(ts=at, available_at=at, symbol='BTC', long_ask=100, long_bid=99.99,
                   short_bid=102, short_ask=102.01, long_size=100, short_size=100,
                   long_venue='gate', short_venue='mexc' if model['market'] == 'gate_mexc' else 'gate',
                   long_market='perp' if model['id'] == 'funding_cross' else 'spot',
                   short_market='spot' if model['id'] == 'spot_dislocation' else 'perp',
                   long_fee_bps=1, short_fee_bps=1, long_impact=0, short_impact=0,
                   fee_source='synthetic', base_units_verified=True)
        funding = [dict(ts=at-1, available_at=at-1, settlement_ts=at-1, period_seconds=28800,
                        rate=.01 if venue == row['short_venue'] else 0, symbol='BTC', venue=venue,
                        mark_price=100) for venue in {row['long_venue'], row['short_venue']}]
        data = dict(paired_quotes=[row, dict(row, ts=at+1, available_at=at+1),
                                  dict(row, ts=at+86401, available_at=at+86401,
                                       long_bid=103, long_ask=103.01, short_bid=100, short_ask=100.01)],
                    funding=funding, inventory=[dict(ts=at-1, available_at=at-1, symbol='BTC',
                    venue=v, base_quantity=100, cash=10000) for v in ('gate', 'mexc')])
        return data

    def test_all_four_missing_or_stale_universe_blocked(self):
        for model in build_plan()['models'][6:10]:
            for snapshots in ([], [universe(ts('2023-01-01T00:00:00Z'))]):
                with self.subTest(model=model['id'], snapshots=bool(snapshots)):
                    data = self.fixture(model)
                    data['pit_universe'] = snapshots
                    with self.assertRaisesRegex(MissingEvidence, 'monthly'):
                        paired(model, data, lambda: None)

    def test_future_published_universe_not_used(self):
        model = build_plan()['models'][6]
        data = self.fixture(model)
        snapshot = universe(ts('2023-02-01T00:00:00Z'))
        snapshot['available_at'] = ts('2023-02-03T00:00:00Z')
        data['pit_universe'] = [snapshot]
        with self.assertRaises(MissingEvidence):
            paired(model, data, lambda: None)

    def test_excluded_asset_does_not_open_position(self):
        for model in build_plan()['models'][6:10]:
            data = self.fixture(model)
            data['pit_universe'] = [universe(ts('2023-02-01T00:00:00Z'), ('ETH',))]
            self.assertEqual(([], []), paired(model, data, lambda: None))

    def test_valid_universe_preserves_pair_opportunities(self):
        for model in build_plan()['models'][6:9]:
            data = self.fixture(model)
            data['pit_universe'] = [universe(ts('2023-02-01T00:00:00Z'))]
            trades, exposed = paired(model, data, lambda: None)
            self.assertEqual(1, len(trades), model['id'])
            self.assertFalse(exposed)

    def test_entry_in_new_month_requires_new_observable_universe(self):
        model = build_plan()['models'][6]
        at = ts('2023-02-28T23:59:59Z')
        data = self.fixture(model, at)
        data['pit_universe'] = [universe(ts('2023-02-01T00:00:00Z'))]
        with self.assertRaises(MissingEvidence):
            paired(model, data, lambda: None)
        data['pit_universe'].append(universe(at+1, ('ETH',)))
        self.assertEqual(([], []), paired(model, data, lambda: None))

    def test_existing_position_can_close_after_month_rollover(self):
        model = build_plan()['models'][6]
        data = self.fixture(model, ts('2023-02-28T12:00:00Z'))
        data['pit_universe'] = [universe(ts('2023-02-01T00:00:00Z'))]
        self.assertEqual(1, len(paired(model, data, lambda: None)[0]))

    def test_readiness_requires_universe_without_mutating_frozen_plan(self):
        from unittest.mock import patch
        plan = build_plan()
        before = copy.deepcopy(plan)
        inv = inventory(plan, [])
        loaded = []
        for model in plan['models'][6:10]:
            for kind, rows in self.fixture(model).items():
                loaded.append(dict(entry=dict(id=model['id']+kind, kind=kind, market=model['market'],
                                              model_ids=[model['id']]), rows=rows))
        with patch('channel_validation.runner.load_inputs', return_value=(None, loaded)):
            result = validate(plan, inv, None)
        for row in result['models'][6:10]:
            self.assertEqual('BLOCKED_DATA', row['status'])
            self.assertIn('pit_universe', row['missing_kinds'])
        for row in inv['models'][6:10]:
            self.assertIn('pit_universe', row['required_kinds'])
        self.assertEqual(before, plan)


class EvidenceTests(unittest.TestCase):
    def test_paired_probe_fixed_budget_and_no_oos(self):
        from channel_validation.gate_paired import request_plan
        p = request_plan()
        self.assertEqual(10, len(p['requests']))
        self.assertEqual(10, len({r['url'] for r in p['requests']}))
        self.assertEqual(1000000, p['per_response_bytes'])
        self.assertEqual(0, p['retries'])
        self.assertFalse(p['redirects'])
        self.assertEqual({'202301', '202501'}, {r['month'] for r in p['requests']})

    def test_paired_probe_prefix_and_gzip_are_not_full_evidence(self):
        import gzip
        from channel_validation.gate_paired import inspect_archive
        raw = gzip.compress(b'time,rate\n1672531200,0.001\n')
        complete = inspect_archive(raw, True)
        self.assertTrue(complete['gzip_complete'])
        self.assertEqual(2, complete['sample_csv_widths'][0])
        partial = inspect_archive(raw[:-6], False)
        self.assertFalse(partial['gzip_complete'])
        self.assertFalse(partial['eligible_for_evaluation'])
        with self.assertRaises(ValueError):
            inspect_archive(raw[:-6], True)
        with self.assertRaises(ValueError):
            inspect_archive(b'<html>error</html>', True)
        large = inspect_archive(gzip.compress(b'x'*10000), True, decompressed_cap=100)
        self.assertTrue(large['decompressed_truncated'])
        self.assertLessEqual(large['decompressed_bytes'], 100)

    def test_paired_probe_body_cap_no_extra_read(self):
        import io
        from channel_validation.gate_paired import read_prefix
        stream = io.BytesIO(b'x'*20)
        stream.headers = {'Content-Length': '20'}
        raw, metadata = read_prefix(stream, lambda: None, cap=10)
        self.assertEqual(10, stream.tell())
        self.assertEqual(10, len(raw))
        self.assertFalse(metadata['complete'])
        self.assertEqual(20, metadata['declared_length'])
        stream = io.BytesIO(b'x'*5)
        stream.headers = {'Content-Length': '5'}
        self.assertTrue(read_prefix(stream, lambda: None, cap=10)[1]['complete'])

    def test_paired_probe_http_error_is_one_attempt_and_no_body_read(self):
        import urllib.error
        from channel_validation.gate_paired import probe_one, request_plan
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise urllib.error.HTTPError(request.full_url, 302, 'redirect', {}, None)
        opener = Opener()
        with tempfile.TemporaryDirectory() as folder:
            record = probe_one(request_plan()['requests'][0], opener, Path(folder), 1, lambda: None)
        self.assertEqual(1, opener.calls)
        self.assertEqual(302, record['http_status'])
        self.assertEqual(0, record['body']['bytes_read'])
        self.assertFalse(record['eligible_for_evaluation'])

    def test_source_probe_is_fixed_small_and_reference_not_execution(self):
        urls = sample_requests()
        self.assertEqual(12, len(urls))
        self.assertEqual(12, len(set(urls)))
        self.assertTrue(all(u.startswith('https://download.gatedata.org/spot/') for u in urls))

    def test_corrupted_archive_rejected(self):
        with self.assertRaises(OSError):
            inspect_csv_gzip(b'not-gzip')

    def test_bootstrap_requires_calendar_not_sparse_trade_dates(self):
        m = summarize([], {'2026-01-01': 10001, '2026-01-03': 10002})
        self.assertFalse(m['calendar_complete'])
        self.assertIsNone(m['bootstrap_p'])

    def test_overlapping_events_not_independent(self):
        trades = [dict(entry_ts=100, exit_ts=100000), dict(entry_ts=90000, exit_ts=200000)]
        self.assertEqual(1, temporal_groups(trades))

    def test_profit_concentration_is_group_not_individual_ticket(self):
        trades = [dict(symbol='A', entry_ts=100, exit_ts=100000, pnl=10),
                  dict(symbol='B', entry_ts=90000, exit_ts=200000, pnl=10)]
        metrics = summarize(trades, {})
        self.assertEqual(1, metrics['single_event_positive_share'])
        self.assertEqual(.5, metrics['single_base_positive_share'])

    def test_unknown_exposure_cannot_pass_candidate_gate(self):
        self.assertEqual('EXPLORATORY_ONLY', candidate_status(dict(exposure='UNKNOWN', execution_quality='EXECUTABLE_CERTIFIED'), .001, build_plan()))


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan()
        self.at = ts('2026-01-01T00:00:00Z')

    def opportunity(self, symbol, entry=None, exit=None, pnl=10, **extra):
        a = self.at if entry is None else entry
        b = self.at+3600 if exit is None else exit
        return dict(symbol=symbol, entry_ts=a, exit_ts=b, pnl=pnl, stress_pnl=pnl-2,
                    capital=1000, turnover=2000, reason='SYNTHETIC', marks=[(a, -2, -4), (b, pnl, pnl-2)], **extra)

    def test_global_capital_cannot_fund_eleventh_simultaneous_position(self):
        opportunities = [self.opportunity(str(i)) for i in range(11)]
        result = replay_opportunities(opportunities, [], self.plan, '2026-01-01', '2026-01-02')
        self.assertEqual(10, len(result['trades']))
        self.assertLessEqual(sum(t['capital'] for t in result['trades']), 10000)

    def test_future_gain_not_spendable_at_entry(self):
        base = [self.opportunity(str(i)) for i in range(10)]
        extra = self.opportunity('Z', self.at+60, self.at+120, 999999)
        first = replay_opportunities(base+[extra], [], self.plan, '2026-01-01', '2026-01-02')
        extra['pnl'] = -999999
        second = replay_opportunities(base+[extra], [], self.plan, '2026-01-01', '2026-01-02')
        self.assertEqual(first, second)

    def test_missing_daily_mark_blocks_instead_of_realized_only_curve(self):
        trade = self.opportunity('X', exit=self.at+3*86400)
        with self.assertRaisesRegex(MissingEvidence, 'stale'):
            replay_opportunities([trade], [], self.plan, '2026-01-01', '2026-01-05')

    def test_open_grid_or_token_exposure_blocks_candidate_equity(self):
        with self.assertRaisesRegex(MissingEvidence, 'Open/unexecutable'):
            replay_opportunities([], [dict(symbol='X')], self.plan, '2026-01-01', '2026-01-02')

    def test_loss_reduces_next_position_no_borrowing(self):
        first = self.opportunity('A', pnl=-100)
        second = self.opportunity('B', self.at+7200, self.at+10800)
        result = replay_opportunities([first, second], [], self.plan, '2026-01-01', '2026-01-02')
        self.assertEqual(990, result['trades'][1]['capital'])
        self.assertAlmostEqual(9.9, result['trades'][1]['pnl'])

    def test_fully_reserved_derivative_lot_cannot_be_fractionally_shrunk(self):
        first = self.opportunity('A', pnl=-100)
        second = self.opportunity('B', self.at+7200, self.at+10800, size_scale_step=1)
        result = replay_opportunities([first, second], [], self.plan, '2026-01-01', '2026-01-02')
        self.assertEqual(1, len(result['trades']))


class HistoryInputTests(unittest.TestCase):
    def setUp(self):
        self.spec = dict(base='BTC', step=3600, start=1672531200, end=1672538400)
        self.rows = [[str(t), '201', '101', '102', '99', '100', '2', 'true']
                     for t in (1672531200, 1672534800)]

    def test_fixed_request_budget_public_no_current_survivor_selection(self):
        p = requests_plan()
        self.assertEqual(10, len(p['requests']))
        self.assertLessEqual(len(p['requests']), build_plan()['resource_limits']['max_source_probe_requests'])
        self.assertEqual(0, p['retries'])
        self.assertFalse(p['universe_certified'])
        self.assertTrue(all('currency_pairs' not in r['url'] for r in p['requests']))

    def test_rest_preserves_exact_turnover_not_close_times_volume(self):
        result = normalize_rest(list(reversed(self.rows)), self.spec)
        self.assertEqual('201', result[0]['quote_volume'])
        self.assertEqual('2', result[0]['volume'])
        self.assertNotEqual(float(result[0]['quote_volume']), float(result[0]['close'])*float(result[0]['volume']))

    def test_unclosed_or_legacy_schema_rejected(self):
        for mutate in (lambda x: x[0].pop(), lambda x: x[0].__setitem__(7, 'false')):
            rows = copy.deepcopy(self.rows)
            mutate(rows)
            with self.assertRaises(ValueError):
                normalize_rest(rows, self.spec)

    def test_missing_duplicate_or_outside_bar_rejected(self):
        for rows in (self.rows[:1], self.rows+[self.rows[0]], self.rows[1:]+[self.rows[1]]):
            with self.assertRaises(ValueError):
                normalize_rest(rows, self.spec)

    def test_nonfinite_and_unit_swap_rejected(self):
        for q, v in (('NaN', '2'), ('Infinity', '2'), ('2', '201'), ('201', '0')):
            rows = copy.deepcopy(self.rows)
            rows[0][1], rows[0][6] = q, v
            with self.assertRaises(ValueError):
                normalize_rest(rows, self.spec)

    def test_csv_volume_is_not_silently_rest_volume_schema(self):
        import gzip
        raw = gzip.compress(b'1672531200,2,101,102,99,100\n1672534800,2,101,102,99,100\n')
        result = archive_comparison(normalize_rest(self.rows, self.spec), raw)
        self.assertEqual('BASE_VOLUME_MATCHES_API_ON_SAMPLED_ROWS', result['archive_column_1'])
        self.assertFalse(result['quote_turnover_reconstructible_from_csv'])
        self.assertFalse(result['global_schema_certified'])

    def response(self, raw, declared=None):
        import io
        r = io.BytesIO(raw)
        r.headers = {} if declared is None else {'Content-Length': str(declared)}
        return r

    def test_stream_exact_cap_known_length_valid(self):
        raw, status = read_bounded(self.response(b'1234', 4), lambda: None, 4)
        self.assertEqual(b'1234', raw)
        self.assertTrue(status['complete'])

    def test_stream_unknown_length_cap_not_guessed_complete(self):
        r = self.response(b'123456')
        raw, status = read_bounded(r, lambda: None, 4)
        self.assertEqual(4, r.tell())
        self.assertEqual(4, status['bytes_read'])
        self.assertFalse(status['complete'])

    def test_declared_oversize_skips_body_and_partial_length_rejected(self):
        r = self.response(b'123456', 6)
        raw, status = read_bounded(r, lambda: None, 4)
        self.assertEqual(0, r.tell())
        self.assertFalse(status['complete'])
        self.assertFalse(read_bounded(self.response(b'12', 4), lambda: None, 4)[1]['complete'])

    def test_stop_propagates_before_body_read(self):
        def stop():
            raise TimeoutError('STOP')
        r = self.response(b'1234')
        with self.assertRaises(TimeoutError):
            read_bounded(r, stop)
        self.assertEqual(0, r.tell())

    def test_missing_archive_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'missing'
            result = discover(path)
            self.assertFalse(path.exists())
            self.assertFalse(result['inventory_complete'])

    def test_archive_discovery_never_reads_payload_or_other_listing_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'daily'
            folder.mkdir()
            (folder/'candles.jsonl').write_bytes(b'invalid json, discovery must not read this')
            (folder/'listing_momentum_other.json').write_text('private other project')
            (folder/'holdout.jsonl').write_text('do not open')
            r = discover(tmp)
            self.assertEqual(['daily/candles.jsonl'], [f['path'] for f in r['files']])
            self.assertFalse(r['data_payloads_read'])
            self.assertFalse(r['evaluation_eligible'])
            self.assertFalse(discover(tmp, max_entries=1)['inventory_complete'])

    def test_perp_snapshot_does_not_certify_historical_spot_universe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'universe_state.json'
            state = dict(schema='pit_universe_state_v1', run_id='test', symbols={
                'gate|BTC': dict(row=dict(exchange='gate', contract_type='linear_perp', snapshot_ts='2026-08-11T00:00:00Z'))})
            p.write_text(json.dumps(state))
            r = inspect_pit_state(p)
            self.assertFalse(r['monthly_spot_membership_certified'])
            self.assertEqual({'gate:linear_perp': 1}, r['instrument_counts'])
            state['symbols']['gate|BTC']['row']['contract_type'] = 'spot'
            p.write_text(json.dumps(state))
            self.assertNotEqual(r['sha256'], inspect_pit_state(p)['sha256'])


class CatalogTests(unittest.TestCase):
    prefix = 'spot/candlesticks_1d/202301/'

    def xml(self, keys=('BTC_USDT-202301.csv.gz',), truncated='false', marker='', prefix=None):
        prefix = self.prefix if prefix is None else prefix
        entries = ''.join(f'<Contents><Key>{prefix}{k}</Key><Size>100</Size></Contents>' for k in keys)
        return (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                f'<Name>gateio-public-data</Name><Prefix>{prefix}</Prefix><Marker>{marker}</Marker>'
                f'<IsTruncated>{truncated}</IsTruncated>{entries}</ListBucketResult>').encode()

    def test_truncated_page_is_not_complete_and_uses_last_key(self):
        r = parse_catalog(self.xml(truncated='true'), self.prefix)
        self.assertTrue(r['is_truncated'])
        self.assertEqual(self.prefix+'BTC_USDT-202301.csv.gz', r['next_marker'])
        self.assertIsNone(r['objects'][0]['payload_sha256'])

    def test_empty_complete_catalog_allowed_not_infinite_pagination(self):
        self.assertFalse(parse_catalog(self.xml(keys=()), self.prefix)['is_truncated'])
        with self.assertRaises(ValueError):
            parse_catalog(self.xml(keys=(), truncated='true'), self.prefix)

    def test_wrong_prefix_duplicate_or_repeated_page_rejected(self):
        for raw, marker in ((self.xml(prefix='wrong/'), ''),
                            (self.xml(keys=('BTC_USDT-202301.csv.gz',)*2), ''),
                            (self.xml(marker=self.prefix+'BTC_USDT-202301.csv.gz'), self.prefix+'BTC_USDT-202301.csv.gz')):
            with self.assertRaises(ValueError):
                parse_catalog(raw, self.prefix, marker)

    def test_xml_entity_blocked(self):
        with self.assertRaises(ValueError):
            parse_catalog(b'<!DOCTYPE x [<!ENTITY x "bad">]>'+self.xml(), self.prefix)

    def test_archive_daily_volume_requires_every_hour(self):
        import gzip
        start = 1735689600
        raw = ''.join(f'{at},1,100,101,99,100\n' for at in range(start, start+86400, 3600)).encode()
        rest = dict(ts=start, end_ts=start+86400, volume='24', quote_volume='2400',
                    open='100', high='101', low='99', close='100')
        r = aggregate_archive(gzip.compress(raw), [rest])
        self.assertEqual('BASE_ON_SAMPLED_DAYS', r['inferred_volume_unit'])
        with self.assertRaises(ValueError):
            aggregate_archive(gzip.compress(raw.split(b'\n', 1)[1]), [rest])

    def test_changed_sealed_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'audit.json'
            value = dict(rows=30, source='A')
            value['hash'] = canonical_hash(value)
            p.write_text(json.dumps(value))
            checked_json(p, 'hash')
            value['source'] = 'B'
            p.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                checked_json(p, 'hash')


class SurvivorshipTests(unittest.TestCase):
    def test_fixed_public_budget_no_profit_selection(self):
        plan = survivorship_plan()
        self.assertEqual(8, len(plan['requests']))
        self.assertEqual(8, len({r['url'] for r in plan['requests']}))
        self.assertEqual(0, plan['retries'])
        self.assertFalse(plan['evaluation_eligible'])
        self.assertEqual({'TRC', 'EYWA'}, {r['base'] for r in plan['requests'] if 'base' in r})

    def test_current_symbols_never_certify_past_membership(self):
        result = parse_symbols(dict(code=0, data=dict(spot=['btc_usdt', 'old_usdt'])))
        self.assertEqual(['BTC_USDT', 'OLD_USDT'], result['pairs'])
        self.assertFalse(result['historical_membership_complete'])
        self.assertFalse(result['asset_types_verified'])

    def test_empty_wrong_or_duplicate_symbols_rejected(self):
        for values in ([], ['BTC_USDT', 'btc_usdt'], ['BTC'], [None], ['BTC_USDT '], ['_USDT']):
            with self.assertRaises(ValueError):
                parse_symbols(dict(code=0, data=dict(spot=values)))
        with self.assertRaises(ValueError):
            parse_symbols(dict(code=1, data=dict(spot=['BTC_USDT'])))

    def test_absent_pair_and_real_archive_prove_export_omission_only(self):
        records = [dict(kind='export_symbols', parsed=dict(pairs=['BTC_USDT'])),
                   dict(kind='hourly_archive', base='TRC', parsed=dict(rows=744, full_requested_grid=True))]
        result = conclusions(records)
        self.assertTrue(result['samples'][0]['export_list_missing_historical_pair'])
        self.assertFalse(result['historical_universe_certified'])
        self.assertFalse(result['samples'][0]['exact_daily_turnover_observed'])

    def test_failed_list_does_not_mean_absence(self):
        result = conclusions([dict(kind='export_symbols', status='HTTP_ERROR_NO_RETRY'),
                              dict(kind='hourly_archive', base='TRC', parsed=dict(rows=744))])
        self.assertIsNone(result['samples'][0]['absent_from_export_symbols'])
        self.assertFalse(result['samples'][0]['export_list_missing_historical_pair'])

    def test_partial_archive_explicit_not_complete(self):
        import gzip
        spec = dict(start=0, end=7200, step=3600)
        result = parse_archive(gzip.compress(b'0,1,100,101,99,100\n'), spec)
        self.assertFalse(result['full_requested_grid'])
        self.assertEqual(1, result['missing_bars'])
        self.assertFalse(result['exact_quote_turnover_available'])

    def test_corrupt_archive_rejected(self):
        import gzip
        for raw in (b'', b'0,1,100,101,99,100\n'*2, b'1,1,100,101,99,100\n',
                    b'0,NaN,100,101,99,100\n', b'0,1,100,99,101,100\n', b'0,1,100\n'):
            with self.assertRaises(ValueError):
                parse_archive(gzip.compress(raw), dict(start=0, end=7200, step=3600))

    def test_new_stage_rejects_long_runtime_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'unused'
            with self.assertRaises(SystemExit):
                main(['gate-survivorship-audit', '--max-runtime-sec', '301', '--output', str(output)])
            self.assertFalse(output.exists())


class ArchivedTradeTests(unittest.TestCase):
    def zipped(self, text):
        import gzip
        return gzip.compress(text.encode())

    def test_exact_turnover_not_candle_close_times_volume(self):
        result = summarize_trades(self.zipped('0.1,1,99,2,1\n1.2,2,101,3,2\n'), dict(start=0, end=86400))
        self.assertEqual('501', result['days'][0]['quote_turnover'])
        self.assertEqual('5', result['days'][0]['base_volume'])
        self.assertFalse(result['historical_completeness_certified'])

    def test_daily_boundary_fractional_timestamp_and_no_fabricated_empty_days(self):
        result = summarize_trades(self.zipped('86399.9,1,100,1,1\n172800,2,100,1,2\n'), dict(start=0, end=259200))
        self.assertEqual([0, 172800], [r['ts'] for r in result['days']])
        self.assertEqual([82800, 172800], [r['ts'] for r in result['hours']])

    def test_schema_duplicate_unit_or_price_errors_rejected(self):
        for text in ('0,1,100,1,1\n'*2, '0,1,100,1\n', '0,1,100,-1,1\n', '0,1,NaN,1,1\n',
                     '3600000,1,100,1,1\n', '0,1,100,1,0\n', ''):
            with self.assertRaises(ValueError):
                summarize_trades(self.zipped(text), dict(start=0, end=86400))

    def test_cross_archive_consistency_is_not_completeness(self):
        spec = dict(start=0, end=10800)
        summary = summarize_trades(self.zipped('0,1,100,2,1\n7200,2,100,1,2\n'), spec)
        result = reconcile_trades(summary, self.zipped('0,2,100,101,99,100\n7200,3,100,101,99,100\n'), spec)
        self.assertEqual(1, result['base_volume_matches'])
        self.assertEqual([7200], result['volume_mismatch_hours'])
        self.assertEqual(1, result['hours_absent_from_both'])
        self.assertFalse(result['historical_completeness_certified'])

    def test_stop_request_propagates(self):
        def stop():
            raise TimeoutError('STOP')
        with self.assertRaises(TimeoutError):
            summarize_trades(self.zipped('0,1,100,1,1\n'), dict(start=0, end=86400), stop)


class ProviderMetadataTests(unittest.TestCase):
    def payload(self):
        return dict(id='gate-io', availableSymbols=[dict(id='TRC_USDT', type='spot',
                    availableSince='2022-06-09T00:00:00Z', availableTo='2026-09-02T03:00:00Z'),
                    dict(id='BTC_USDT', type='spot', availableSince='2020-07-01T00:00:00Z')])

    def test_provider_dates_and_spot_type_do_not_certify_pit_or_asset_type(self):
        result = parse_metadata(json.dumps(self.payload()))
        self.assertEqual(2, result['usdt_symbol_count'])
        self.assertEqual(1, result['finite_provider_interval_count'])
        self.assertEqual('TRC_USDT', result['delisted_samples'][0]['symbol'])
        self.assertIsNone(result['symbols'][0]['provider_available_to'])
        self.assertTrue(all(r['listing_ts'] is None and r['asset_type'] is None for r in result['symbols']))
        self.assertFalse(result['historical_membership_complete'])
        self.assertFalse(result['evaluation_eligible'])

    def test_missing_empty_duplicate_or_wrong_market_rejected(self):
        for mutate in (lambda p: p.update(id='gate-io-futures'), lambda p: p.update(availableSymbols=[]),
                       lambda p: p['availableSymbols'].append(p['availableSymbols'][0]),
                       lambda p: p['availableSymbols'][0].update(type='perpetual'),
                       lambda p: p['availableSymbols'][0].update(id='../bad')):
            payload = self.payload()
            mutate(payload)
            with self.assertRaises(ValueError):
                parse_metadata(json.dumps(payload))
        for raw in ('{"id":"gate-io","id":"gate-io"}', '{'):
            with self.assertRaises(ValueError):
                parse_metadata(raw)

    def test_bad_or_reversed_dates_rejected(self):
        for start, end in ((None, None), ('2023-01-01', None),
                           ('2026-01-01T00:00:00Z', '2025-01-01T00:00:00Z')):
            payload = self.payload()
            payload['availableSymbols'][0].update(availableSince=start, availableTo=end)
            with self.assertRaises(ValueError):
                parse_metadata(json.dumps(payload))

    def test_deterministic_sorted_metadata_and_changed_data_binding(self):
        payload = self.payload()
        first = canonical_hash(parse_metadata(json.dumps(payload)))
        payload['availableSymbols'].reverse()
        self.assertEqual(first, canonical_hash(parse_metadata(json.dumps(payload))))
        payload['availableSymbols'][0]['availableSince'] = '2021-07-01T00:00:00Z'
        self.assertNotEqual(first, canonical_hash(parse_metadata(json.dumps(payload))))

    def test_single_request_no_retry_and_runtime_bound(self):
        plan = metadata_plan()
        self.assertEqual(1, len(plan['requests']))
        self.assertEqual(0, plan['retries'])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'unused'
            with self.assertRaises(SystemExit):
                main(['gate-metadata-audit', '--max-runtime-sec', '301', '--output', str(output)])
            self.assertFalse(output.exists())

    def test_stop_propagates(self):
        def stop():
            raise TimeoutError('STOP')
        with self.assertRaises(TimeoutError):
            parse_metadata(json.dumps(self.payload()), stop)


class OptionArchiveSourceTests(unittest.TestCase):
    def catalog(self):
        details = []
        for family in ('BTC-USD', 'ETH-USD'):
            filename = f'{family}-optionchain-L2orderbook-400lv-{DAY}.tar.gz'
            details.append(dict(instType='OPTION', instFamily=family, groupDetails=[dict(
                dateTs=str(DAY_MS), sizeMB='243.22', filename=filename,
                url=f'https://static.okx.com/cdn/okx/match/orderbook/L2/400lv/daily/20250106/{filename}')]))
        return dict(code='0', data=dict(details=details))

    def tar(self, name='BTC-USD-250131-90000-P.txt'):
        import io
        import tarfile
        import gzip
        data = (json.dumps(dict(instId='BTC-USD-250131-90000-P', action='snapshot',
                               ts=str(DAY_MS), bids=[['0.01', '1', '1']], asks=[['0.02', '1', '1']]))+'\n').encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        return gzip.compress(buffer.getvalue())

    def test_catalog_allows_only_exact_dated_btc_eth_public_files(self):
        rows = parse_okx_catalog(json.dumps(self.catalog()))
        self.assertEqual(['BTC-USD', 'ETH-USD'], [r['family'] for r in rows])
        self.assertEqual([], parse_okx_catalog(json.dumps(dict(code='0', data=dict(details=[])))))

    def test_catalog_does_not_follow_untrusted_urls_or_wrong_dates(self):
        for field, value in (('url', 'https://example.com/private'), ('dateTs', '0'),
                             ('sizeMB', 'NaN'), ('filename', '../file.tar.gz')):
            payload = self.catalog()
            payload['data']['details'][0]['groupDetails'][0][field] = value
            with self.assertRaises(ValueError):
                parse_okx_catalog(json.dumps(payload))
        payload = self.catalog()
        payload['data']['details'] *= 2
        with self.assertRaises(ValueError):
            parse_okx_catalog(json.dumps(payload))

    def test_utc_date_and_bounded_public_request_budget(self):
        plan = okx_plan()
        self.assertEqual(str(DAY_MS+86400000-1), plan['payload']['dateQuery']['begin'])
        self.assertEqual(3, plan['max_requests'])
        self.assertFalse(plan['credentials'])
        self.assertFalse(plan['full_archive_download'])
        self.assertEqual(0, plan['retries'])

    def test_ignored_oversized_encoded_or_wrong_range_rejected(self):
        valid = {'Content-Range': f'bytes 0-{CAP-1}/200000000', 'Content-Length': str(CAP)}
        self.assertFalse(validate_range(206, valid)['entire_archive_in_response'])
        for status, headers in ((200, valid), (206, {}), (206, dict(valid, **{'Content-Encoding': 'gzip'})),
                                (206, dict(valid, **{'Content-Length': str(CAP+1)})),
                                (206, dict(valid, **{'Content-Range': 'bytes 1-99/200'}))):
            with self.assertRaises(ValueError):
                validate_range(status, headers)

    def test_tar_prefix_records_real_fields_but_never_certifies_archive(self):
        result = inspect_prefix(self.tar())
        self.assertIn('bids', result['sample']['top_level_fields'])
        self.assertIn('asks', result['sample']['top_level_fields'])
        self.assertFalse(result['evaluation_eligible'])
        self.assertFalse(result['archive_complete'])
        self.assertEqual(canonical_hash(result), canonical_hash(inspect_prefix(self.tar())))

    def test_incomplete_gzip_prefix_can_describe_schema_not_integrity(self):
        raw = self.tar()
        result = inspect_prefix(raw[:-8])
        self.assertFalse(result['gzip_end_seen'])
        self.assertFalse(result['archive_complete'])
        self.assertIsNotNone(result['sample'])

    def test_unsafe_tar_member_and_corrupted_header_rejected(self):
        import gzip
        with self.assertRaises(ValueError):
            inspect_prefix(self.tar('../outside'))
        decoded = bytearray(gzip.decompress(self.tar()))
        decoded[0] ^= 1
        with self.assertRaises(ValueError):
            inspect_prefix(gzip.compress(decoded))

    def test_stop_and_runtime_cap(self):
        def stop():
            raise TimeoutError('STOP')
        with self.assertRaises(TimeoutError):
            inspect_prefix(self.tar(), stop)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'unused'
            with self.assertRaises(SystemExit):
                main(['okx-history-audit', '--max-runtime-sec', '301', '--output', str(output)])
            self.assertFalse(output.exists())


class OptionFullArchiveTests(unittest.TestCase):
    symbol = 'BTC-USD-250207-90000-P'

    def record(self, **changes):
        value = dict(instId=self.symbol, action='snapshot', ts=str(DAY_MS),
                     bids=[['0.01', '2', '1']], asks=[['0.02', '3', '1']])
        value.update(changes)
        return value

    def book(self):
        return Book(self.symbol, DAY_MS, DAY_MS+86400000)

    def archive(self, records=None, names=None, body=None):
        import io
        import tarfile
        import gzip
        if body is None:
            body = b''.join((json.dumps(r)+'\n').encode() for r in (records or [self.record()]))
        names = names or [self.symbol+'-L2orderbook-400lv-'+DAY+'.data']
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name in names:
                member = tarfile.TarInfo(name)
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
        return gzip.compress(buffer.getvalue(), mtime=0)

    def scan(self, raw, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'test.tar.gz'
            path.write_bytes(raw)
            return census(path, DAY, DAY_MS, **kwargs)

    def test_snapshot_absolute_updates_and_deletion(self):
        book = self.book()
        book.apply(self.record())
        result = book.apply(self.record(action='update', ts=str(DAY_MS+1),
                            bids=[['0.01', '5', '2']], asks=[]))
        self.assertEqual('5', result['bid_size'])
        self.assertEqual('3', result['ask_size'])
        result = book.apply(self.record(action='update', bids=[['0.01', '0', '0']],
                            asks=[], ts=str(DAY_MS+2)))
        self.assertEqual('EMPTY_SIDE', result['status'])
        self.assertIsNone(result['bid'])

    def test_snapshot_resets_stale_levels(self):
        book = self.book()
        book.apply(self.record())
        result = book.apply(self.record(bids=[['0.005', '1', '1']]))
        self.assertEqual('0.005', result['bid'])

    def test_crossed_or_one_sided_is_not_fabricated_liquidity(self):
        for changes, status in ((dict(asks=[]), 'EMPTY_SIDE'),
                                (dict(asks=[['0.005', '1', '1']]), 'CROSSED_OR_LOCKED')):
            result = self.book().apply(self.record(**changes))
            self.assertEqual(status, result['status'])
            self.assertFalse(result['historical_units_verified'])
            self.assertIsNone(result['available_at'])

    def test_malformed_prices_units_or_schema_rejected(self):
        for bids in ([['NaN', '1', '1']], [['0', '1', '1']], [['0.01', '-1', '1']],
                     [['0.01', '1', '0']], [['0.01', '1', '0.5']], [['0.01', '1', '1', '0']],
                     [['0.01', '1', '1']]*2):
            with self.subTest(bids=bids), self.assertRaises(ValueError):
                self.book().apply(self.record(bids=bids))

    def test_snapshot_required_and_timestamp_checks(self):
        for changes in (dict(action='update'), dict(ts=str(DAY_MS-1)),
                        dict(ts=str(DAY_MS+86400000)), dict(ts=str(DAY_MS)+'.5'), dict(instId='wrong')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.book().apply(self.record(**changes))
        book = self.book()
        book.apply(self.record(ts=str(DAY_MS+2)))
        with self.assertRaises(ValueError):
            book.apply(self.record())

    def test_sequence_gap_and_missing_sequence_not_certified(self):
        book = self.book()
        book.apply(self.record(seqId='1'))
        book.apply(self.record(action='update', seqId='2', prevSeqId='1', bids=[], asks=[]))
        self.assertTrue(book.sequence_complete)
        with self.assertRaises(ValueError):
            book.apply(self.record(action='update', seqId='4', prevSeqId='3'))
        book = self.book()
        book.apply(self.record())
        self.assertFalse(book.sequence_complete)

    def test_contract_metadata_never_invents_historical_specifications(self):
        result = contract_id(self.symbol)
        self.assertEqual('2025-02-07', result['expiry_date'])
        self.assertEqual('P', result['option_type'])
        self.assertIsNone(result['multiplier'])
        self.assertIsNone(result['premium_currency'])
        self.assertFalse(result['expiry_time_verified'])
        for name in ('BTC-USD-250230-90000-P', 'BTC-USD-250207-0-P', 'ETH-USD-250207-90000-P'):
            with self.assertRaises(ValueError):
                contract_id(name)

    def test_complete_container_hashes_are_deterministic_not_trade_eligibility(self):
        import hashlib
        raw = self.archive()
        result = self.scan(raw)
        self.assertTrue(result['gzip_crc_checked'])
        self.assertTrue(result['tar_eof_checked'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result['compressed_sha256'])
        self.assertEqual(1, result['put_count'])
        self.assertFalse(result['evaluation_eligible'])
        self.assertFalse(result['entire_day_books_validated'])
        self.assertEqual(canonical_hash(result), canonical_hash(self.scan(raw)))
        changed = self.scan(self.archive([self.record(asks=[['0.03', '3', '1']])]))
        self.assertEqual(result['sampled_rows'], changed['sampled_rows'])
        self.assertNotEqual(canonical_hash(result), canonical_hash(changed))

    def test_gzip_crc_and_footer_checked_after_tar_terminator(self):
        import gzip
        raw = self.archive()
        corrupted = bytearray(raw)
        corrupted[-8] ^= 1
        for value in (raw[:-4], bytes(corrupted)):
            with self.assertRaises((EOFError, gzip.BadGzipFile)):
                self.scan(value)

    def test_tar_truncation_and_trailing_nonzero_data_rejected(self):
        import gzip
        decoded = gzip.decompress(self.archive())
        for value in (decoded[:1024], decoded+bytes(100)+b'bad'):
            with self.assertRaises(ValueError):
                self.scan(gzip.compress(value))

    def test_unsafe_duplicate_or_wrong_day_members_rejected(self):
        name = self.symbol+'-L2orderbook-400lv-'+DAY+'.data'
        for names in ([name, name], ['../'+name], [name.replace(DAY, '2025-01-07')]):
            with self.assertRaises(ValueError):
                self.scan(self.archive(names=names))

    def test_invalid_book_sample_is_not_a_container_or_trading_pass(self):
        result = self.scan(self.archive(body=b'{\n'))
        self.assertTrue(result['container_complete'])
        self.assertEqual(1, result['invalid_book_samples'])
        self.assertEqual('INVALID_BOOK_SAMPLE', result['members'][0]['sample_status'])
        self.assertFalse(result['members'][0]['trading_eligible'])

    def test_sample_limit_never_claims_unread_book_records_valid(self):
        body = (json.dumps(self.record())+'\n{malformed later record}\n').encode()
        result = self.scan(self.archive(body=body), sample_rows=1)
        self.assertEqual(1, result['sampled_rows'])
        self.assertEqual(0, result['invalid_book_samples'])
        self.assertFalse(result['members'][0]['entire_member_book_validated'])
        self.assertFalse(result['exchange_completeness_certified'])

    def test_scan_limits_and_stop_propagate(self):
        with self.assertRaises(ValueError):
            self.scan(self.archive(), scan_limit=100)
        def stop():
            raise TimeoutError('STOP')
        with self.assertRaises(TimeoutError):
            self.scan(self.archive(), check=stop)


class FullDownloadTests(unittest.TestCase):
    def response(self, raw=b'abcdefgh', status=200, declared='8', encoding='identity'):
        import io
        response = io.BytesIO(raw)
        response.status = status
        response.headers = {'Content-Encoding': encoding}
        if declared is not None:
            response.headers['Content-Length'] = declared
        return response

    def download(self, response, path, prefix=b'abcd', **kwargs):
        import hashlib
        return stream_download(response, path, 8, hashlib.sha256(prefix).hexdigest(),
                               kwargs.pop('check', lambda: None), prefix_bytes=4, **kwargs)

    def test_full_download_atomic_and_exact_cap_success(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'full.gz'
            result = self.download(self.response(), path, cap=8)
            self.assertEqual(b'abcdefgh', path.read_bytes())
            self.assertEqual(hashlib.sha256(b'abcdefgh').hexdigest(), result['sha256'])
            self.assertFalse(Path(str(path)+'.partial').exists())

    def test_length_prefix_status_and_encoding_fail_without_complete_artifact(self):
        for response in (self.response(raw=b'abcd'), self.response(raw=b'bad_data'),
                         self.response(status=206), self.response(declared='9'),
                         self.response(encoding='gzip'), self.response(raw=b'abcdefghi', declared=None)):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'full.gz'
                with self.assertRaises(ValueError):
                    self.download(response, path)
                self.assertFalse(path.exists())

    def test_unknown_length_eof_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'full.gz'
            result = self.download(self.response(declared=None), path)
            self.assertTrue(result['complete'])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.download(self.response(declared=None), Path(tmp)/'full.gz', cap=8)

    def test_no_overwrite_or_blind_resume(self):
        for suffix in ('', '.partial'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'full.gz'
                existing = Path(str(path)+suffix)
                existing.write_bytes(b'original')
                with self.assertRaises(FileExistsError):
                    self.download(self.response(), path)
                self.assertEqual(b'original', existing.read_bytes())

    def test_stop_propagates_before_body_read(self):
        def stop():
            raise TimeoutError('STOP')
        response = self.response()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                self.download(response, Path(tmp)/'full.gz', check=stop)
        self.assertEqual(0, response.tell())

    def test_acquisition_is_separate_from_one_mb_probe(self):
        self.assertEqual(300000000, MAX_DOWNLOAD)
        self.assertEqual(1000000, okx_plan()['per_response_bytes'])
        self.assertFalse(okx_plan()['full_archive_download'])

    def test_download_cannot_be_retried_under_a_new_namespace(self):
        from unittest.mock import patch
        from channel_validation.okx_acquire import acquire
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'renamed-retry'
            with patch('channel_validation.okx_acquire.acquisition_plan') as plan, self.assertRaises(ValueError):
                acquire(path, lambda: None)
            plan.assert_not_called()
            self.assertFalse(path.exists())

    def local_fixture(self, source):
        import hashlib
        root = source/'artifacts/okx-full-archive'
        root.mkdir(parents=True)
        raw = b'abcdefgh'
        sha = hashlib.sha256(raw).hexdigest()
        expected = dict(expected_bytes=len(raw), plan_hash='synthetic-frozen-plan')
        ah = canonical_hash(expected)
        (root/'BTC-USD-2025-01-06.tar.gz').write_bytes(raw)
        write_immutable(root/'acquisition-plan.json', dict(**expected, acquisition_hash=ah, runtime_binding={}))
        write_immutable(root/'download-receipt.json', dict(acquisition_hash=ah, complete=True, bytes=len(raw), sha256=sha))
        write_immutable(source/'completion.json', dict(status='STOPPED_INCOMPLETE', plan_hash=expected['plan_hash'],
                                                     runtime_hash=canonical_hash({})))
        write_immutable(source/'failure.json', dict(error='Decoded stream budget exceeded', retry_authorized=False))
        return root, expected, sha

    def test_complete_subartifact_is_readonly_no_network_or_status_rewrite(self):
        from unittest.mock import patch
        from channel_validation.okx_acquire import local_census_plan
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            _, expected, sha = self.local_fixture(source)
            before = {p.name: p.read_bytes() for p in source.glob('*.json')}
            with patch('channel_validation.okx_acquire.acquisition_plan', return_value=expected), \
                 patch('channel_validation.okx_acquire.LOCAL_SHA', sha):
                plan = local_census_plan(source)
            self.assertEqual(0, plan['max_http_requests'])
            self.assertFalse(plan['archive_retry'])
            self.assertFalse(plan['trading_eligible'])
            self.assertEqual(32*1024**3, plan['max_stream_decoded_bytes'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in source.glob('*.json')})

    def test_partial_corrupt_or_different_failure_cannot_be_reused(self):
        from unittest.mock import patch
        from channel_validation.okx_acquire import local_census_plan
        for change in ('raw', 'receipt', 'failure', 'binding'):
            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp)
                root, expected, sha = self.local_fixture(source)
                if change == 'raw':
                    (root/'BTC-USD-2025-01-06.tar.gz').write_bytes(b'abcdefgX')
                else:
                    file, key, value = {
                        'receipt': (root/'download-receipt.json', 'complete', False),
                        'failure': (source/'failure.json', 'error', 'CRC mismatch'),
                        'binding': (source/'completion.json', 'runtime_hash', 'changed'),
                    }[change]
                    data = json.loads(file.read_text())
                    data[key] = value
                    file.write_text(json.dumps(data))
                with patch('channel_validation.okx_acquire.acquisition_plan', return_value=expected), \
                     patch('channel_validation.okx_acquire.LOCAL_SHA', sha), self.assertRaises(ValueError):
                    local_census_plan(source)


class OptionDependencyTests(unittest.TestCase):
    def spec(self):
        from channel_validation.okx_dependencies import request_plan
        return request_plan()['requests'][0]

    def row(self, offset=-60000):
        return [str(DAY_MS+offset), '100', '102', '99', '101', '1']

    def parse(self, rows):
        from channel_validation.okx_dependencies import parse_index
        return parse_index(json.dumps(dict(code='0', data=rows)).encode(), self.spec())

    def terms(self):
        return dict(valid_from='2025-01-01T00:00:00Z', valid_to='2025-02-01T00:00:00Z',
                    verified=True, evidence_sha256='a'*64, premium_currency='BTC', settlement_currency='BTC',
                    taker_rate='0.0003', premium_cap='0.125', multiplier='0.01', contract_value='1')

    def test_fixed_eight_requests_and_no_full_archives(self):
        from channel_validation.okx_dependencies import request_plan, EXIT_MS
        from urllib.parse import urlparse, parse_qs
        plan = request_plan()
        self.assertEqual(8, len(plan['requests']))
        self.assertEqual(8, plan['max_requests'])
        self.assertEqual(0, plan['retries'])
        self.assertEqual(300, plan['max_runtime_sec'])
        self.assertEqual(1000000, plan['per_response_bytes'])
        self.assertEqual(8000000, plan['total_response_bytes'])
        for key in ('redirects', 'proxies', 'credentials', 'full_archive_download', 'evaluation_eligible'):
            self.assertFalse(plan[key])
        for request in plan['requests'][:4]:
            self.assertIn(request['anchor_ms'], (DAY_MS, EXIT_MS))
            query = parse_qs(urlparse(request['url']).query)
            self.assertEqual([str(request['anchor_ms']+60000)], query['after'])
            self.assertEqual([str(request['anchor_ms']-120000)], query['before'])
            self.assertEqual(['3'], query['limit'])
        self.assertEqual(str(EXIT_MS+86400000-1), plan['requests'][4]['payload']['dateQuery']['begin'])
        self.assertEqual(canonical_hash(plan), canonical_hash(request_plan()))

    def test_current_candle_close_not_available_at_entry(self):
        result = self.parse([self.row(0), self.row(-120000), self.row()])
        self.assertEqual(DAY_MS-60000, result['latest_closed_reference']['start_ms'])
        self.assertEqual(DAY_MS, result['latest_closed_reference']['close_usable_not_before_ms'])
        self.assertEqual(DAY_MS+60000, result['candles'][-1]['close_usable_not_before_ms'])
        self.assertFalse(result['execution_quote'])
        self.assertFalse(result['evaluation_eligible'])
        self.assertFalse(result['publication_latency_verified'])

    def test_empty_and_current_only_are_not_an_entry_quote(self):
        empty = self.parse([])
        self.assertEqual('NO_INDEX_HISTORY', empty['status'])
        self.assertIsNone(empty['latest_closed_reference'])
        self.assertIsNone(self.parse([self.row(0)])['latest_closed_reference'])

    def test_duplicate_index_candles_rejected(self):
        with self.assertRaises(ValueError):
            self.parse([self.row(), self.row()])

    def test_index_schema_grid_and_prices_rejected(self):
        for row in (self.row()+['extra'], self.row(1), self.row(60000), self.row(-180000),
                    [str(DAY_MS), '100', '102', '99', '101', '0'],
                    [str(DAY_MS), 'NaN', '102', '99', '101', '1'],
                    [str(DAY_MS), '100', '99', '99', '101', '1'],
                    [str(DAY_MS), '100', '102', '-1', '101', '1']):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.parse([row])

    def test_index_payload_errors_are_not_empty_history(self):
        from channel_validation.okx_dependencies import parse_index
        for raw in (b'{"code":"1","data":[]}', b'{"code":"0","code":"0","data":[]}',
                    b'{"code":"0","data":{}}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_index(raw, self.spec())

    def test_exit_catalog_date_is_separate_from_entry(self):
        from channel_validation.okx_dependencies import EXIT_DAY, EXIT_MS
        filename = 'BTC-USD-optionchain-L2orderbook-400lv-2025-01-13.tar.gz'
        raw = json.dumps(dict(code='0', data=dict(details=[dict(instType='OPTION', instFamily='BTC-USD',
            groupDetails=[dict(filename=filename, url='https://static.okx.com/cdn/okx/match/orderbook/L2/400lv/daily/20250113/'+filename,
                               dateTs=str(EXIT_MS), sizeMB='250')])]))).encode()
        self.assertEqual('BTC-USD', parse_okx_catalog(raw, EXIT_DAY, EXIT_MS)[0]['family'])
        with self.assertRaises(ValueError):
            parse_okx_catalog(raw)

    def test_later_fee_notice_does_not_backfill_january(self):
        from channel_validation.okx_dependencies import inspect_document
        raw = b'<article>OKX to adjust parameters for options fee calculation May 15, 2025 7:00 am UTC 12.5% 7%</article>'
        result = inspect_document(raw, 'cap_change')
        self.assertEqual('DATED_FEE_CAP_TRANSITION_FOUND', result['status'])
        self.assertEqual('2025-05-15T07:00:00Z', result['effective_at_utc'])
        self.assertIsNone(result['previous_effective_from'])
        self.assertFalse(result['jan2025_terms_verified'])
        self.assertFalse(result['date_coverage_certified'])
        self.assertFalse(result['evaluation_eligible'])

    def test_script_markers_do_not_become_document_evidence(self):
        from channel_validation.okx_dependencies import inspect_document
        raw = b'<script>OKX to adjust parameters for options fee calculation May 15, 2025 7:00 am UTC 12.5% 7%</script><p>Unavailable</p>'
        self.assertEqual('DOCUMENT_REQUIRES_REVIEW', inspect_document(raw, 'cap_change')['status'])

    def test_tier_notice_and_current_specs_do_not_certify_old_terms(self):
        from channel_validation.okx_dependencies import inspect_document
        result = inspect_document(b'OKX to adjust options trading fees February 10, 2025 10:40 am UTC Lvl 1 0.030%', 'tier_change')
        self.assertEqual('DATED_FEE_TIER_ANNOUNCEMENT_FOUND', result['status'])
        self.assertFalse(result['prior_tiers_verified'])
        current = inspect_document(b'Published 2023 Updated 2026 Contract Multiplier 0.01 0.1', 'current_specs')
        self.assertEqual('CURRENT_SPEC_NOT_HISTORICAL_CERTIFICATE', current['status'])
        self.assertFalse(current['historical_values_adopted'])

    def test_dated_fee_native_units_cap_and_rate(self):
        from decimal import Decimal
        from channel_validation.okx_dependencies import dated_taker_fee
        terms = self.terms()
        at = '2025-01-06T00:00:00Z'
        self.assertEqual(Decimal('0.0000025'), dated_taker_fee(terms, at, '0.001', '2'))
        terms['premium_cap'] = '0.07'
        self.assertEqual(Decimal('0.0000014'), dated_taker_fee(terms, at, '0.001', '2'))
        self.assertEqual(Decimal('0.000006'), dated_taker_fee(terms, at, '0.01', '2'))

    def test_fee_time_boundary_no_future_backfill(self):
        from channel_validation.okx_dependencies import dated_taker_fee
        terms = self.terms()
        self.assertGreater(dated_taker_fee(terms, terms['valid_from'], '0.001', 1), 0)
        for at in ('2024-12-31T23:59:59Z', terms['valid_to']):
            with self.assertRaises(ValueError):
                dated_taker_fee(terms, at, '0.001', 1)

    def test_fee_requires_explicit_dated_proof_and_native_units(self):
        from channel_validation.okx_dependencies import dated_taker_fee
        for key, value in (('valid_from', None), ('valid_to', None), ('verified', False),
                           ('evidence_sha256', 'not-a-hash'), ('premium_currency', 'USD'),
                           ('multiplier', 'NaN'), ('taker_rate', '-1'), ('premium_cap', '0')):
            terms = self.terms()
            terms[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                dated_taker_fee(terms, '2025-01-06T00:00:00Z', '0.001', 1)

    def test_fee_rejects_negative_or_fractional_contract_count(self):
        from channel_validation.okx_dependencies import dated_taker_fee
        for premium, qty in (('-1', 1), ('0', 1), ('0.001', 0), ('0.001', '-1'), ('0.001', '1.5')):
            with self.assertRaises(ValueError):
                dated_taker_fee(self.terms(), '2025-01-06T00:00:00Z', premium, qty)

    def test_renamed_dependency_retry_rejected_before_io(self):
        from unittest.mock import patch
        from channel_validation.okx_dependencies import audit
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'retry'
            with patch('channel_validation.okx_dependencies.preflight') as preflight, self.assertRaises(ValueError):
                audit(output, lambda: None)
            preflight.assert_not_called()
            self.assertFalse(output.exists())

    def test_audit_http_failures_are_once_each_and_no_metrics(self):
        from unittest.mock import patch
        import urllib.error
        from channel_validation.okx_dependencies import audit, RUN_ID
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('channel_validation.okx_dependencies.OUTPUT_ROOT', root), \
                 patch('channel_validation.okx_dependencies.preflight', return_value={'census_hash': 'fixture'}), \
                 patch('channel_validation.okx_dependencies.urllib.request.build_opener') as build:
                build.return_value.open.side_effect = urllib.error.URLError('synthetic unavailable')
                result = audit(root/'runs'/RUN_ID/'artifacts/okx-dependencies', lambda: None)
            self.assertEqual(8, build.return_value.open.call_count)
            self.assertEqual(8, result['requests'])
            self.assertTrue(all(r['attempts'] == 1 for r in result['records']))
            self.assertIsNone(result['metrics'])
            self.assertFalse(result['dated_terms_complete'])
            self.assertFalse(result['exit_quotes_verified'])
            self.assertFalse(list(root.rglob('*.raw')))


class GoldSourceTests(unittest.TestCase):
    def raw(self, ticks=((0, 2010000, 2000000, 1., 2.), (500, 2020000, 2010000, 3., 4.))):
        import lzma
        from channel_validation.gold_history import RECORD
        return lzma.compress(b''.join(RECORD.pack(*t) for t in ticks), format=lzma.FORMAT_ALONE)

    def parse(self, raw=None, **kwargs):
        from channel_validation.gold_history import inspect_hour
        return inspect_hour(self.raw() if raw is None else raw, 1672747200000, **kwargs)

    def test_exact_source_budget_and_zero_based_month(self):
        from channel_validation.gold_history import request_plan
        plan = request_plan()
        self.assertEqual(19, plan['max_requests'])
        self.assertEqual(19, len(plan['requests']))
        self.assertEqual(16, sum(r['kind']=='hour_ticks' for r in plan['requests']))
        self.assertIn('/2023/00/03/12h_ticks.bi5', plan['requests'][0]['url'])
        self.assertIn('/2026/08/01/12h_ticks.bi5', plan['requests'][12]['url'])
        self.assertEqual(0, plan['retries'])
        self.assertEqual(300, plan['max_runtime_sec'])
        self.assertIsNone(plan['price_scale'])
        for key in ('redirects', 'credentials', 'paid_data', 's3_requester_pays', 'evaluation_eligible'):
            self.assertFalse(plan[key])
        self.assertEqual(canonical_hash(plan), canonical_hash(request_plan()))

    def test_raw_points_not_dollars_and_quote_size_not_volume(self):
        result = self.parse()
        self.assertEqual(2, result['records'])
        self.assertEqual(2000000, result['first']['bid_points'])
        self.assertEqual(500, result['last']['ts_ms']-result['first']['ts_ms'])
        self.assertEqual([2000000, 2010000, 2000000, 2010000], result['bid_ohlc_points'])
        self.assertEqual(10000, result['min_spread_points'])
        self.assertIsNone(result['price_scale'])
        self.assertIsNone(result['trading_volume'])
        self.assertFalse(result['price_units_verified'])
        self.assertFalse(result['quote_sequence_certified'])
        self.assertFalse(result['evaluation_eligible'])

    def test_empty_archive_not_closed_session_or_zero_return(self):
        result = self.parse(self.raw(()))
        self.assertEqual('EMPTY_ARCHIVE_NOT_CALENDAR_EVIDENCE', result['status'])
        self.assertIsNone(result['first'])
        self.assertIsNone(result['bid_ohlc_points'])
        self.assertFalse(result['no_ticks_means_closed'])

    def test_incomplete_concatenated_or_partial_record_rejected(self):
        import lzma
        for raw in (self.raw()[:-1], self.raw()+self.raw(), self.raw()+b'extra',
                    lzma.compress(b'partial', format=lzma.FORMAT_ALONE)):
            with self.subTest(raw=raw[:10]), self.assertRaises(ValueError):
                self.parse(raw)

    def test_corrupt_or_wrong_container_rejected(self):
        import lzma
        for raw in (b'not lzma', lzma.compress(b'')):
            with self.assertRaises((lzma.LZMAError, ValueError)):
                self.parse(raw)

    def test_decoded_budget_and_stop_checked(self):
        with self.assertRaises(ValueError):
            self.parse(decoded_cap=20)
        def stop():
            raise TimeoutError('synthetic stop')
        with self.assertRaises(TimeoutError):
            self.parse(check=stop)

    def test_out_of_hour_backward_crossed_and_nonfinite_rejected(self):
        cases = (
            ((3600000, 100, 99, 1., 1.),),
            ((2, 100, 99, 1., 1.), (1, 100, 99, 1., 1.)),
            ((0, 98, 99, 1., 1.),), ((0, 100, 0, 1., 1.),),
            ((0, 100, 99, float('nan'), 1.),), ((0, 100, 99, 1., -1.),),
        )
        for ticks in cases:
            with self.subTest(ticks=ticks), self.assertRaises(ValueError):
                self.parse(self.raw(ticks))

    def test_same_millisecond_quotes_are_preserved(self):
        result = self.parse(self.raw(((5, 100, 100, 0., 0.), (5, 101, 100, 1., 2.))))
        self.assertEqual(2, result['records'])
        self.assertEqual(1, result['same_timestamp_records'])
        self.assertEqual(1, result['locked_quotes'])

    def records(self):
        from channel_validation.gold_history import request_plan, inspect_hour
        return [dict(request=r, status='RAW_POINT_QUOTES_VALID', parsed=inspect_hour(self.raw(), r['start_ms']))
                for r in request_plan()['requests'][:4]]

    def test_four_hour_points_no_future_availability(self):
        from channel_validation.gold_history import four_hour_diagnostics
        records = self.records()
        result = four_hour_diagnostics(records)[0]
        self.assertTrue(result['all_four_files_valid'])
        self.assertEqual(8, result['records'])
        self.assertEqual(records[0]['request']['start_ms']+4*3600000, result['available_not_before_ms'])
        self.assertFalse(result['calendar_certified'])
        self.assertFalse(result['evaluation_eligible'])

    def test_missing_empty_and_duplicate_hours_not_filled(self):
        from channel_validation.gold_history import four_hour_diagnostics
        for change in ('missing','empty','duplicate'):
            records = self.records()
            if change == 'missing': records.pop()
            if change == 'empty': records[0]['status']='EMPTY_ARCHIVE_NOT_CALENDAR_EVIDENCE'
            if change == 'duplicate': records[0]=records[1]
            result = four_hour_diagnostics(records)[0]
            self.assertFalse(result['all_four_files_valid'])
            self.assertNotIn('bid_ohlc_points', result)

    def test_millisecond_grid_is_explicit(self):
        from channel_validation.gold_history import inspect_hour
        with self.assertRaises(ValueError):
            inspect_hour(self.raw(), 1672747200001)

    def test_named_retry_rejected_before_network(self):
        from unittest.mock import patch
        from channel_validation.gold_history import audit
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'retry'
            with patch('channel_validation.gold_history.request_plan') as plan, self.assertRaises(ValueError):
                audit(output, lambda: None)
            plan.assert_not_called()
            self.assertFalse(output.exists())

    def test_unavailable_source_once_each_not_calendar_evidence(self):
        from unittest.mock import patch
        import urllib.error
        from channel_validation.gold_history import audit, RUN_ID
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('channel_validation.gold_history.OUTPUT_ROOT', root), \
                 patch('channel_validation.gold_history.urllib.request.build_opener') as build:
                build.return_value.open.side_effect=urllib.error.URLError('synthetic unavailable')
                result=audit(root/'runs'/RUN_ID/'artifacts/gold-history-audit', lambda: None)
            self.assertEqual(19, build.return_value.open.call_count)
            self.assertEqual(19, result['requests'])
            self.assertIsNone(result['metrics'])
            self.assertFalse(result['historical_calendar_inferred'])
            self.assertTrue(all(not r['all_four_files_valid'] for r in result['four_hour_samples']))


class GoldUnattemptedTests(unittest.TestCase):
    def parent(self, root, change=None):
        from datetime import datetime, timezone, timedelta
        from channel_validation.gold_history import RUN_ID, request_plan
        parent=root/'runs'/RUN_ID
        runtime={'synthetic': 'fixture'}
        rh=canonical_hash(runtime)
        data={
            'intent.json':dict(runtime_hash=rh, runtime=runtime),
            'completion.json':dict(status='STOPPED_INCOMPLETE', exit_code=2, runtime_hash=rh, plan_hash=build_plan()['plan_hash']),
            'failure.json':dict(error='The read operation timed out', retry_authorized=False),
            'owner.json':dict(worker_started_utc=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()),
        }
        if change == 'error': data['failure.json']['error']='corruption'
        if change == 'runtime': data['intent.json']['runtime_hash']='bad'
        if change == 'elapsed': data['owner.json']['worker_started_utc']='2000-01-01T00:00:00Z'
        for name, value in data.items(): write_immutable(parent/name,value)
        plan=request_plan()
        write_immutable(parent/'artifacts/gold-history-audit/request-plan.json', dict(**plan, request_plan_hash=canonical_hash(plan)))
        if change == 'progress': write_immutable(parent/'artifacts/gold-history-audit/01.receipt.json', {})
        return rh

    def test_exact_parent_first_request_timeout_required(self):
        from unittest.mock import patch
        from channel_validation.gold_history import remaining_preflight
        for change in (None,'error','runtime','elapsed','progress'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                rh=self.parent(root, change)
                with patch('channel_validation.gold_history.OUTPUT_ROOT',root), \
                     patch('channel_validation.gold_history.PARENT_RUNTIME',rh):
                    if change is not None:
                        with self.assertRaises(ValueError): remaining_preflight()
                    else:
                        proof=remaining_preflight()
                        self.assertTrue(proof['first_request_not_retried'])
                        self.assertLessEqual(proof['parent_elapsed_sec'],60)

    def test_socket_timeouts_receipted_without_repeating_first_url(self):
        from unittest.mock import patch
        from channel_validation.gold_history import audit, request_plan, REMAINING_RUN_ID
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            rh=self.parent(root)
            with patch('channel_validation.gold_history.OUTPUT_ROOT',root), \
                 patch('channel_validation.gold_history.PARENT_RUNTIME',rh), \
                 patch('channel_validation.gold_history.urllib.request.build_opener') as build:
                build.return_value.open.side_effect=TimeoutError('synthetic socket timeout')
                output=root/'runs'/REMAINING_RUN_ID/'artifacts/gold-history-audit'
                result=audit(output,lambda:None,remaining=True)
            urls=[c.args[0].full_url for c in build.return_value.open.call_args_list]
            self.assertEqual([r['url'] for r in request_plan()['requests'][1:]],urls)
            self.assertEqual(18,result['requests'])
            self.assertEqual(19,result['cumulative_requests'])
            self.assertEqual(18,len(list(output.glob('*.attempt.json'))))
            self.assertEqual(18,len(list(output.glob('*.receipt.json'))))
            self.assertTrue(all(r['bytes_read_unknown'] for r in result['records']))
            self.assertIsNone(result['metrics'])

    def test_control_stop_is_not_swallowed_as_source_timeout(self):
        from unittest.mock import patch
        import io
        from channel_validation.gold_history import audit, RUN_ID
        calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls > 1: raise TimeoutError('synthetic stop')
        response=io.BytesIO(b'data')
        response.status=200
        response.headers={'Content-Length':'4'}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('channel_validation.gold_history.OUTPUT_ROOT',root), \
                 patch('channel_validation.gold_history.urllib.request.build_opener') as build:
                build.return_value.open.return_value=response
                with self.assertRaises(TimeoutError):
                    audit(root/'runs'/RUN_ID/'artifacts/gold-history-audit',check)
            self.assertEqual(1,build.return_value.open.call_count)
            self.assertEqual(1,len(list(root.rglob('*.attempt.json'))))
            self.assertEqual(0,len(list(root.rglob('*.receipt.json'))))


class HistDataTests(unittest.TestCase):
    def form(self, **changes):
        from channel_validation.histdata import FIELDS, ACTION
        fields = dict(FIELDS, tk='a'*32)
        fields.update(changes)
        return ('<form id="file_down" method="post" action="'+ACTION+'">'+''.join(
            f'<input type="hidden" name="{k}" value="{v}">' for k,v in fields.items())+'</form>').encode()

    def archive(self, body=None, extras=None):
        import io, zipfile
        from channel_validation.histdata import MEMBER
        if body is None:
            body=b'20230103 065959123,1840.01,1840.11,0\n20230103 070000000,1840.02,1840.12,0\n'
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr(MEMBER,body)
            for name,content in (extras or {}).items(): z.writestr(name,content)
        return stream.getvalue()

    def response(self, raw):
        import io
        value=io.BytesIO(raw)
        value.status=200
        value.headers={'Content-Length':str(len(raw))}
        return value

    def test_fixed_acquisition_not_parameter_change(self):
        from channel_validation.histdata import request_plan, PAGE
        p=request_plan()
        self.assertEqual(2,p['max_requests'])
        self.assertEqual(0,p['retries'])
        self.assertEqual(300,p['max_runtime_sec'])
        self.assertEqual(32*1024**2,p['archive_cap'])
        self.assertIn('/XAUUSD/2023/1',PAGE)
        self.assertFalse(p['source_probe'])
        self.assertFalse(p['evaluation_eligible'])
        self.assertEqual(canonical_hash(p),canonical_hash(request_plan()))

    def test_exact_form_no_external_post_or_scope_change(self):
        from channel_validation.histdata import download_form
        import urllib.parse
        form=self.form()
        self.assertEqual(['202301'],urllib.parse.parse_qs(download_form(form).decode())['datemonth'])
        for raw in (self.form(datemonth='202302'),self.form(fxpair='BTCUSD'),self.form(tk='bad'),
                    self.form(secret='no'),form.replace(b'www.histdata.com/get.php',b'evil.example/get.php'),
                    form.replace(b'method="post"',b'method="get"'),form+form,
                    form.replace(b'</form>',b''),form.replace(b'name="date"',b'name="tk"')):
            with self.assertRaises(ValueError): download_form(raw)

    def test_public_same_host_http_action_upgraded_only(self):
        from channel_validation.histdata import download_form
        self.assertEqual(download_form(self.form()),download_form(self.form().replace(b'https:',b'http:')))
        with self.assertRaises(ValueError):
            download_form(self.form().replace(b'https://www.',b'http://user@www.'))

    def test_status_and_payment_forms_are_never_submitted(self):
        from channel_validation.histdata import download_form
        good=self.form()
        status=good.replace(b'file_down',b'file_status').replace(b'/get.php',b'/getStatus.php')
        payment=b'<form id="payment" method="post" action="https://evil.example"><input type="hidden" name="pay" value="100"></form>'
        self.assertEqual(download_form(good),download_form(good+status+payment))
        with self.assertRaises(ValueError): download_form(status+payment)

    def test_cached_archive_phase_does_not_refetch_page(self):
        from unittest.mock import patch
        from channel_validation.histdata import acquire, ARCHIVE_RUN_ID, download_form, ACTION
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('channel_validation.histdata.OUTPUT_ROOT',root), \
                 patch('channel_validation.histdata.cached_form_preflight',return_value=({'fixture':True},download_form(self.form()))), \
                 patch('channel_validation.histdata.urllib.request.build_opener') as build:
                build.return_value.open.return_value=self.response(self.archive())
                r=acquire(root/'runs'/ARCHIVE_RUN_ID/'artifacts/histdata-sample',lambda:None,cached=True)
            self.assertEqual(1,build.return_value.open.call_count)
            request=build.return_value.open.call_args.args[0]
            self.assertEqual(ACTION,request.full_url)
            self.assertEqual('POST',request.get_method())
            self.assertEqual(2,r['cumulative_requests'])
            self.assertFalse(r['page_refetched'])

    def test_cached_parent_hash_scope_progress_and_budget(self):
        from unittest.mock import patch
        from datetime import datetime,timezone,timedelta
        from channel_validation.histdata import cached_form_preflight, request_plan, RUN_ID, PAGE
        import hashlib
        for change in (None,'page','progress','runtime','elapsed','post'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                parent=root/'runs'/RUN_ID
                artifacts=parent/'artifacts/histdata-sample'
                artifacts.mkdir(parents=True)
                raw=self.form().ljust(31616,b' ')
                sha=hashlib.sha256(raw).hexdigest()
                (artifacts/'download-page.html').write_bytes(raw if change!='page' else b'corrupt')
                runtime={'synthetic':True}
                rh=canonical_hash(runtime)
                record=dict(url=PAGE,method='GET',attempts=1,status='SOURCE_UNAVAILABLE_OR_INVALID',
                            response_cap=1000000,http_status=200,
                            body=dict(bytes_read=31616,declared_length=None,complete=True,reason='COMPLETE'),
                            error='Unexpected public download form',raw_file='download-page.html',sha256=sha)
                audit=dict(runtime_binding=runtime,plan_hash=build_plan()['plan_hash'],records=[record],requests=1,archive_parsed=False)
                if change=='post': audit['records'].append({'method':'POST'})
                ah=canonical_hash(audit)
                write_immutable(artifacts/'audit.json',dict(**audit,audit_hash=ah))
                write_immutable(artifacts/'01.receipt.json',record)
                write_immutable(artifacts/'01.attempt.json',{})
                plan=request_plan()
                write_immutable(artifacts/'request-plan.json',dict(**plan,request_plan_hash=canonical_hash(plan)))
                write_immutable(parent/'completion.json',dict(status='COMPLETE',exit_code=0,
                    runtime_hash='bad' if change=='runtime' else rh,plan_hash=build_plan()['plan_hash']))
                at=datetime.now(timezone.utc)-timedelta(seconds=100 if change=='elapsed' else 10)
                write_immutable(parent/'owner.json',dict(worker_started_utc=at.isoformat()))
                if change=='progress': write_immutable(artifacts/'02.attempt.json',{})
                with patch('channel_validation.histdata.OUTPUT_ROOT',root), \
                     patch('channel_validation.histdata.PARENT_RUNTIME',rh), \
                     patch('channel_validation.histdata.PARENT_AUDIT',ah), \
                     patch('channel_validation.histdata.PAGE_SHA',sha):
                    if change is None:
                        proof,payload=cached_form_preflight()
                        self.assertFalse(proof['page_refetched'])
                        self.assertIn(b'fxpair=XAUUSD',payload)
                    else:
                        with self.assertRaises(ValueError): cached_form_preflight()

    def test_fixed_est_utc_and_bar_end_not_backtest(self):
        from channel_validation.histdata import inspect_zip, EST
        from datetime import datetime,timezone
        result=inspect_zip(self.archive())
        self.assertEqual(2,result['rows'])
        self.assertEqual(2,len(result['four_hour_diagnostics']))
        self.assertEqual('2023-01-03T11:59:59.123000+00:00',datetime.fromtimestamp(result['first_ms']/1000,timezone.utc).isoformat())
        self.assertEqual(-18000,datetime(2023,7,1,tzinfo=EST).utcoffset().total_seconds())
        for bar in result['four_hour_diagnostics']:
            self.assertGreater(bar['end_ms'],bar['last_tick_ms'])
            self.assertFalse(bar['complete_session_verified'])
        self.assertFalse(result['evaluation_eligible'])
        self.assertIsNone(result['metrics'])

    def test_quotes_invalid_month_schema_crossed_nan_volume(self):
        from channel_validation.histdata import inspect_zip
        for row in (b'20230201 000000000,1,2,0', b'20230103 000000,1,2,0',
                    b'20230103 240000000,1,2,0', b'20230103 000000000,2,1,0',
                    b'20230103 000000000,NaN,2,0', b'20230103 000000000,1,2,3',
                    b'20230103 000000000,0,2,0', b''):
            with self.assertRaises(ValueError): inspect_zip(self.archive(row))

    def test_equal_time_retained_but_reversal_rejected(self):
        from channel_validation.histdata import inspect_zip
        row=b'20230103 000000000,1,2,0\n'
        r=inspect_zip(self.archive(row+row))
        self.assertEqual(2,r['rows'])
        self.assertEqual(1,r['equal_time_ticks'])
        with self.assertRaises(ValueError):
            inspect_zip(self.archive(b'20230104 000000000,1,2,0\n'+row))

    def test_gap_is_not_calendar_or_synthetic_bars(self):
        from channel_validation.histdata import inspect_zip
        r=inspect_zip(self.archive(b'20230103 000000000,1,2,0\n20230105 000000000,1,2,0\n'))
        self.assertEqual(2,len(r['four_hour_diagnostics']))
        self.assertEqual(1,r['gaps_over_one_minute'])
        self.assertEqual(172800000,r['max_observed_gap_ms'])
        self.assertFalse(r['calendar_certified'])
        self.assertFalse(r['missing_gaps_filled'])

    def test_zip_crc_truncated_paths_member_budget(self):
        import zipfile
        from unittest.mock import patch
        from channel_validation.histdata import inspect_zip, MEMBER
        for name in ('../bad.txt','evil.exe','C:bad.txt','dir\\bad.txt','dir/bad.txt'):
            with self.assertRaises(ValueError): inspect_zip(self.archive(extras={name:b'no'}))
        with self.assertRaises(zipfile.BadZipFile): inspect_zip(self.archive()[:-15])
        with patch('channel_validation.histdata.DECODE_CAP',10):
            with self.assertRaises(ValueError): inspect_zip(self.archive())
        with patch('channel_validation.histdata.ROW_CAP',1):
            with self.assertRaises(ValueError): inspect_zip(self.archive())
        with self.assertRaises(ValueError): inspect_zip(self.archive(b'x'*257))
        raw=bytearray(self.archive())
        central=raw.index(b'PK\x01\x02')
        raw[central+16] ^= 1
        with self.assertRaises(zipfile.BadZipFile): inspect_zip(bytes(raw))
        r=inspect_zip(self.archive(extras={'report.txt':b'provider report'}))
        self.assertEqual(2,r['rows'])

    def test_success_two_requests_and_immutable_receipts(self):
        from unittest.mock import patch
        from channel_validation.histdata import acquire, RUN_ID, PAGE, ACTION
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            output=root/'runs'/RUN_ID/'artifacts/histdata-sample'
            with patch('channel_validation.histdata.OUTPUT_ROOT',root), \
                 patch('channel_validation.histdata.urllib.request.build_opener') as build:
                build.return_value.open.side_effect=[self.response(self.form()),self.response(self.archive())]
                r=acquire(output,lambda:None)
                with self.assertRaises(FileExistsError): acquire(output,lambda:None)
                with self.assertRaises(ValueError): acquire(root/'renamed',lambda:None)
            calls=build.return_value.open.call_args_list
            self.assertEqual([PAGE,ACTION],[c.args[0].full_url for c in calls])
            self.assertEqual(['GET','POST'],[c.args[0].get_method() for c in calls])
            self.assertEqual(2,len(list(output.glob('*.attempt.json'))))
            self.assertEqual(2,len(list(output.glob('*.receipt.json'))))
            self.assertTrue(r['archive_parsed'])
            self.assertIsNone(r['metrics'])
            self.assertFalse(r['evaluation_eligible'])

    def test_timeout_and_http_failure_no_post_no_retry(self):
        import urllib.error
        from unittest.mock import patch
        from channel_validation.histdata import acquire, RUN_ID
        for error in (TimeoutError('synthetic timeout'),urllib.error.HTTPError('url',503,'unavailable',{},None)):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                with patch('channel_validation.histdata.OUTPUT_ROOT',root), \
                     patch('channel_validation.histdata.urllib.request.build_opener') as build:
                    build.return_value.open.side_effect=error
                    r=acquire(root/'runs'/RUN_ID/'artifacts/histdata-sample',lambda:None)
                self.assertEqual(1,build.return_value.open.call_count)
                self.assertFalse(r['archive_parsed'])
                self.assertFalse(r['retry_authorized'])

    def test_wrong_form_and_oversize_archive_no_more_network(self):
        from unittest.mock import patch
        from channel_validation.histdata import acquire, RUN_ID, DOWNLOAD_CAP
        large=self.response(b'not downloaded')
        large.headers={'Content-Length':str(DOWNLOAD_CAP+1)}
        for responses in ([self.response(self.form(datemonth='202401'))], [self.response(self.form()),large]):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                with patch('channel_validation.histdata.OUTPUT_ROOT',root), \
                     patch('channel_validation.histdata.urllib.request.build_opener') as build:
                    build.return_value.open.side_effect=responses
                    r=acquire(root/'runs'/RUN_ID/'artifacts/histdata-sample',lambda:None)
                self.assertEqual(len(responses),r['requests'])
                self.assertFalse(r['archive_parsed'])
                self.assertEqual([],list(root.rglob('*.zip')))

    def test_cooperative_stop_not_misclassified_timeout(self):
        from unittest.mock import patch
        from channel_validation.histdata import acquire, RUN_ID
        calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls > 1: raise TimeoutError('synthetic stop')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('channel_validation.histdata.OUTPUT_ROOT',root), \
                 patch('channel_validation.histdata.urllib.request.build_opener') as build:
                build.return_value.open.return_value=self.response(self.form())
                with self.assertRaises(TimeoutError):
                    acquire(root/'runs'/RUN_ID/'artifacts/histdata-sample',check)
            self.assertEqual(1,build.return_value.open.call_count)
            self.assertEqual([],list(root.rglob('*.receipt.json')))


class HistDataLocalCensusTests(unittest.TestCase):
    def test_named_provider_report_crc_and_no_arbitrary_members(self):
        import io
        from channel_validation.histdata_local import census, REPORT_MEMBER
        good=HistDataTests().archive(extras={REPORT_MEMBER:b'provider claims, not independently certified'})
        r=census(io.BytesIO(good))
        self.assertTrue(r['zip_crc_verified'])
        self.assertFalse(r['provider_claims_independently_verified'])
        self.assertIn('provider claims',r['provider_report_text'])
        with self.assertRaises(ValueError):
            census(io.BytesIO(HistDataTests().archive(extras={'wrong.txt':b'no'})))

    def test_crc_full_file_but_semantics_only_fixed_prefix(self):
        import io
        from unittest.mock import patch
        from channel_validation.histdata_local import census
        raw=HistDataTests().archive(b'20230103 000000000,1,2,0\n'*5)
        with patch('channel_validation.histdata_local.SAMPLE_ROWS',2):
            r=census(io.BytesIO(raw))
        self.assertTrue(r['zip_crc_verified'])
        self.assertEqual(5,r['physical_csv_rows'])
        self.assertEqual(2,r['validated_sample_rows'])
        self.assertEqual(3,r['unvalidated_rows'])
        self.assertFalse(r['full_month_semantics_verified'])
        self.assertFalse(r['evaluation_eligible'])

    def test_bad_crc_or_budget_or_first_sample_rejected(self):
        import io,zipfile
        from unittest.mock import patch
        from channel_validation.histdata_local import census
        raw=bytearray(HistDataTests().archive())
        raw[raw.index(b'PK\x01\x02')+16] ^= 1
        with self.assertRaises(zipfile.BadZipFile): census(io.BytesIO(raw))
        with patch('channel_validation.histdata_local.DECODE_CAP',1):
            with self.assertRaises(ValueError): census(io.BytesIO(HistDataTests().archive()))
        with self.assertRaises(ValueError): census(io.BytesIO(HistDataTests().archive(b'invalid\n')))

    def test_last_row_no_newline_and_invalid_tail_not_certified(self):
        import io
        from unittest.mock import patch
        from channel_validation.histdata_local import census
        raw=HistDataTests().archive(b'20230103 000000000,1,2,0\ninvalid tail')
        with patch('channel_validation.histdata_local.SAMPLE_ROWS',1): r=census(io.BytesIO(raw))
        self.assertEqual(2,r['physical_csv_rows'])
        self.assertEqual(1,r['unvalidated_rows'])
        self.assertFalse(r['full_month_semantics_verified'])


class HistDataMonthTests(unittest.TestCase):
    def scan(self, body, rows, **kwargs):
        import io
        from channel_validation.histdata_month import scan
        return scan(io.BytesIO(HistDataTests().archive(body)), rows, **kwargs)

    def test_all_rows_chunks_hashes_and_determinism(self):
        import hashlib
        from channel_validation.histdata_month import verify_chunks
        body=b'20230103 000000000,1,2,0\n'*5
        chunks=[]
        result=self.scan(body,5,chunk_rows=2,on_chunk=chunks.append)
        self.assertEqual(result,self.scan(body,5,chunk_rows=2))
        self.assertEqual(5,result['validated_rows'])
        self.assertEqual(hashlib.sha256(body).hexdigest(),result['csv_sha256'])
        self.assertEqual([2,2,1],[c['rows'] for c in chunks])
        self.assertEqual(4,result['equal_time_ticks'])
        self.assertEqual(5,verify_chunks(chunks)['rows'])
        self.assertFalse(result['evaluation_eligible'])
        self.assertFalse(result['calendar_certified'])
        self.assertIsNone(result['metrics'])
        chunks[1]['row_start']=999
        with self.assertRaises(ValueError): verify_chunks(chunks)

    def test_boundary_time_order_and_bad_tail(self):
        good=b'20230103 000001000,1,2,0\n'*2
        for tail in (b'20230103 000000000,1,2,0\n',b'20230103 000002000,3,2,0\n',b'bad\n'):
            with self.assertRaises(ValueError): self.scan(good+tail,3,chunk_rows=2)

    def test_row_count_exact_not_prefix_acceptance(self):
        body=b'20230103 000000000,1,2,0\n'*3
        for expected in (2,4):
            with self.assertRaises(ValueError): self.scan(body,expected,chunk_rows=2)

    def test_gap_and_utc_month_boundary_not_calendar(self):
        body=b'20230102 180000000,1,2,0\n20230131 235959999,2,3,0'
        result=self.scan(body,2,chunk_rows=1)
        self.assertEqual(1,result['gaps_over_24h'])
        self.assertEqual(2,len(result['observed_utc_days']))
        self.assertIn('2023-02-01',result['observed_utc_days'])
        self.assertEqual(2,result['observed_four_hour_buckets'])
        self.assertFalse(result['missing_gaps_filled'])

    def test_crc_including_auxiliary_report_and_resource_bounds(self):
        import io,zipfile
        from channel_validation.histdata_month import scan
        from channel_validation.histdata_local import REPORT_MEMBER
        raw=bytearray(HistDataTests().archive(extras={REPORT_MEMBER:b'report'}))
        offset=raw.index(b'PK\x01\x02',raw.index(b'PK\x01\x02')+1)
        raw[offset+16] ^= 1
        with self.assertRaises(zipfile.BadZipFile): scan(io.BytesIO(raw),2)
        with self.assertRaises(ValueError): self.scan(b'20230103 000000000,1,2,0\n',1,max_decoded_bytes=10)
        with self.assertRaises(ValueError): self.scan(b'x'*257,1)
        with self.assertRaises(ValueError): self.scan(b'',0)
        with self.assertRaises(ValueError): self.scan(b'20230103 000000000,1,2,0\n',1,chunk_rows=0)

    def test_stop_after_chunk_never_returns_complete_result(self):
        chunks=[]
        def check():
            if chunks: raise TimeoutError('synthetic stop')
        with self.assertRaises(TimeoutError):
            self.scan(b'20230103 000000000,1,2,0\n'*5,5,chunk_rows=2,on_chunk=chunks.append,check=check)
        self.assertEqual(1,len(chunks))

    def test_chunk_chain_rejects_missing_reordered_and_rehashed_gap(self):
        import copy
        from channel_validation.histdata_month import verify_chunks
        chunks=[]
        self.scan(b'20230103 000000000,1,2,0\n'*5,5,chunk_rows=2,on_chunk=chunks.append)
        for broken in (chunks[1:],chunks[::-1],[chunks[0],chunks[2]]):
            with self.assertRaises(ValueError): verify_chunks(broken)
        broken=copy.deepcopy(chunks)
        broken[1]['byte_start']+=1
        broken[1]['chunk_hash']=canonical_hash({k:v for k,v in broken[1].items() if k!='chunk_hash'})
        with self.assertRaises(ValueError): verify_chunks(broken)


if __name__ == '__main__':
    unittest.main(verbosity=2)
