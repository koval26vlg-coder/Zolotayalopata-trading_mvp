# Аналитика часового paper-test trading_mvp
Дата: 2026-06-02

## Рамка
Тест был запущен в paper-режиме: реальные заявки не отправлялись. Результаты ниже не являются инвестиционной рекомендацией и не доказывают прибыльность стратегии. Это проверка инженерной работоспособности текущего MVP и грубая оценка экономики.

## Запуск
- Metadata: `docs/agent-log/2026-06-02-trading-mvp-hour-test-20260602_192458.json`
- Stdout: `exports/trading-mvp/run/hour_test_20260602_192458.stdout.log`
- Stderr: `exports/trading-mvp/run/hour_test_20260602_192458.stderr.log`
- Итог: `exports/trading-mvp/run/multi_run_20260602_172653.json`
- Режим: paper
- Биржи: `mexc`, `gateio`, `kucoin`, `bingx`
- Universe: `no_binance_focus_2026-06-02.csv`
- Пары на биржу: 3
- Paper notional: 25 USDT
- Запрошенная длительность: 3600 сек
- Фактическая длительность: 3701.48 сек

## Discovery
| Биржа | Найдено spot USDT-пар | Выбрано пар | Пары |
|---|---:|---:|---|
| MEXC | 1999 | 3 | HYPEUSDT, WBTUSDT, XMRUSDT |
| Gate | 2055 | 3 | HYPE_USDT, LEO_USDT, CC_USDT |
| KuCoin | 899 | 3 | HYPE-USDT, XMR-USDT, CC-USDT |
| BingX | 783 | 3 | HYPE-USDT, OKB-USDT, RAIN-USDT |

## Метрики
| Метрика | Значение |
|---|---:|
| Completed cycles | 114 |
| Markets with state | 11 |
| Successful snapshots | 1099 |
| Errors | 269 |
| Snapshot success rate | 80.3% |
| Total paper trades | 27 |
| Wins / losses | 14 / 13 |
| Win rate | 51.85% |
| Gross paper PnL | -0.0360 USDT |
| Avg gross PnL | -0.00134 USDT/trade |
| Avg gross PnL bps | -0.53 bps |
| Avg hold | 29.9 sec |

## PnL по рынкам
| Рынок | Сделок | Win rate | Gross PnL |
|---|---:|---:|---:|
| Gate HYPE_USDT | 21 | 42.9% | -0.10 USDT |
| KuCoin HYPE-USDT | 2 | 100% | +0.02 USDT |
| KuCoin XMR-USDT | 4 | 75% | +0.04 USDT |
| Остальные рынки | 0 | 0% | 0 |

Сигнал почти полностью сконцентрировался на Gate HYPE_USDT. Это плохой признак для устойчивости: стратегия не показала широкого повторяемого edge по набору рынков.

## Ошибки
Всего ошибок: 269.

По биржам:
- BingX: 143
- Gate: 42
- KuCoin: 42
- MEXC: 42

Типы:
- BingX RAIN-USDT часто возвращал payload без ожидаемого `data` (99 раз).
- Был DNS/connection burst почти по всем API, примерно по 13-15 ошибок на рынок.
- Stderr пустой; процесс завершился штатно, ошибки были обработаны внутри bot loop.

Вывод: текущая REST-архитектура слишком чувствительна к сетевым сбоям и слишком медленная для микроструктурного скальпинга.

## Экономика сделки
В текущем paper-движке комиссии и проскальзывание не включены в PnL. Для грубой оценки:
- entry notional: 675 USDT
- round-trip notional: 1350.16 USDT
- gross PnL: -0.0360 USDT
- estimated taker fee при 0.1% на вход и 0.1% на выход: 1.3502 USDT
- estimated net PnL: -1.3862 USDT

Экономический вывод: при taker-исполнении стратегия в текущем виде не проходит комиссионный барьер. Текущий take-profit/stop-loss около 6 bps слишком мал для бирж, где round-trip taker cost около 20 bps до учета проскальзывания.

MEXC потенциально интереснее из-за низких/нулевых spot-fee режимов, но в этом тесте сделок на MEXC не было, поэтому преимущество комиссии не подтверждено результатом.

## Себестоимость
Минимальный research-стенд:
- VPS: 5-20 USD/мес
- Логи/хранилище: 0-10 USD/мес
- API public data: 0 USD/мес
- Итого: 5-30 USD/мес

Рабочий research/prod MVP:
- VPS ближе к API-регионам + мониторинг: 30-150 USD/мес
- Хранилище сырых WebSocket-событий: 10-100 USD/мес
- Alerts/observability: 10-50 USD/мес
- Итого: 50-300 USD/мес

Серьезная low-latency версия:
- несколько VPS/регионов, WebSocket fanout, приватные API, мониторинг, аварийные лимиты: 300-1500+ USD/мес
- colocated/HFT-уровень для крипто CEX: отдельный бюджет, часто экономически не оправдан для малых счетов

Разработка до честного MVP:
- 40-80 часов: WebSocket collector + event store + fee/slippage backtester
- 80-160 часов: private execution, idempotency, order state machine, risk controls, monitoring
- 200+ часов: production-grade multi-exchange bot

## Рентабельность и окупаемость
На текущих данных окупаемость отрицательная:
- paper gross: почти ноль, но уже отрицательный;
- fee-adjusted result: примерно -1.386 USDT за час на 27 сделках;
- при таких параметрах рост объема масштабирует убыток, а не прибыль.

Для безубыточности при taker-исполнении нужно, чтобы средний gross edge был выше комиссии и проскальзывания:
- при 0.1% taker per side: нужно больше 20 bps round-trip до slippage;
- текущий gross avg: -0.53 bps;
- разрыв: примерно 20+ bps.

Следовательно, стратегия в текущем виде не масштабируется live. Потенциальная рентабельность может появиться только после изменения исполнения и отбора сетапов.

## Жизнеспособность стратегии
Текущий v1 как торговая стратегия: не доказана и пока не жизнеспособна для live.

Текущий v1 как исследовательский инструмент: жизнеспособен. Он уже умеет:
- находить пары вне Binance;
- подключаться к нескольким spot-биржам;
- собирать стакан/ленту;
- считать микроструктурные признаки;
- вести paper-позиции и риск-лимиты;
- сохранять итоговые метрики.

Главная проблема не в идее стакана, а в реализации и экономике исполнения:
- REST polling не подходит для микроструктурного скальпинга;
- taker-исполнение с малым TP математически проигрывает комиссиям;
- нет учета очереди, fee tier, slippage, fill probability;
- нет фильтра качества рынка перед торговлей;
- нет статистической проверки edge на большой выборке.

## Что добавить
1. WebSocket L2 + trades для каждой биржи.
2. Сохранение сырых order-book/trade events в parquet/jsonl.
3. Replay-backtester с комиссиями, spread/slippage, latency и partial fills.
4. Отдельный fee model по бирже/символу/VIP-level.
5. Market quality filter: минимальный объем, spread, depth, volatility, uptime API.
6. Сигналы второго слоя: spoof-like replenishment, iceberg absorption, sweep detection, stop-cascade detector.
7. Post-only/maker-first execution simulator.
8. Async IO вместо последовательного REST-цикла.
9. Per-symbol параметры стратегии вместо одного threshold для всех.
10. Kill-switch по API errors, drawdown, abnormal spread, stale data.

## Что изменить
1. Увеличить TP/SL или перейти на maker/post-only, иначе комиссионный барьер не пройти.
2. Исключить рынки без стабильной ленты trades.
3. Не выбирать пары только по market-cap rank; ранжировать по spread/depth/volatility/API reliability.
4. Разделить стратегии по типам рынков: high-liquidity, illiquid, listing, exchange-token, privacy coin.
5. Убрать термин HFT из описания v1; корректнее: microstructure paper bot / L2 scalping research.

## Что убрать
1. REST polling как основной режим для скальпинга.
2. Taker-only входы с TP около 6 bps на биржах с 0.1% fee.
3. BingX RAIN-USDT из universe до исправления/проверки depth payload.
4. Любые обещания win rate или доходности.

## Следующий этап
Рекомендуемый следующий этап: не live-trading, а `data-first` апгрейд.

Минимальный план:
1. WebSocket collector для MEXC и Gate как двух главных бирж по покрытию.
2. 24-72 часа сбора сырых данных по 20-50 парам.
3. Replay-backtest с комиссиями и slippage.
4. Отбор 3-5 сетапов с положительным net expectancy.
5. Только после этого private API paper/live-small executor.

## Вердикт
Проект перспективен как исследовательская платформа для поиска микроструктурных аномалий на альткоинах вне Binance. Как торговая система в текущем виде он не готов к live: latency, REST polling, комиссии и error-rate убивают ожидаемую доходность. Стратегию стоит развивать только через WebSocket data pipeline, maker-first исполнение и строгую net-PnL валидацию.
