# trading_mvp: One-Week Historical Edge Sprint

## Каноническая цель

За семь календарных дней получить воспроизводимый verdict для одной новой non-Binance стратегии на MEXC/Gate без grid-search, OOS-retune, private API и live orders. Результат недели обязан быть одним из:

- `ACCEPT_FOR_EXECUTION_PROBE`;
- `HISTORICAL_ACCEPT_AWAIT_EVENT`;
- `PAPER_FORWARD_READY`;
- `REJECT`;
- `INSUFFICIENT_DATA`.

Прибыль к фиксированной дате не обещается. Гарантируется ограниченный по времени доказательный цикл с окончательным статусом ветки. Высокий win rate не заменяет положительный net expectancy после базовых издержек.

## Активная гипотеза

- `hypothesis_id`: `cross_venue_perp_basis_convergence_history_v1`.
- Площадки: только MEXC и Gate.
- Инструменты: совпадающие USDT linear perpetual, canonical identity обязателен.
- Binance: только reference/exclusion; Binance Spot активы исключаются.
- Позиция: long perp на площадке с меньшим venue basis и short perp на площадке с большим basis.
- Номинал: `$500` на каждую ногу, fully collateralized, `1x`.
- Сигнал: только после закрытия 5m mark/index bar.
- Вход: open следующего 5m trade bar.
- Выход: `basis_spread_bps <= 20` либо 72 часа.
- `entry_threshold = stress_cycle_cost_bps + 20 bps exit + 20 bps safety`.
- TP/SL/trailing/grid и подбор threshold/hold по OOS запрещены.
- Funding обеих ног считается отдельно и не может скрыть отрицательный price-only PnL.

## Frozen economics

- Historical maker fill probability: `0`.
- MEXC perp taker: `8 bps` за операцию.
- Gate perp: `10 bps` за операцию до account-specific подтверждения.
- Полный цикл включает четыре операции, spread, impact, slippage, funding обеих ног и rebalance buffer.
- Stress: taker-only, p95 spread/impact, двойной rebalance buffer, 50% haircut только благоприятного funding; adverse funding сохраняется полностью.
- Rebates/VIP/promo не применяются без account-specific evidence.

Единственный runtime-источник экономики: `trading_mvp/src/costs.py` и замороженный `CostProfile` внутри PlanOnly.

## Universe contract

Shortlist строится до чтения OOS returns:

1. Canonical identity подтверждён внешним registry; join по одному ticker запрещён.
2. Актив отсутствует на Binance Spot.
3. На MEXC и Gate существуют USDT linear perpetual и все шесть 5m series: trade/mark/index на обеих площадках.
4. История обеих ног покрывает не менее 220 закрытых дней.
5. Исключаются stable, wrapped, staked, leveraged, LP, synthetic, pre-market, index и tokenized assets.
6. Train-only 7-day median quote volume худшей ноги не ниже `$1 млн`.
7. Формируются 12 primary и 8 reserve; reserve заменяет primary только из-за lifecycle/data-quality failure до OOS.
8. Менее восьми surviving canonical assets означает `INSUFFICIENT_EXECUTABLE_UNIVERSE`; пороги не ослабляются.

## Данные и split

- 220 полностью закрытых дней по `5m`.
- 20 дней warm-up.
- 100 дней train/feasibility.
- 100 закрытых OOS-дней.
- Пять непересекающихся OOS folds по 20 дней.
- Для каждой ноги: trade, mark, index candles и funding с фактическими settlement timestamps.
- Open bars, conflicting duplicates и overlapping pages отвергаются.
- Price gaps не интерполируются; gap более 15 минут разрывает эпизод и запрещает сквозной PnL.

## Реализованный интерфейс

`trading_mvp/run_mvp.ps1` предоставляет:

| Action | Ограничение | Назначение |
|---|---:|---|
| `fast-edge-basis-universe-build` | 600 сек | Canonical identity и bounded six-series availability |
| `fast-edge-basis-plan` | 600 сек | Freeze hypothesis/universe/costs/split/gates |
| `fast-edge-basis-history-collect` | 7200 сек | Public MEXC/Gate historical acquisition |
| `fast-edge-basis-history-quality` | 1800 сек | Coverage/alignment/lifecycle/gap audit и физический split |
| `fast-edge-basis-evaluate` | 1800 сек | Hash-bound train либо OOS, no-grid |
| `fast-edge-basis-probe-plan` | 600 сек | Freeze трёх execution windows |
| `fast-edge-basis-probe` | 1200-1800 сек | Public BBO/depth snapshots |
| `fast-edge-basis-report` | 1800 сек | Финальный sprint verdict |
| `fast-edge-basis-paper-init/observe/status` | bounded | Paper-only WAL/state/reconciliation |

Каждая frozen стадия выполняется из одного content-addressed code snapshot и проверяет `plan_hash`, `code_snapshot_hash`, `universe_hash` и входные hashes. Resume history collect использует исходный immutable time range и не может незаметно сдвинуть окно вперёд.

## Resource-scoped gate

- Только один `market_data_writer` одновременно.
- Collector/probe публикует `locks`, `owner_output_prefix`, `code_snapshot_hash`, `parallel_safe_actions`, `forbidden_overlapping_actions` и `parallel_parent_run_id`.
- Во время writer разрешены только изолированные code work, unit tests, fixtures, static analysis и вычисления по другому immutable cache.
- Запрещены второй collector/probe, consumer незавершённого owner output, postprocess и grid-search.
- Collector/probe запускается только в видимом терминале. Timeout/network error создаёт `STOPPED_INCOMPLETE`, никогда частичный ACCEPT.

## Acceptance gates

### Data quality

- Каждая trade/mark/index series: coverage `>=98%`.
- Dual-venue aligned coverage: `>=95%`.
- Funding settlement coverage: `>=98%`.
- Нет open bars и conflicting duplicate timestamps.
- После фильтра остаётся минимум восемь assets.

### Train feasibility

- Минимум 20 независимых episodes на 10 различных датах.
- Присутствуют оба направления: MEXC-cheap и Gate-cheap.
- При провале train OOS shard не открывается.

### Historical OOS

- Минимум 40 независимых episodes, 20 дат и 8 assets.
- Price-only и total net expectancy после costs `>0`.
- Profit factor `>=1.2`.
- Не менее `4/5` положительных folds.
- Stress net PnL `>=0`.
- Нижняя cluster-bootstrap 95% граница expectancy `>0`.
- Каждое направление отдельно неотрицательно.
- Одна база, дата или episode не формирует более 25% положительного PnL.
- Max drawdown `<=10%` одновременно обеспеченного капитала.
- Повтор на тех же hashes обязан дать идентичный result hash.

Historical OHLCV не доказывает fills/capacity. Максимальный historical verdict: `ACCEPT_FOR_EXECUTION_PROBE`.

### Execution и paper

- Три 20-минутных окна, разделённые минимум четырьмя часами.
- В каждом окне `>=180` valid dual-venue snapshots, coverage `>=80%`.
- Capacity `>= $500` на каждую ногу, worst-leg p95 impact `<=10 bps`.
- `PAPER_FORWARD_READY` требует historical ACCEPT, три качественных probe и хотя бы одно qualifying forward event.
- `LIVE_REVIEW_ELIGIBLE` находится вне недельного спринта и требует 15 независимых paper events, positive paper net и отсутствие reconciliation/kill-switch/data-quality нарушений.

## Stop rules

- Отрицательный OOS, walk-forward либо stress закрывает ветку без ретюнинга.
- Недостаточная выборка даёт `INSUFFICIENT_DATA`, не искусственный ACCEPT.
- Funding carry, spot dislocation, HFT, listing-event и slow-liquidity на прежних данных не повторяются.
- Новые биржи и ручное расширение universe запрещены в этом sprint.
- При reject итог: `NO_WEEKLY_EDGE_FOUND_MEXC_GATE`.
- Private API, live orders, leverage и margin не входят в sprint.

## Текущий статус

На 2026-07-15 инженерный контур реализован и проверен. Видимый bounded universe preflight завершился за `92.276` секунды: `12` кандидатов проверены, сетевых ошибок процесса нет. Первичный артефакт выдал `INSUFFICIENT_EXECUTABLE_UNIVERSE`, но последующая проверка тела HTTP 400 установила техническую причину: Gate public 5m candles возвращает `Maximum 10000 points recently are allowed`. Это около `34.722` дня вместо замороженных `220` дней.

Финальный append-only verdict ветки: `INSUFFICIENT_DATA` с reason code `GATE_5M_PUBLIC_HISTORY_RETENTION_LT_FROZEN_220D`. Первичный артефакт сохранён неизменным; его семантика исправлена отдельным hash-bound closure report. Это не отрицательный результат стратегии: edge не был оценён, OOS/PnL не читались.

Следующей команды внутри этой frozen-ветки нет. Запрещены historical collect, train/OOS evaluation, execution probe, paper-forward, live и ретюнинг контракта. Новый research-кандидат требует отдельного PlanOnly, а не ослабления 5m/220d acceptance contract.

PIT membership-drift остаётся shadow-track и не блокирует этот critical path.
