# trading_mvp daily momentum candidate gates

Дата: 2026-07-09
Агент: Codex

## Запрос
Продолжить цель без лишних подтверждений: найти/доказать/отбросить trading edge через данные, OOS, walk-forward, stress, economics и gates.

## Что сделано
- Проверен active-run gate после slow-liquidity replay.
- Подтверждено, что `slow_liquidity_fixed_v1` отвергнут: trades=144, net PnL=-420.96, expectancy=-2.923, OOS net PnL=-111.79, walk-forward ratio=0.
- `spot_perp_basis_mean_reversion_no_funding` прошел PlanOnly и availability preflight, но public probe отвергнут: 0/10 paired OK.
- Исправлен selector, чтобы он не возвращался в уже отвергнутый `slow_liquidity` после replay rejection.
- Добавлена fallback-ветка `cross_sectional_momentum_daily`.
- Обновлен `momentum_backtest.py`: base/VIP0 selection scenario, per-base attribution, rolling walk-forward, stress 2x slippage, zero/adverse funding, partial-fill/stale-exit buffer.
- Проведен research-only daily momentum backtest на existing daily dataset.
- Независимый subagent review вернул verdict `revise`, не `approve`; блокеры учтены в gates.

## Артефакты
- Slow-liquidity replay: `exports/trading-mvp/backtests/slow_liquidity_fixed_v1_replay_planonly_20260709_213021.json`
- Spot/perp public probe: `exports/trading-mvp/analysis/spot_perp_basis_public_probe_20260709_213455.json`
- Selector fix output: `exports/trading-mvp/analysis/structural_branch_planonly_20260709_214110.json`
- Daily momentum report: `exports/trading-mvp/backtests/momentum_daily_20260709_185507.json`
- Daily momentum validation: `exports/trading-mvp/analysis/cross_sectional_momentum_daily_validation_20260709_215555.json`

## Результат daily momentum
- Decision: `DAILY_CROSS_SECTIONAL_MOMENTUM_RESEARCH_CANDIDATE_REQUIRES_SURVIVORSHIP_AUDIT`
- Extended: OOS n=28, mean=161.352 bps/week, PF=2.004, hit=0.679, DD=19.756%, rolling WF positive ratio=0.889, top-base share=0.124.
- Non-Binance baseline: OOS n=28, mean=583.796 bps/week, PF=2.756, hit=0.643, DD=35.42%, rolling WF positive ratio=0.857, top-base share=0.221.
- Stress positive under +50% fee, legacy 39 bps, 2x slippage, zero funding, adverse funding 50%, partial-fill/stale-exit 25 bps.

## Ограничения
- Strategy is not accepted.
- No live orders, no API keys, no leverage/margin, no paper-forward, no grid.
- Survivorship bias remains unresolved: universe is current top-volume contracts, no delisted/dead/no-trade outcomes.
- Long/short perp live feasibility remains blocked by margin/shorting assumptions.
- Max drawdown policy is not accepted yet.

## Следующий шаг
Build survivorship/point-in-time universe audit and max drawdown/concentration policy for `cross_sectional_momentum_daily`. Do not paper-forward/live/API/grid.
