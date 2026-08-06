# trading_mvp Fast-First v2: fixed PlanOnly hypothesis

Date: 2026-07-13
Mode: `PLAN_ONLY`
Status: frozen, not evaluated

## Goal

За один короткий доказательный цикл проверить одну новую non-Binance structural-edge гипотезу на уже собранной публичной истории. Результат должен быть только одним из трех: `ACCEPT_FOR_SHORT_EXECUTION_PROBE`, `REJECT` или `INSUFFICIENT_DATA`.

Оптимизируется net expectancy после полной стоимости исполнения, а не номинальный win rate. До исторического `ACCEPT` запрещены execution probe, paper-forward, API keys, live orders, leverage и margin.

## Frozen hypothesis

`venue_local_perp_residual_dispersion_reversion_v1`

После удаления venue-market beta аномально широкое однодневное распределение residual returns у ликвидных non-Binance perpetuals частично сходится в течение следующего дня. На каждой бирже независимо открывается market-neutral пара: long по минимальному residual и short по максимальному residual.

Это новая ветка:

- funding не используется как сигнал, а price-only PnL после costs обязан быть положительным;
- нет listing-age или launch-event условия;
- нет thin-market, стаканного, HFT или latency-сигнала;
- обе ноги находятся на одной бирже, поэтому это не MEXC/Gate spot dislocation;
- это однодневный residual reversal, а не ранее проверенный 30/60/90-day momentum;
- это symmetric long/short pair, а не long-only capitulation rebound.

## Frozen signal

- Venue: MEXC и Gate отдельно, без выбора лучшей биржи после OOS.
- Instrument: USDT linear perpetual, fully collateralized `1x` research assumption.
- Universe: `non_binance_baseline=true`, зафиксирован до OOS.
- Minimum history: 90 дней.
- Liquidity: trailing 30-day median quote volume не ниже `$5,000,000`.
- Minimum eligible markets: 12 на биржу.
- Return: `log(close_t / close_t-1)`.
- Venue benchmark: cross-sectional median return.
- Beta: rolling OLS with intercept, 20 завершенных дней, только до `t-1`.
- Dispersion: scaled MAD residuals.
- Regime: текущая dispersion не ниже `1.5x` trailing 20-day median dispersion.
- Tail gap: минимум `150 bps`.
- Entry: следующий daily open.
- Exit: close того же дня.
- Position: `$500` на каждую ногу, максимум одна пара на venue, без overlap.
- Grid, TP/SL и parameter selection отсутствуют.

## Economics

Единый `CostProfile` включает четыре ордера, maker-fill probability, taker fallback, spread, impact, slippage и rebalance buffer.

- MEXC normal cycle: `65 bps`; stress: `84 bps`.
- Gate normal cycle: `75 bps`; stress: `92 bps`.
- Funding учитывается только как неизбежный cash flow позиции.
- В stress сохраняется 100% adverse funding и только 50% favorable funding.
- Funding не может дать более 25% положительного OOS PnL.
- Capacity proxy: `0.0001 * trailing 30-day median quote volume`, минимум `$500` на ногу.

## Validation

- Main train: `2025-12-26..2026-05-14`, 140 дней.
- Main OOS: `2026-05-15..2026-07-13`, 60 дней.
- Walk-forward: пять frozen 20-day folds после initial 100-day train.
- Minimum OOS events: 20 total и 8 на каждую venue.
- OOS net expectancy: `> 0`.
- OOS profit factor: `>= 1.2`.
- Positive-event rate: `>= 60%`.
- Positive walk-forward folds: минимум 4 из 5.
- Обе venue должны иметь положительный OOS expectancy.
- Stress net PnL: `>= 0`.
- Price-only OOS net after costs: `> 0`.
- Top event и top base: не более 25% positive PnL каждый.
- Top venue: не более 75% positive PnL.
- Break-even holding period: не более одного дня.
- Hash mismatch, недостаточная coverage или недостаток events дают только `INSUFFICIENT_DATA`.

## Evidence seal

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v2\plans\fast_first_residual_dispersion_planonly_20260713.json`
- Plan hash: `a73a54627477030bea0d4c57395c717cf74b1a243862ef9f8726356780e50566`
- Plan file SHA-256: `3abde96e8b6aa279c74268edcb558d6a5012bb09251d7a1a695ba66f373a4115`
- Input Merkle SHA-256: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`
- Frozen inputs: 195 files, 97 contracts after explicit synthetic-proxy exclusions.

## Known limitation

Dataset сформирован из текущего top-volume universe и не содержит полноценной истории delisted/inactive membership. Поэтому даже прохождение всех исторических gates может разрешить только короткий forward execution probe. Оно не дает `PAPER_READY` и не разрешает live.

## Next allowed step

Реализовать deterministic no-grid evaluator, жестко привязанный к plan hash, и сначала проверить unit tests на look-ahead leakage, costs, split и verdict logic. Сам evaluator не запускать до прохождения этих проверок.

## Final result

- Run: `fast_first_v2_residual_dispersion_20260713_1845`.
- Verdict: `INSUFFICIENT_DATA`.
- Evidence seal: 195/195 inputs, Merkle hash совпал.
- Последний незавершенный daily bar исключен; закрытый OOS составил 59/60 дней.
- Frozen liquidity gate не оставил минимум 12 eligible markets: Gate пропущен 200/200 дней, MEXC 199/199 дней.
- Signals/events: `0/0`; поэтому PnL, expectancy, profit factor, win rate и capacity не являются измеренными результатами стратегии.
- Два deterministic evaluation совпали по result hash `f2edd8391b088fcec12214601ac8364adcea1fd651d8b9f0a9a135efc13f6e75`.
- Execution probe, grid, paper-forward, API keys и live не запускались.
- Эта ветка закрыта для ретюнинга на текущем датасете. Следующий разрешенный шаг: новая независимая Fast-First гипотеза в режиме PlanOnly.
