# MVP алготрейдинга: universe -> collector -> backtester -> risk-engine

Этот модуль дает минимальный, но рабочий контур:
- `universe`: отбор монет, которых нет на Binance Spot;
- `collector`: сбор микроструктурных снапшотов через REST;
- `backtest`: проверка стратегии на собранных данных;
- `paper`: симуляция сигналов с риск-ограничениями;
- `risk-engine`: pre-trade проверки, дневной лимит убытка, kill-switch.

Важно:
- Binance используется как источник списка активов для исключения из universe, а не как площадка исполнения.
- По умолчанию режим безопасный: без реальных ордеров.
- Это исследовательский контур, не инвестиционный совет.

## Структура

```text
trading_mvp/
  config.example.json
  requirements.txt
  run_mvp.ps1
  src/
    cli.py
    config.py
    collector.py
    trading.py
  tests/
    test_backtester.py
    test_risk.py
```

## Установка

```powershell
cd C:\Users\koval\Documents\ZolotyayLopata
.\.venv\Scripts\Activate.ps1
pip install -r trading_mvp\requirements.txt
```

## Конфиг

Скопируйте:

```powershell
Copy-Item trading_mvp\config.example.json trading_mvp\config.json
```

## Быстрый старт

1) Собрать universe монет вне Binance:

```powershell
.\trading_mvp\run_mvp.ps1 -Action universe
```

2) Сбор данных (60 секунд):

```powershell
.\.venv\Scripts\python.exe trading_mvp\src\cli.py --config trading_mvp\config.json collect --seconds 60
```

3) Бэктест последнего файла:

```powershell
.\.venv\Scripts\python.exe trading_mvp\src\cli.py --config trading_mvp\config.json backtest
```

4) Paper-run (без реальных ордеров):

```powershell
.\.venv\Scripts\python.exe trading_mvp\src\cli.py --config trading_mvp\config.json run --mode paper --cycles 120
```

5) Multi-exchange paper-бот по монетам вне Binance:

```powershell
.\trading_mvp\run_mvp.ps1 -Action multi-run `
  -Exchanges "mexc,gateio,kucoin,bingx" `
  -Cycles 20 `
  -MaxPairsPerExchange 5 `
  -MaxSymbols 200 `
  -PaperNotionalQuote 25
```

Длительный тест на 1 час:

```powershell
.\trading_mvp\run_mvp.ps1 -Action multi-run `
  -Exchanges "mexc,gateio,kucoin,bingx" `
  -DurationSec 3600 `
  -MaxPairsPerExchange 3 `
  -MaxSymbols 200 `
  -PaperNotionalQuote 25
```

Поддерживаемые public-data коннекторы: `mexc`, `gateio`, `kucoin`, `bingx`. В этом режиме бот только читает spot-стакан/ленту, считает сигнал и ведет paper-позиции; реальные заявки не отправляются.

6) WebSocket-сбор raw market data для будущего replay-backtest:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-collect `
  -Exchanges "mexc,gateio" `
  -DurationSec 60 `
  -MaxPairsPerExchange 3 `
  -MaxSymbols 200 `
  -UpdateInterval "100ms"
```

Этот режим только читает публичные WebSocket-данные и пишет raw events в `exports/trading-mvp/raw`. MEXC spot WebSocket сейчас использует protobuf, поэтому бинарные сообщения сохраняются как base64 для последующего декодирования. Gate события сохраняются как JSON.

7) Нормализовать raw WebSocket events в общий формат:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-normalize
```

Команда без параметров берет последний `ws_collect_*.json` manifest из `exports/trading-mvp/raw` и пишет результат в `exports/trading-mvp/normalized/ws_normalized_*.jsonl`. Можно указать конкретный raw-файл или manifest:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-normalize `
  -InputPath "exports\trading-mvp\raw\ws_collect_20260603_165754.json"
```

Нормализованный JSONL содержит единые события `bbo`, `depth`, `trade` для дальнейшего replay-backtest. MEXC protobuf декодируется для `aggre_book_ticker`, `limit_depth`, `aggre_deals`; Gate JSON декодируется для `spot.book_ticker`, `spot.order_book_update`, `spot.trades`.

8) Event-driven replay-backtest по normalized events:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-replay `
  -InputPath "exports\trading-mvp\normalized\ws_normalized_20260604_085056.jsonl" `
  -SignalType "flow_continue" `
  -NotionalQuote 25 `
  -ExecutionMode "taker" `
  -TakerFeeBps 10 `
  -SlippageBps 1 `
  -LatencyMs 250 `
  -FlowWindowSec 5
```

Команда без `-InputPath` берет последний normalized JSONL. Replay использует BBO как источник исполнения, стакан/qty для imbalance, trades для signed flow, а результат сохраняет в `exports/trading-mvp/backtests/ws_replay_*.json`. По умолчанию short-сигналы отключены, потому что базовая модель ориентирована на spot; для исследовательского long/short replay можно добавить `-AllowShort`.

Доступные `SignalType`:
- `flow_continue`: текущий continuation-сигнал, где imbalance и signed flow направлены в одну сторону.
- `fade_exhaustion`: контртрендовый absorption-сигнал: long при sell-flow + bid absorption, short при buy-flow + ask absorption.
- `liquidity_sweep_reversal`: нейтральный detector наблюдаемого sweep/reclaim: long после sell sweep ниже recent bid/low и возврата bid, short после buy sweep выше recent ask/high и rejection. Это не label "манипуляция маркетмейкера".
- `liquidity_sweep_reversal_v2`: event-slice версия sweep/reclaim. Она не использует старый imbalance gate, а применяет фильтры `SweepV2AllowedMarkets`, `SweepV2Side`, `SweepV2MinTradeNotionalQuote`, `SweepV2MinIntensityBps`, `SweepV2MaxPreSpreadBps`, `SweepV2MaxReclaimSec`, `SweepV2EventCooldownSec`, найденные через `event-slice-optimizer`.

Maker/post-only replay:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-replay `
  -InputPath "exports\trading-mvp\normalized\ws_normalized_30m_20260604.jsonl" `
  -ExecutionMode "maker" `
  -NotionalQuote 25 `
  -MakerFeeBps 0 `
  -TakerFeeBps 10 `
  -SlippageBps 0 `
  -LatencyMs 250 `
  -MakerQueueModel "fixed" `
  -MakerQueueAheadQty 0 `
  -MakerOrderTtlSec 5
```

Maker-fill модель консервативнее простого "поставили лимитку и считаем filled": пассивный buy заполняется только после встречного sell trade print по цене `<= limit`, пассивный sell — только после buy trade print по цене `>= limit`.

Доступны две модели очереди:
- `-MakerQueueModel "fixed"`: очередь перед нами равна `-MakerQueueAheadQty`.
- `-MakerQueueModel "top_qty_fraction"`: очередь перед нами равна `MakerQueueAheadQty + best_bid_or_ask_qty * MakerQueueAheadFraction`.

`fixed` с нулевой очередью — оптимистичный sanity-check. `top_qty_fraction` с `MakerQueueAheadFraction 1` предполагает, что весь видимый объем best bid/ask стоит перед нами.

Market-quality / regime filter:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-replay `
  -InputPath "exports\trading-mvp\normalized\ws_normalized_6h_20260604.jsonl" `
  -ExecutionMode "maker" `
  -NotionalQuote 25 `
  -MakerFeeBps 0 `
  -SlippageBps 0 `
  -LatencyMs 250 `
  -MakerQueueModel "top_qty_fraction" `
  -MakerQueueAheadFraction 1 `
  -MakerOrderTtlSec 5 `
  -QualityFilter `
  -QualityWindowSec 60 `
  -QualityMinTradeCount 20 `
  -QualityMinTradeNotional 1000 `
  -QualityMaxAvgSpreadBps 3 `
  -QualityMinQuoteUpdates 10 `
  -MinNetTakeProfitBps 1
```

Фильтр выключен по умолчанию. При включении сигнал допускается только если в rolling-window достаточно trade-flow плотности, quote updates, средний spread не выше лимита, и, при необходимости, top bid/ask qty выше порога. Это не улучшает сигнал само по себе, а отсекает рынки/периоды, где maker-fill слишком маловероятен или микроструктура слишком разреженная.

`-MinNetTakeProfitBps` добавляет cost gate: сигнал допускается только если целевой `take_profit_bps` покрывает round-trip fees и оставляет заданный net edge. Для taker-режима это критично: take-profit 3-6 bps при taker fee 10 bps обычно математически не окупает комиссии.

9) Grid-search параметров стратегии на event-driven replay:

```powershell
.\trading_mvp\run_mvp.ps1 -Action ws-grid-search `
  -InputPath "exports\trading-mvp\normalized\ws_normalized_20260604_085056.jsonl" `
  -NotionalQuote 25 `
  -ExecutionMode "taker" `
  -TakerFeeBps 10 `
  -SlippageBps 1 `
  -LatencyMs 250 `
  -FlowWindowSec 5 `
  -GridImbalance "0.1,0.25" `
  -GridFlow "50,250,1000" `
  -GridSignalType "flow_continue,fade_exhaustion,liquidity_sweep_reversal" `
  -GridSpread "1.5,3" `
  -GridTakeProfit "3,6" `
  -GridStopLoss "3,6" `
  -GridMaxHoldSec "5,25" `
  -MinTrades 3 `
  -MinWinRate 0.6 `
  -MinExpectancyQuote 0 `
  -MinNetPnlQuote 0 `
  -MinProfitFactor 1.2 `
  -MaxDrawdownQuote 5 `
  -MinNetTakeProfitBps 1 `
  -TopN 20
```

Grid-search перебирает комбинации, запускает replay для каждой и ранжирует результаты по net PnL, profit factor, expectancy, win rate и числу сделок. Eligibility-фильтры (`-MinTrades`, `-MinWinRate`, `-MinExpectancyQuote`, `-MinNetPnlQuote`, `-MinProfitFactor`, `-MaxDrawdownQuote`) нужны, чтобы не считать "лучшей" стратегию, которая почти не торговала или выигрывала только до учета риска/комиссий. Output включает `best_by_signal_type`, чтобы сравнивать signal families даже когда один тип не попал в общий top.

10) Perp public REST collect + replay / grid-search research layer:

```powershell
.\trading_mvp\run_mvp.ps1 -Action perp-collect `
  -InputPath "exports\trading-mvp\universe\no_binance_focus_YYYY-MM-DD.csv" `
  -OutputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -Exchanges "mexc,gateio" `
  -MaxSymbols 200 `
  -MaxPairsPerExchange 5 `
  -DurationSec 21600 `
  -PollIntervalSec 30 `
  -DepthLimit 20 `
  -TradesLimit 50
```

`perp-collect` собирает public REST data без API keys и live orders: BBO/depth/trades плюс `mark_price`, `index_price`, `funding_rate`, `next_funding_ts`, `funding_interval_sec`, `open_interest`, `volume_24h_quote`, если биржа отдает эти поля. V1 покрывает MEXC и Gate. Output сразу пишется в replay-compatible normalized JSONL, а рядом создается manifest `*.manifest.json` с cycles/errors/discovery.

Если задан `-DurationSec`, сбор останавливается по wall-clock времени; `-Cycles` остается как верхний лимит для safety/backward compatibility. Для 6h исследования используйте именно `-DurationSec 21600`, а не `-Cycles 720`.

Перед replay/grid полезно проверить качество датасета:

```powershell
.\trading_mvp\run_mvp.ps1 -Action perp-report `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -OutputPath "exports\trading-mvp\backtests\perp_report_YYYYMMDD.json"
```

`perp-report` считает rows, markets, cycles, event kinds, per-market trade/spread/funding stats, coverage `mark_price`/`index_price`/`funding_rate` и warnings. Его можно запускать даже на in-progress JSONL: частично записанная последняя строка будет помечена как `malformed_rows`, а не сломает отчет.

Для финальной обработки после завершенного сбора используйте `perp-postprocess`: команда требует final manifest, сначала запускает QA-report и только при чистом QA запускает strict perp grid-search.

```powershell
.\trading_mvp\run_mvp.ps1 -Action perp-postprocess `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -ManifestPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.manifest.json" `
  -ReportOutputPath "exports\trading-mvp\backtests\perp_report_YYYYMMDD.json" `
  -GridOutputPath "exports\trading-mvp\backtests\perp_grid_search_YYYYMMDD.json"
```

Если manifest еще не final, `perp-postprocess` возвращает `status=not_final` и не запускает grid. Для явных smoke/debug запусков есть `-AllowPartial`, но для исследовательских выводов его использовать нельзя.

```powershell
.\trading_mvp\run_mvp.ps1 -Action perp-replay `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -SignalType "flow_continue" `
  -ExecutionMode "maker" `
  -NotionalQuote 25 `
  -MakerFeeBps 0 `
  -TakerFeeBps 10 `
  -SlippageBps 0 `
  -LatencyMs 250
```

`perp-replay` использует те же `flow_continue` / `fade_exhaustion` / `liquidity_sweep_reversal`, но включает short-side по умолчанию и учитывает `funding_pnl_quote`, если normalized events содержат `mark_price`, `index_price`, `funding_rate`, `funding_interval_sec`. Без явного `-InputPath` perp-команды предпочитают последний `perp_normalized_*.jsonl`; fallback на spot-normalized файл остается только для wiring smoke и не является доказательством perp edge.

Grid-search:

```powershell
.\trading_mvp\run_mvp.ps1 -Action perp-grid-search `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -ExecutionMode "maker" `
  -GridSignalType "flow_continue,fade_exhaustion,liquidity_sweep_reversal" `
  -GridImbalance "0.05,0.1" `
  -GridFlow "250,1000,2500" `
  -GridSpread "3,6" `
  -GridTakeProfit "6,10" `
  -GridStopLoss "3,6" `
  -GridMaxHoldSec "15,25" `
  -MinTrades 20 `
  -MinWinRate 0.6 `
  -MinExpectancyQuote 0 `
  -MinNetPnlQuote 0 `
  -MinProfitFactor 1.2
```

Результаты сохраняются как `exports/trading-mvp/backtests/perp_replay_*.json` и `exports/trading-mvp/backtests/perp_grid_search_*.json`. Модуль research-only: API keys, live orders, leverage/margin execution не используются.

11) Event-quality report for sweep/reclaim research:

```powershell
.\trading_mvp\run_mvp.ps1 -Action event-quality-report `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -OutputPath "exports\trading-mvp\backtests\event_quality_YYYYMMDD.json" `
  -EventLookbackSec 120 `
  -EventHorizonSec 300 `
  -EventMinSweepNotionalQuote 1000 `
  -EventReclaimBps 0 `
  -EventTargetBps 6 `
  -EventStopBps 3 `
  -EventMaxPreSpreadBps 6 `
  -EventCooldownSec 10 `
  -EventMaxEvents 10000
```

`event-quality-report` не открывает сделки. Он маркирует наблюдаемые sweep/reclaim события, считает `time_to_reclaim_sec`, favorable/adverse excursion, `target_before_stop`, `stop_before_target`, `no_reclaim` и market-level качество. Этот слой нужен перед добавлением новой версии `liquidity_sweep_reversal`: если событие само по себе имеет высокий false-sweep rate или слабую target-before-stop статистику, расширять replay-сигнал нельзя.

12) Event-slice optimizer before replay v2:

```powershell
.\trading_mvp\run_mvp.ps1 -Action event-slice-optimizer `
  -InputPath "exports\trading-mvp\backtests\event_quality_YYYYMMDD.json" `
  -OutputPath "exports\trading-mvp\backtests\event_slice_optimizer_YYYYMMDD.json" `
  -SliceMinEvents 20 `
  -SliceMinReclaimed 10 `
  -SliceMinTargetBeforeStopRate 0.60 `
  -SliceMinTargetRateAll 0.20 `
  -SliceMaxAvgAdverseBps 15 `
  -SliceMinSweepIntensityBps "0,2,5,10" `
  -SliceMaxTimeToReclaimSec "0,30,60,120,300" `
  -SliceMaxPreSpreadBps "0,1,3,6" `
  -SliceMaxAbsBasisBps "0,5,10,25,100" `
  -SliceMinTradeNotionalQuote "0,2500,5000,10000" `
  -TopN 50
```

`event-slice-optimizer` перебирает срезы уже размеченных событий: market, expected side, sweep intensity, time-to-reclaim, pre-spread, basis и notional. Output ранжирует срезы по eligibility, `target_before_stop_rate`, `target_rate_all`, sample-size и adverse/favorable profile. Если eligible-срезов нет, следующий шаг — не live/paper trading, а уточнение event definition или отказ от этой signal family.

In-sample replay v2 example:

```powershell
.\trading_mvp\run_mvp.ps1 -Action perp-grid-search `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_YYYYMMDD.jsonl" `
  -GridSignalType "liquidity_sweep_reversal_v2" `
  -GridFlow "2500" `
  -GridSpread "3,6" `
  -GridTakeProfit "6" `
  -GridStopLoss "3" `
  -GridMaxHoldSec "300" `
  -SweepV2AllowedMarkets "gateio:HYPE_USDT" `
  -SweepV2Side "SHORT" `
  -SweepV2MinTradeNotionalQuote 2500 `
  -SweepV2MaxPreSpreadBps 1 `
  -SweepV2EventCooldownSec 10
```

Этот replay нужен только для проверки среза. Если после учета исполнения, latency, maker queue и fees он не проходит eligibility, срез нельзя переносить в paper/live.

13) Funding / basis carry research engine:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-scan `
  -Exchanges "mexc,gateio" `
  -MaxPairsPerExchange 5 `
  -MaxSymbols 200 `
  -NotionalQuote 25 `
  -FundingMinRate 0 `
  -FundingMaxSpotSpreadBps 30 `
  -FundingMaxPerpSpreadBps 30 `
  -FundingSpotFeeBps 10 `
  -FundingPerpFeeBps 7.5 `
  -SlippageBps 1 `
  -FundingTargetHoldIntervals 1 `
  -FundingMinExpectedNetCarryBps 0
```

`funding-scan` сопоставляет spot-пары из universe монет вне Binance с perpetual futures на той же бирже, считает funding, basis, spread/liquidity/risk scores, round-trip cost, expected net carry и break-even funding horizon, затем сохраняет результат в `exports/trading-mvp/funding/funding_scan_*.json`.

`FundingMinExpectedNetCarryBps` является quality gate: если funding за целевой горизонт не покрывает round-trip spot/perp fees и slippage, строка помечается `expected_edge_below_min`. Это защищает от "красивых" high-winrate carry-сделок, которые математически не окупают исполнение.

Периодический сбор snapshots:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-collect `
  -Exchanges "mexc,gateio" `
  -Cycles 12 `
  -PollIntervalSec 300 `
  -MaxPairsPerExchange 5
```

`funding-collect` пишет не только JSONL snapshots, но и соседний `*.manifest.json` с per-cycle coverage, top rows и error breakdown. Используйте manifest для диагностики зависаний, API-ошибок и потери coverage.

Ранжирование последнего funding-файла:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-rank -TopN 20
```

Backtest long spot + short perp carry по собранным snapshots:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-backtest `
  -InputPath "exports\trading-mvp\funding\funding_collect_YYYYMMDD_HHMMSS.jsonl" `
  -NotionalQuote 100 `
  -FundingSpotFeeBps 10 `
  -FundingPerpFeeBps 7.5 `
  -SlippageBps 1
```

Funding-модуль является research-only: он не использует API keys, не открывает реальные позиции, не включает leverage/margin execution и не является торговой рекомендацией. V1 проверяет гипотезу `long spot + short perp`, где положительный funding потенциально платит short-perp стороне, а spot-leg снижает directional exposure.

14) Experiment ledger and setup registry:

```powershell
.\trading_mvp\run_mvp.ps1 -Action setup-registry
.\trading_mvp\run_mvp.ps1 -Action experiment-record `
  -SourceVideoId Z5UjQOF7QI0 `
  -SourceUrl "https://www.youtube.com/watch?v=Z5UjQOF7QI0" `
  -Participant "Михаил Латогузов" `
  -ClaimFamily "orderbook_tape_continuation" `
  -Hypothesis "Maker replay on 6h dataset did not clear EV gates." `
  -SetupId flow_continue `
  -Dataset "ws_normalized_6h_20260604.jsonl" `
  -ResultPath "exports\trading-mvp\backtests\ws_grid_search_signal_type_maker_quality_6h_20260608.json" `
  -Verdict rejected `
  -VerdictReason "negative net pnl and PF below threshold"
.\trading_mvp\run_mvp.ps1 -Action experiment-list -SetupId flow_continue
```

This layer is research-only and exists to keep every channel-derived hypothesis traceable: source video, participant, claim family, setup id, dataset, result artifact and verdict.

## Результаты

Артефакты пишутся в:
- `exports/trading-mvp/raw/*.jsonl` — рыночные снапшоты;
- `exports/trading-mvp/raw/ws_*.jsonl` — raw WebSocket events;
- `exports/trading-mvp/raw/ws_collect_*.json` — manifest WebSocket-сбора;
- `exports/trading-mvp/normalized/ws_normalized_*.jsonl` — нормализованные WebSocket events;
- `exports/trading-mvp/backtests/ws_replay_*.json` — event-driven replay с fee/slippage/latency;
- `exports/trading-mvp/backtests/ws_grid_search_*.json` — grid-search по параметрам replay;
- `exports/trading-mvp/backtests/perp_replay_*.json` — perp replay с short-side и funding accounting;
- `exports/trading-mvp/backtests/perp_grid_search_*.json` — perp grid-search по signal families;
- `exports/trading-mvp/backtests/event_quality_*.json` — разметка sweep/reclaim событий и качество event family;
- `exports/trading-mvp/backtests/event_slice_optimizer_*.json` — ranked event slices перед replay v2;
- `exports/trading-mvp/funding/funding_scan_*.json` — funding/basis scan;
- `exports/trading-mvp/funding/funding_collect_*.jsonl` — периодические funding/basis snapshots;
- `exports/trading-mvp/funding/funding_rank_*.json` — ranked carry opportunities;
- `exports/trading-mvp/backtests/funding_backtest_*.json` — funding carry backtest;
- `exports/trading-mvp/experiments/setup_registry.json` — research-only setup registry;
- `exports/trading-mvp/experiments/experiment_ledger.jsonl` — append-only hypothesis/result/verdict ledger;
- `exports/trading-mvp/backtests/*.json` — метрики и сделки;
- `exports/trading-mvp/run/*.json` — результаты paper-запуска.
- `exports/trading-mvp/universe/*.csv` — universe-фильтры, включая монеты вне Binance.

## Universe вне Binance

Собрать актуальный список монет, которых нет на Binance Spot:

```powershell
.\trading_mvp\scripts\build_no_binance_universe.ps1
```

Файл `no_binance_full_*.csv` содержит все монеты из источника, отсутствующие в активных Binance-активах по символу. Файл `no_binance_focus_*.csv` дополнительно убирает явные stablecoin/wrapped/staked/bridged-подобные активы.

Посчитать, на каких spot-CEX биржах больше всего монет из этого universe:

```powershell
C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe trading_mvp\scripts\rank_exchanges_by_universe.py `
  --focus-csv exports\trading-mvp\universe\no_binance_focus_2026-06-02.csv `
  --full-csv exports\trading-mvp\universe\no_binance_full_2026-06-02.csv `
  --out-dir exports\trading-mvp\universe `
  --date-stamp 2026-06-02
```

## Риск-контроль (вшит в движок)

- лимит нотионала на сделку;
- лимит позиции;
- лимит сделок за день;
- дневной лимит убытка (активирует `kill_switch`);
- запрет новых входов при активном kill-switch.
