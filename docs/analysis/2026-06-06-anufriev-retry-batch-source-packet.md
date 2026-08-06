# Anufriev Transcript Retry Batch Source Packet

Дата: 2026-06-06

Статус: transcript-backed continuation packet по top-priority metadata-only видео. Это редакционный факт-чек и research input, не торговая рекомендация.

## 1. Batch Result

| Metric | Value |
|---|---:|
| Clean retry processed | 31 |
| Unique transcript-backed ids union | 77 |
| Remaining metadata-only in all-287 scorecard | 210 |
| Updated retry rows in scorecard | 31 |

Source files:

- `exports/youtube-anufriev/anufriev_transcript_retry_claim_cards_clean_20260606.jsonl`
- `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json`
- `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv`
- `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_summary_20260606.json`

## 2. Clean Matched Themes

| Theme | Videos | Windows |
|---|---:|---:|
| `crypto_regulation_legal` | 23 | 86 |
| `risk_psychology_process` | 16 | 28 |
| `high_winrate_claims` | 15 | 40 |
| `funding_basis_arbitrage` | 10 | 26 |
| `news_event_trading` | 10 | 15 |
| `prop_moex_traditional` | 10 | 23 |
| `hft_orderbook_scalping` | 7 | 11 |
| `ai_trading` | 6 | 18 |
| `market_maker_manipulation` | 4 | 11 |

Important correction: the retry tool was updated so `бот` only matches a standalone bot word. This removed false `ai_trading` hits caused by substrings in words like `работаем`.

## 3. Video-Level Source Cards

| Queue rank | Video | Metadata clusters | Clean transcript themes | Evidence windows | Editorial reading |
|---:|---|---|---|---|---|
| 1 | `V-bu00UygbQ` - Как заработать, когда рынок рушится? / Откровение маркетмейкера DWF Labs | `orderbook_scalping,high_winrate_deposit_growth,ai_trading` | `hft_orderbook_scalping`, `market_maker_manipulation` | 0.04-7.6s, 3.6-11.96s, 28.84-36.12s | Market-maker/orderbook framing is confirmed; useful as hypothesis input, not proof of market-maker intent. |
| 2 | `eUZcEUH_3Ak` - Арбитраж криптовалюты P2P в 2022. Стоит ли начинать и сколько может заработать новичок? | `high_winrate_deposit_growth,risk_psychology_playbook,ai_trading,funding_passive_crypto` | `crypto_regulation_legal`, `funding_basis_arbitrage`, `market_maker_manipulation` | 0.16-10.559s, 2.399-11.88s, 14.12-23.68s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 3 | `uHvHeSZG2vk` - Как начать в трейдинге криптовалют со $100 / Проп-трейдинг для новичков | `high_winrate_deposit_growth,risk_psychology_playbook,futures_prop_moex,general_trading` | `crypto_regulation_legal`, `high_winrate_claims`, `news_event_trading`, `risk_psychology_process` | 5.04-13.759s, 8.36-17.52s, 19.279-25.519s | Prop/derivatives/risk framing is confirmed; useful for perp_replay and risk gates. |
| 4 | `mrPJmyUjKbM` - Трейдинг криптовалют / Как в 21 год ЗАРАБОТАТЬ НА ТРЕЙДИНГЕ и что такое проп-трейдинговые компании | `high_winrate_deposit_growth,ai_trading,futures_prop_moex,general_trading` | `prop_moex_traditional`, `risk_psychology_process` | 0.0-8.28s, 31.72-39.28s, 34.879-42.44s | Prop/derivatives/risk framing is confirmed; useful for perp_replay and risk gates. |
| 5 | `6A9-0rrOUCw` - Трейдинг криптовалют / Что такое опционы, как они устроены и как на них заработать? | `high_winrate_deposit_growth,ai_trading,futures_prop_moex,general_trading` | `crypto_regulation_legal`, `funding_basis_arbitrage`, `high_winrate_claims`, `risk_psychology_process` | 1.319-9.88s, 36.559-46.0s, 48.079-54.44s | Prop/derivatives/risk framing is confirmed; useful for perp_replay and risk gates. |
| 6 | `DLjlFGdx32M` - Арбитраж криптовалюты / Как Саша Вайс на Ролс Ройс заработал - честный Р2Р заработок или обучение? | `high_winrate_deposit_growth,ai_trading,funding_passive_crypto` | `crypto_regulation_legal`, `funding_basis_arbitrage`, `prop_moex_traditional` | 2.76-11.46s, 114.899-122.189s, 122.189-129.63s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 7 | `54g-UwVL7Sc` - Арбитраж криптовалюты p2p - РАЗБОР СВЯЗКИ / Почему ТЫ НЕ ЗАРАБОТАЕШЬ | `high_winrate_deposit_growth,ai_trading,funding_passive_crypto` | `crypto_regulation_legal`, `news_event_trading`, `risk_psychology_process` | 25.529-33.0s, 84.299-91.59s, 100.979-108.21s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 8 | `JTM4z4bX8_I` - Как заработать на криптовалюте? Арбитраж криптовалюты это далеко не все... | `high_winrate_deposit_growth,ai_trading,funding_passive_crypto` | `crypto_regulation_legal`, `high_winrate_claims`, `market_maker_manipulation`, `news_event_trading` | 9.69-18.0s, 14.25-23.4s, 98.009-109.049s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 9 | `tBh859wTAWg` - Арбитраж криптовалюты / Я вернул все что заработал с онлайн-курса / Вся правда про обучение p2p | `high_winrate_deposit_growth,ai_trading,funding_passive_crypto` | `crypto_regulation_legal`, `funding_basis_arbitrage`, `news_event_trading` | 2.159-10.8s, 40.92-48.899s, 62.16-70.56s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 10 | `1kvXfO3uHdI` - Как новичку в трейдинге быстро увеличить депозит? Что работает в 2026 | `high_winrate_deposit_growth,risk_psychology_playbook,ai_trading,general_trading` | `high_winrate_claims`, `risk_psychology_process` | 0.12-6.12s, 2.0-8.519s, 7.04-13.92s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 11 | `RvHaM3SQHNE` - Психология трейдинга: Как заработать МИЛЛИОНЫ и не потерять ВСЕ | `high_winrate_deposit_growth,risk_psychology_playbook,ai_trading,general_trading` | `funding_basis_arbitrage`, `hft_orderbook_scalping`, `high_winrate_claims`, `news_event_trading`, `prop_moex_traditional`, `risk_psychology_process` | 0.08-8.559s, 4.52-11.28s, 9.8-17.96s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 12 | `PL0LG4DYNaI` - Самый ПРОСТОЙ СПОСОБ заработка на крипте БЕЗ РИСКА | `high_winrate_deposit_growth,risk_psychology_playbook,ai_trading` | `funding_basis_arbitrage`, `high_winrate_claims`, `market_maker_manipulation`, `news_event_trading`, `prop_moex_traditional`, `risk_psychology_process` | 0.08-5.24s, 8.24-15.28s, 16.199-24.64s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 13 | `XAusAqySURg` - Стефан - КРИПТО МИЛЛИОНЕР про успех в 17 лет, 2 млн подписчиков, арбитраж, крипту и переезд в Дубай. | `high_winrate_deposit_growth,funding_passive_crypto` | `crypto_regulation_legal` | 21.359-32.759s, 99.06-109.88s, 101.579-112.86s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 14 | `-6tKe1FIG4I` - Как делать 1000% годовых на трейдинге? Путь от новичка до профессионала | `high_winrate_deposit_growth,risk_psychology_playbook,general_trading` | `crypto_regulation_legal`, `prop_moex_traditional`, `risk_psychology_process` | 21.72-29.88s, 51.079-57.76s, 53.12-58.68s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 15 | `5Af-C0_ry4Y` - Трейдинг криптовалют / Заработал $68 000 за месяц и показал свою стратегию / Григорий INV | `high_winrate_deposit_growth,ai_trading,general_trading` | `ai_trading`, `crypto_regulation_legal`, `high_winrate_claims`, `news_event_trading`, `prop_moex_traditional`, `risk_psychology_process` | 34.239-41.44s, 62.879-71.08s, 114.719-123.0s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 16 | `WAvk5xQY-eI` - Как выйти из ямы МИНУСОВ в ТРЕЙДИНГЕ? Путь от 1600р до миллионов! | `high_winrate_deposit_growth,risk_psychology_playbook,general_trading` | `crypto_regulation_legal`, `hft_orderbook_scalping`, `news_event_trading` | 33.68-42.84s, 51.879-58.399s, 55.199-63.28s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 17 | `4NIwjDdaljQ` - Как ИИ помогает находить сделки на 1000%? Новая эра трейдинга | `high_winrate_deposit_growth,ai_trading,general_trading` | `ai_trading`, `crypto_regulation_legal` | 2.159-10.599s, 35.32-43.719s, 43.719-50.96s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 18 | `MdGoQyFa7RQ` - Как заработать на трейдинге с депозитом 100 долларов? / Трейдинг криптовалют | `high_winrate_deposit_growth,ai_trading,general_trading` | `crypto_regulation_legal`, `high_winrate_claims`, `risk_psychology_process` | 0.08-9.4s, 48.6-57.44s, 119.079-126.399s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 19 | `FnEUehVp1ns` - Биржи РАЗДАЮТ ДЕНЬГИ? Как заработать на неэффективностях бирж? / Трейдинг криптовалют | `high_winrate_deposit_growth,ai_trading,general_trading` | `crypto_regulation_legal`, `funding_basis_arbitrage`, `hft_orderbook_scalping`, `news_event_trading`, `prop_moex_traditional` | 28.72-37.8s, 36.0-42.96s, 42.96-50.44s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 20 | `4YoY2VIHzAU` - Трейдинг криптовалют / как заработать на крипте | `high_winrate_deposit_growth,ai_trading,general_trading` | `ai_trading`, `crypto_regulation_legal`, `high_winrate_claims` | 5.72-12.16s, 12.16-19.359s, 60.64-68.52s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 21 | `nivJxncUoJ8` - Трейдинг криптовалют / почему только 1% заработают на крипте | `high_winrate_deposit_growth,ai_trading,general_trading` | `crypto_regulation_legal`, `funding_basis_arbitrage`, `hft_orderbook_scalping`, `high_winrate_claims`, `risk_psychology_process` | 47.399-54.359s, 52.719-61.16s, 74.52-81.24s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 22 | `ZHRTRB0ljM8` - Крипта / Почему ты все еще не заработал и есть ли тут деньги? / Влад Утушкин | `high_winrate_deposit_growth,ai_trading` | `ai_trading`, `crypto_regulation_legal`, `funding_basis_arbitrage` | 3.48-11.16s, 16.8-23.279s, 31.32-38.84s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 23 | `n1LdpJlyWgE` - Как заработать на недвижимости в Дубае? Доходность, риски, инвестиции - ответ эксперта | `high_winrate_deposit_growth,risk_psychology_playbook,ai_trading` | `crypto_regulation_legal`, `prop_moex_traditional`, `risk_psychology_process` | 5.52-14.04s, 136.76-144.44s, 201.08-210.799s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 24 | `_J2RK09WHtc` - Пассивный доход и "подписка на дивиденды". Запускаю инвестиционный клуб "Хедлайнеры". | `high_winrate_deposit_growth,funding_passive_crypto` | `funding_basis_arbitrage`, `high_winrate_claims` | 77.7-86.22s, 92.22-103.439s, 100.28-108.78s | P2P/arbitrage/funding-adjacent topic is confirmed, but this is not a direct CEX HFT edge. |
| 25 | `Z-LlG2o1Hd0` - Как РАЗОГНАТЬ ДЕПОЗИТ новичку в трейдинге - ЛУЧШИЙ СПОСОБ | `high_winrate_deposit_growth,risk_psychology_playbook,general_trading` | `crypto_regulation_legal`, `hft_orderbook_scalping`, `prop_moex_traditional` | 36.16-44.36s, 44.36-52.239s, 65.32-75.64s | Risk/process and deposit-growth framing is confirmed; use as operating gates, not alpha. |
| 26 | `kVSsydknuC0` - ТРЕЙДИНГ с нуля - МИФ или ЧЕМОДАН БАБЛА. Как заработать на криптовалюте в 2023? / Крипто Котлета | `high_winrate_deposit_growth,ai_trading,general_trading` | `crypto_regulation_legal`, `high_winrate_claims`, `risk_psychology_process` | 0.0-5.88s, 1.92-9.36s, 5.88-13.2s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 27 | `UB1iPD67fTE` - Как заработать на рынке акций? / Трейдинг | `high_winrate_deposit_growth,ai_trading,general_trading` | `hft_orderbook_scalping`, `high_winrate_claims`, `prop_moex_traditional` | 23.519-32.399s, 102.0-110.24s, 129.92-138.48s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 28 | `V0FDL2NoSM0` - Как заработать на крипте? Дима TheVsё | `high_winrate_deposit_growth,ai_trading` | `crypto_regulation_legal`, `high_winrate_claims`, `risk_psychology_process` | 0.0-5.839s, 1.64-9.559s, 3.76-12.2s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 29 | `K6uV9eeEU9M` - Крипта / Cryptus - Как заработать, когда крипта пробивает дно | `high_winrate_deposit_growth,ai_trading` | `ai_trading`, `crypto_regulation_legal`, `news_event_trading`, `risk_psychology_process` | 1.24-9.32s, 7.08-13.96s, 39.399-45.559s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 30 | `a55Kzs9L5AI` - Airdrop криптовалют. Как Славик пол миллиона крипто-долларов заработал? | `high_winrate_deposit_growth,ai_trading` | `crypto_regulation_legal` | 0.0-8.28s, 42.6-69.06s, 69.06-78.119s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |
| 31 | `ou2b3e0Q3t8` - Как заставить ИИ прибыльно трейдить вместо тебя - разбор с AI-инженером | `high_winrate_deposit_growth,ai_trading` | `ai_trading`, `high_winrate_claims`, `risk_psychology_process` | 25.8-32.92s, 45.399-53.32s, 63.519-70.4s | Transcript confirms topic presence; profitability remains unproven without independent PnL/EV evidence. |

## 4. Implications For trading_mvp

| Finding | Implication |
|---|---|
| High-winrate/deposit-growth is now majority transcript-backed in the priority set | This improves fact-checking, but still does not justify win-rate-only optimization |
| P2P/arbitrage/funding-adjacent videos are transcript-backed but mostly not CEX microstructure systems | Keep funding/basis as separate carry research, not as a HFT/orderbook signal |
| Prop/derivatives videos are transcript-backed | Strengthens the case for `perp_replay` over spot-only maker bot |
| Market-maker/orderbook top video is transcript-backed | Keep market-maker/flash-crash ideas as hypotheses; prove with L2/tape replay, not narrative |
| AI/1000% opportunity videos require strict skepticism | Use AI for research automation and labeling, not autonomous live trade decisions |
| New cards still do not prove a transferable 90% win-rate model | Continue rejecting win-rate-only strategy selection |

## 5. Updated Conclusion

The retry batches improved source grounding from 47 to 77 unique transcript-backed videos. This materially improves coverage of high-winrate/deposit-growth videos, but it does not change the project decision: current spot maker signals failed EV gates, and the next rational engineering branch remains research-only `perp_replay` plus liquidity-sweep/market-quality modeling.
