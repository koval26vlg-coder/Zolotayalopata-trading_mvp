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


if __name__ == '__main__':
    unittest.main(verbosity=2)
