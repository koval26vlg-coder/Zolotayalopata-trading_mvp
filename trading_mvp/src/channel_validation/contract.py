from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / 'docs/plans/channel-strategy-validation-20261006-v1.json'
OUTPUT_ROOT = ROOT / 'docs/analysis/channel-strategy-validation-20261006'


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build_plan():
    rows = [
        ('relative_strength', 'Relative strength', ['bars_1h', 'pit_universe'], 'gate',
         dict(market_drop=-0.03, asset_return_min=0, top_n=3, lookback_hours=24, stop_atr=2, hold_hours=24)),
        ('trend_pullback', 'Trend pullback', ['bars_4h', 'pit_universe'], 'gate',
         dict(ema_fast=50, ema_slow=200, stop_atr=2, target_atr=4, hold_hours=72)),
        ('structure_break', 'Causal structure continuation', ['bars_4h', 'pit_universe'], 'gate',
         dict(pivot_left=2, pivot_right=2, stop_atr=2, target_atr=4, hold_hours=72)),
        ('normalized_line', 'ATR-normalized trend line', ['bars_4h', 'pit_universe'], 'gate',
         dict(pivot_left=2, pivot_right=2, slope_atr=0.1, stop_atr=2, target_atr=4, hold_hours=72)),
        ('book_continue', 'Orderbook continuation', ['books', 'tape', 'pit_universe'], 'gate',
         dict(levels=10, imbalance=0.6, buy_fraction=0.6, tape_seconds=30, hold_seconds=60)),
        ('book_reclaim', 'Orderbook reclaim', ['books', 'bars_1m', 'pit_universe'], 'gate',
         dict(levels=10, imbalance=0.6, drop_atr=3, drop_minutes=5, hold_seconds=60)),
        ('funding_carry', 'Spot-perpetual funding carry', ['paired_quotes', 'funding'], 'gate',
         dict(extra_bps=10, hold_hours=24, forecast='last_published_period_constant_rate')),
        ('funding_cross', 'Cross-venue funding carry', ['paired_quotes', 'funding'], 'gate_mexc',
         dict(extra_bps=10, hold_hours=24, prefunded=True)),
        ('spot_dislocation', 'Prefunded spot dislocation', ['paired_quotes', 'inventory'], 'gate_mexc',
         dict(extra_bps=5, rebalance='explicit_costed_reverse_route_only', prefunded=True)),
        ('basis_convergence', 'Positive spot-perpetual basis convergence', ['paired_quotes', 'funding'], 'gate',
         dict(lookback_hours=24, enter_z=2, exit_z=0.5, hold_hours=24, min_observations=24)),
        ('long_put', 'Long ATM put', ['option_chain', 'underlying_quotes', 'contract_specs'], 'okx',
         dict(strike_ratio=1, target_dte=30, hold_days=7, entry_weekday=0, entry_hour_utc=0)),
        ('cash_put', 'Cash-reserved short put', ['option_chain', 'underlying_quotes', 'contract_specs'], 'okx',
         dict(strike_ratio=0.9, target_dte=30, hold_days=7, entry_weekday=0, entry_hour_utc=0)),
        ('put_spread', 'Bear put spread', ['option_chain', 'underlying_quotes', 'contract_specs'], 'okx',
         dict(long_strike_ratio=1, short_strike_ratio=0.9, target_dte=30, hold_days=7, entry_weekday=0, entry_hour_utc=0)),
        ('fixed_grid', 'Spot-only weekly fixed grid', ['bars_1d', 'books', 'pit_universe'], 'gate',
         dict(width_atr=3, levels=7, recenter=False, borrow=False, exit_on_breach=True)),
        ('gold_macd', 'Gold MACD trend proxy', ['bars_4h', 'contract_specs', 'calendar'], 'gold',
         dict(macd_fast=12, macd_slow=26, macd_signal=9, ema=220, stop_atr=2, target_atr=6, hold_sessions=20)),
        ('dax_orb', 'DAX opening-range breakout', ['bars_5m', 'contract_specs', 'calendar'], 'dax',
         dict(range_minutes=60, trades_per_session=1, exit='session_close', stop='opposite_range')),
        ('gap_continue', 'US equity gap continuation', ['bars_5m', 'pit_equity_universe', 'calendar', 'corporate_actions'], 'us_equity',
         dict(gap_min=0.02, range_minutes=30, trades_per_session=1, exit='session_close')),
        ('gap_fade', 'US equity gap fade', ['bars_5m', 'pit_equity_universe', 'calendar', 'corporate_actions'], 'us_equity',
         dict(gap_min=0.02, range_minutes=30, trades_per_session=1, target='previous_close', exit='session_close')),
        ('aave_lending', 'Aave v3 Ethereum USDC lending', ['lending_index', 'gas', 'token_quotes', 'withdrawal_liquidity'], 'aave_v3_ethereum',
         dict(token='USDC', hold_days=30, borrow=False, recursive=False)),
        ('wallet_follow', 'Ethereum causal wallet following', ['dex_swaps', 'token_universe', 'gas', 'execution_quotes'], 'ethereum',
         dict(wallets=10, rank_days=30, delay_blocks=1, hold_hours=24, universe='verified_erc20_usdc_weth_pairs_asof')),
    ]
    models = []
    for number, (key, title, requirements, market, params) in enumerate(rows, 1):
        m = dict(number=number, id=key, title=title, market=market, parameters=params,
                 required_kinds=requirements, interpretation='OWN_FIXED_PROXY_NOT_GUEST_REPLICATION',
                 prior_evidence='docs/plans/2026-09-29-strategy-audit-and-next-goal-plan.md',
                 difference='Separate fixed model, liquid/as-of universe; never consume a terminally rejected legacy run',
                 source='docs/analysis/2026-10-06-anufriev-july-october-audit.md' if number <= 4 or 15 <= number <= 18
                        else 'D:/AionUi-Paperclip/docs/agent-log/2026-10-06--claude-code-анализ-youtube-хедлайнеры-ануфриев.md')
        m['model_hash'] = canonical_hash(m)
        models.append(m)
    p = dict(schema='channel_validation_plan_v1', program_id='channel_strategy_validation_20261006_v1',
             authorization='User explicitly requested implementation of the complete historical validation plan on 2026-10-06',
             models=models, atr_period=14,
             permissions=dict(public_history=True, paid_data=False, schedules=False, live_orders=False,
                              private_api=False, real_capital=False, actual_leverage=False, long_forward_collection=False),
             portfolio=dict(initial_cash=10000, risk_fraction=0.0025, max_position_fraction=0.1,
                            max_gross_fraction=1, spot_short=False, independent_models=True),
             periods=dict(development=['2023-01-01', '2025-01-01'], walk_forward=['2025-01-01', '2026-01-01'],
                          final=['2026-01-01', '2026-10-01'], warmup_start='2022-11-01'),
             universe=dict(primary='gate', quote='USDT', core=['BTC', 'ETH'], additional=8,
                           rank='previous_30_completed_UTC_days_median_quote_turnover', rebalance='month_start_UTC',
                           exclude=['stablecoin', 'wrapped', 'staked', 'derivative'], require_asof_types=True,
                           unknown_type='exclude_and_report', historical_delisted_required=True,
                           binance='REFERENCE_ONLY_NOT_EXECUTION', legacy_non_binance='ISOLATED'),
             execution=dict(next_bar=True, ambiguous_bar='STOP_FIRST', gap_stop='WORSE_OPEN',
                            candle_touch_is_fill=False, missing_quote='EXPLORATORY_ONLY',
                            default_fee_bps=10, fallback_adverse_bps_per_order=10,
                            stress_execution_multiplier=2, no_midprice_fills=True,
                            stop_exit_costs=True, no_synthetic_options=True),
             statistics=dict(family_size=20, alpha=0.05, correction='HOLM', bootstrap_replicates=5000,
                             block_days=7, seed=20261006, min_oos_trades=30, min_temporal_groups=20,
                             min_pf=1.2, positive_wf_folds=4, max_drawdown=0.1,
                             max_positive_pnl_single_event=0.25, max_positive_pnl_single_base=0.25,
                             min_oos_calendar_days=90, causal_certification_required=True),
             resource_limits=dict(max_runtime_sec=1800, max_input_bytes=2*1024**3, max_rows=2000000,
                                  max_source_probe_requests=12, max_source_response_bytes=1000000),
             excluded=dict(listing_momentum='EXTERNAL_PROJECT', premarket_depth='UNCHANGED_PAUSED',
                           closed_runs='NO_REOPEN', ai='NO_REPRODUCIBLE_SPEC_WITHOUT_FIXED_RULES',
                           prop='RISK_OVERLAY_ONLY_NO_CHALLENGE_PURCHASE'),
             result_ceiling='HISTORICAL_CANDIDATE_NOT_LIVE',
             unresolved_default='BLOCKED_DATA_NOT_ZERO_RETURN')
    p['plan_hash'] = canonical_hash(p)
    return p


def validate_plan(plan):
    expected = build_plan()
    if plan != expected:
        raise ValueError('Frozen plan mismatch; parameter search/refreeze requires a separate program')
    return plan


def runtime_binding():
    files = sorted(Path(__file__).parent.glob('*.py')) + [
        ROOT/'tools/run_channel_strategy_validation_visible.ps1',
        ROOT/'trading_mvp/tests/test_channel_validation.py',
        ROOT/'trading_mvp/src/global_market_writer_claim.py',
        ROOT/'tools/check_active_run_gate.ps1', ROOT/'tools/check_trading_mvp_autopilot.ps1']
    files = [p for p in files if p.is_file()]
    return {str(p.relative_to(ROOT)).replace('\\', '/'): file_hash(p) for p in files}
