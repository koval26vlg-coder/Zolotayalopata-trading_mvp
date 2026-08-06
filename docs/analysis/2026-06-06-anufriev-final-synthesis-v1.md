# Итоговый synthesis: канал Ануфриева, стратегии и применимость к trading_mvp

Дата: 2026-06-06  
Статус: v1 / research-only synthesis. Это не инвестсовет и не рекомендация к live-торговле.

## 1. Что было изучено

Канал: https://www.youtube.com/@AnufrievNikita/

Покрытие:
- 461 видео из full channel catalog.
- 287 trading/crypto/investing-релевантных видео.
- 287 видео с full metadata: views, upload date, descriptions, captions metadata.
- 20 562 076 views в all-287 trading-relevant выборке.
- 77 unique transcript-backed claim cards after clean retry batches.
- 241 transcript failures из-за YouTube IP/rate-limit.

Ключевые артефакты:
- `docs/analysis/2026-06-06-anufriev-requirements-coverage-audit.md`
- `docs/analysis/2026-06-06-anufriev-channel-strategy-audit-v1.md`
- `docs/analysis/2026-06-06-anufriev-strategy-decision-matrix.md`
- `docs/analysis/2026-06-06-anufriev-strategy-playbook-v1.md`
- `docs/analysis/2026-06-06-anufriev-external-evidence-register.md`
- `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_20260606.csv`
- `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_summary_20260606.json`

## 2. Главный вывод

Канал полезен как источник торговых гипотез, но не как доказательство прибыльности.

Самые переносимые идеи:
- стакан и лента важнее свечных индикаторов для микроструктурного трейдинга;
- нужна жесткая фильтрация рынка и режимов;
- playbook и риск-процесс важнее красивого win-rate;
- spot-only long стратегия слишком узкая;
- derivatives/perps логически ближе к тем стратегиям, о которых говорит канал;
- funding/basis надо держать отдельным low-frequency модулем;
- AI полезен как research/tooling layer, но не как автономный трейдер.

Самые опасные идеи:
- гнаться за `90% win-rate`;
- верить историям разгона депозита без выборки, комиссий и survivorship bias;
- объяснять каждый вынос стопов намеренной манипуляцией;
- запускать live до replay + paper-forward доказательств;
- смешивать funding, HFT, AI и news в один мутный score.

## 3. Что показал сам канал

All-287 strategy map:

| Strategy family | Видео | Views | Практическое значение |
|---|---:|---:|---|
| General trading | 126 | 10 509 498 | Карта рынка/историй, но мало прямого кода |
| High win-rate / deposit growth | 60 | 4 259 014 | Главный слой для критического факт-чека |
| AI trading / bots | 50 | 3 252 182 | Tooling и automation, не proof of alpha |
| Risk / psychology / playbook | 36 | 2 087 393 | Обязательный операционный слой |
| Orderbook / tape / market maker | 17 | 944 241 | Ближайший кластер к `trading_mvp` |
| Funding / passive / P2P | 14 | 1 875 562 | Отдельный carry/risk модуль |
| Legal / regulatory crypto | 12 | 1 099 537 | Compliance/risk, не alpha |
| Futures / prop / derivatives | 12 | 1 103 406 | Обоснование перехода к perp replay |
| News / event / Polymarket | 6 | 179 069 | Возможный regime filter |

Вывод из структуры канала: фокус не только на стакане. Канал смешивает trading alpha, истории успеха, психологию, legal risk, AI, passive crypto и derivatives. Для проекта это нужно разделить на независимые модули.

## 4. Участники: что переносить

| Участник / группа | Что полезно | Что нельзя переносить напрямую |
|---|---|---|
| Михаил Латогузов | Брифинг, playbook, стакан, дисциплина | Не доказывает автоматический edge |
| Андрей Демченко | L2/tape review, неликвиды, листинги, фрейм-за-фреймом разбор | `90%` как общий KPI |
| Нарэк Григорян | Гипотезы liquidity sweep / stop cascade | Приписывание намерений маркетмейкеру |
| HAMAHA / Максим | Professional process, derivatives mindset | Требует больше transcript-level проверки |
| Игорь Андреев | Futures/derivatives branch | Не переносится в spot-only bot |
| Иван Шашков | Carry/yield/passive crypto | Не HFT, не частые сделки |
| Андрей Тугарин / Михаил Успенский / Калой Ахильгов | Legal/P2P/withdrawal risk | Не торговая стратегия |
| Роман Пищулов / OpenClaw | Productization, bots, automation | Не доказательство прибыльности trading bot |
| Сергей Алексеев / high-return videos | Claims to audit | Высокий risk of survivorship/marketing bias |

## 5. Внешняя проверка правдивости

Внешние источники подтверждают не прибыльность канала, а риск-контекст:

- SEC/FCA: HFT и микроструктура реальны, но это не доказывает, что ручной или retail bot стабильно обыгрывает HFT.
- CFTC: spoofing существует как market abuse, но intent нельзя доказывать по одному стакану.
- ESMA/FINRA/Investor.gov: intraday, margin, CFD/perpetual-like products несут высокий риск.
- Barber/Odean research: большинство day traders не демонстрируют устойчивую прибыльность; небольшая доля skill-based трейдеров может существовать.
- IOSCO: crypto venues несут market integrity, custody, conflict-of-interest и retail-risk проблемы.

Следствие: любые claims канала должны проходить через replay/backtest, а не приниматься как факт.

## 6. Сравнение с текущим trading_mvp

Текущие результаты проекта:

| Проверка | Результат | Вердикт |
|---|---|---|
| 6h spot maker `flow_continue` | 45 trades, 42.22% win-rate, net PnL -0.2065, PF 0.721 | Не годится для live |
| 6h spot maker `fade_exhaustion` | 77 trades, 45.45% win-rate, net PnL -0.4375, PF 0.648 | Больше сделок, хуже EV |
| Funding/basis short horizon | 41 markets, 0 trades | Не high-frequency модуль |
| High-winrate target | EV gates failed | Win-rate как цель отвергнут |

Текущая стратегия не успешна в live-смысле. Но проект успешен как research system, потому что он отсекает непрошедшие гипотезы до реального риска.

## 7. Что нужно делать дальше

Приоритетный roadmap:

1. `perp_replay` scaffold уже реализован; следующий шаг - добавить public perp data для MEXC/Gate и прогнать его на 6-24h dataset.
2. Добавить public perp data для MEXC/Gate сначала.
3. Включить long/short, maker/taker, fees, funding, slippage, mark/index.
4. Перенести `flow_continue` и `fade_exhaustion` в perp replay.
5. Добавить `liquidity_sweep_reversal`.
6. Добавить market-quality + fill-probability metrics.
7. Вести experiment ledger для каждой гипотезы.
8. Только после этого запускать 3-7 дней paper-forward.

Почему именно `perp_replay`:
- канал много говорит о фьючерсах, short-side, stop cascades и market-maker dynamics;
- spot-only replay режет тысячи short-сигналов;
- perp replay позволит проверить обе стороны рынка;
- это research-only шаг без API keys и live orders.

## 8. Экономическая модель по направлениям

| Направление | Потенциал | Главная цена | Главный риск | Решение |
|---|---|---|---|---|
| Perp microstructure | Средний | Data/infra/fees/funding | Toxic fills, liquidation, overfit | Build next, research-only |
| Liquidity sweep reversal | Средний | Labeling/replay complexity | False sweeps | Build after perp scaffold |
| Market-quality/fill model | Высокая инфраструктурная ценность | Analytics/data storage | Слишком строгий фильтр | Build as gate |
| Funding/basis carry | Средний | Capital/margin/time | Basis widening, exchange risk | Keep separate |
| News/event filter | Неизвестный | Data/label quality | Late/false news | Later as filter |
| AI tooling | Высокая productivity value | Evaluation discipline | Hallucinated signals | Use for research only |
| High-winrate stories | Низкий как стратегия | Bias/fake confidence | Losses after fees | Audit only |

## 9. Acceptance gates для любой будущей стратегии

Минимум для research candidate:
- 6-24h replay.
- минимум 50 сделок.
- net PnL > 0 после всех costs.
- profit factor >= 1.2.
- expectancy > 0.
- drawdown внутри лимита.
- нет зависимости от одной монеты без явной market-specific маркировки.

Минимум перед live-like paper:
- 3-7 дней paper-forward.
- измеренные data/API outages.
- kill switch.
- daily loss cap.
- venue risk card.
- no Binance testnet.

## 10. Что не делать

- Не запускать live сейчас.
- Не возвращаться к Binance testnet.
- Не оптимизировать только win-rate.
- Не смешивать funding с HFT-сигналом.
- Не позволять AI принимать trade decisions.
- Не называть текущий проект HFT.
- Не использовать рассказы о разгонах депозита как proof.
- Не доказывать intent маркетмейкера без данных.

## 11. Итоговая позиция

Самая жизнеспособная модель на текущий момент:

`perp long/short microstructure replay + liquidity sweep/reversal + market quality/fill probability + strict experiment ledger`

Это не гарантирует прибыль, но это лучший путь из изученных, потому что:
- он ближе всего к реальным проверяемым тезисам канала;
- устраняет ограничение spot-only;
- проверяет short-side;
- учитывает costs;
- не опирается на маркетинговый win-rate;
- масштабируется через data/replay, а не через ручную веру в сетап.

До доказательства через replay и paper-forward проект должен оставаться research-only.
