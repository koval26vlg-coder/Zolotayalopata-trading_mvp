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
from channel_validation.adapters import (MissingEvidence, pair_economics, wallets, grid, run_specialized, first_after)
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


class EvidenceTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
