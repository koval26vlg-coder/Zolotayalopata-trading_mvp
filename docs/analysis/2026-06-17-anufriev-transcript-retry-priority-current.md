# Anufriev Transcript Retry Priority Current

Дата: 2026-06-17  
Статус: source-grounded приоритизация оставшегося transcript/source coverage gap. Это не список прибыльных стратегий и не торговая рекомендация.

## 1. Grounded Summary

В текущем `all287` scorecard есть `287` trading-relevant видео: `77` transcript-backed unique videos и `210` metadata-only rows. Этот документ ранжирует metadata-only хвост для повторной проверки transcript/timedtext/source packets. Приоритет выше у видео, связанных с high-winrate/deposit-growth, orderbook/market-maker/HFT, funding/carry/P2P/legal, futures/prop, risk/playbook, AI/bots, а также у свежих и более просматриваемых видео. Два последних Shorts из RSS refresh `2026-06-17 16:40` добавлены отдельно как `latest_rss_delta`, потому что они появились после старого каталога и касаются legal/custody риска.

## 2. Source Quality

| Source | Status | Limitation |
|---|---|---|
| `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv` | `287` trading-relevant rows | `210` metadata-only rows remain |
| `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json` | `77` transcript-backed unique videos | timedtext/ytdlp access incomplete |
| `exports/youtube-anufriev/anufriev_youtube_rss_refresh_delta_20260617_164026.csv` | `2` latest RSS delta Shorts | captions probe was empty/429 in local source packet |

## 3. Machine-Readable Artifact

CSV: `exports/youtube-anufriev/anufriev_transcript_retry_priority_current_20260617.csv`

Rows: `212`  
Metadata-only scorecard rows: `210`  
Latest RSS delta rows: `2`

## 4. Tier Counts

| Tier | Count |
|---|---:|
| P0 | 6 |
| P1 | 25 |
| P2 | 35 |
| P3 | 146 |

## 5. Top 30 Retry Priorities

| Rank | Tier | Video ID | Title | Views | Clusters | Participant | Score |
|---:|---|---|---|---:|---|---|---:|
| 1 | P0 | `pF181EcDFQc` | Вывел крипту - сел в тюрьму! / P2P по-русски: уголовка, суды, блокировки | 240597 | funding_passive_crypto,legal_regulatory_crypto | Андрей Тугарин | 207,906 |
| 2 | P0 | `m89dqFDSL2Q` | Где безопаснее хранить крипту? |  | legal_regulatory_crypto,venue_custody_risk |  | 196 |
| 3 | P0 | `TkQK2Bbvdek` | Как сейчас покупать крипту без 115 ФЗ? |  | legal_regulatory_crypto,venue_custody_risk |  | 196 |
| 4 | P0 | `mcYMwpHCdVM` | Как СНГ трейдеры зарабатывают на манипуляциях маркетмейкеров | 62702 | orderbook_scalping,general_trading | Нарэк Григорян | 189,986 |
| 5 | P0 | `-lrecTTpK4c` | Психология в трейдинге: Как стабильно зарабатывать и не ликвидироваться? | 5938 | orderbook_scalping,risk_psychology_playbook,general_trading |  | 174,869 |
| 6 | P0 | `18UNEZr2odw` | Что НЕЛЬЗЯ делать при выводе крипты | 381527 | legal_regulatory_crypto | Андрей Тугарин | 173,908 |
| 7 | P1 | `vKunPVUP1nk` | Скальпинг криптовалют - как сделать  трейдинг стабильным и предсказуемым | 111309 | orderbook_scalping,general_trading |  | 161,233 |
| 8 | P1 | `gtndD2L6iK4` | Как заработать на криптовалюте в 2023? Миллион $$$ в 24 года / Динар Банана | 56544 | high_winrate_deposit_growth,ai_trading | Динар Банана | 160,762 |
| 9 | P1 | `ZDCCw6Eh4HQ` | 2000 сделок в месяц: Как скальперы делают деньги на крипте? / Трейдинг криптовалют | 45877 | orderbook_scalping,general_trading |  | 159,308 |
| 10 | P1 | `kNOrNcUfK60` | Как превратить трейдинг в бизнес? На чем зарабатывают маркетмейкеры | 33346 | orderbook_scalping,general_trading |  | 158,615 |
| 11 | P1 | `-86Z9pMJRRM` | Как маркетмейкеры ликвидируют трейдеров / Андрей Грачев DWF | 26678 | orderbook_scalping,general_trading |  | 158,131 |
| 12 | P1 | `Csj02qT4F00` | Трейдинг криптовалют / Он показал софт маркетмейкера изнутри | 235735 | orderbook_scalping,general_trading |  | 156,862 |
| 13 | P1 | `PYfFtOIp84U` | Трейдинг криптовалют / Маркетмейкер DWF Labs | 132063 | orderbook_scalping,general_trading |  | 155,604 |
| 14 | P1 | `6mv11pIVE6E` | Трейдинг криптовалют / DWF Labs: о чем молчат маркетмейкеры? | 108790 | orderbook_scalping,general_trading |  | 155,183 |
| 15 | P1 | `MlHHgRps3vE` | Как люди РЕАЛЬНО разгоняют депозит в трейдинге: кейс на 600 ИКСОВ | 117151 | high_winrate_deposit_growth,general_trading |  | 154,344 |
| 16 | P1 | `7aZK_BnWHh0` | Миллион долларов на трейдинге с нуля: История, которая взрывает мозг | 88165 | high_winrate_deposit_growth,general_trading |  | 153,727 |
| 17 | P1 | `gQ9f2fFnDn8` | Airdrop криптовалют - почему только 1% заработает на дропах | 68550 | high_winrate_deposit_growth,ai_trading |  | 152,18 |
| 18 | P1 | `4iOjwZWb8jQ` | Трейдинговая стратегия, которая приносит прибыль на любом рынке | 19921 | high_winrate_deposit_growth,general_trading |  | 150,497 |
| 19 | P1 | `xVrV47cGBMU` | Самая прибыльная стратегия в трейдинге | 14739 | high_winrate_deposit_growth,general_trading |  | 149,842 |
| 20 | P1 | `Pc4llCsVeRQ` | Как не ПОТЕРЯТЬ ВСЕ из-за крипты / Разговор с юристом | 161196 | legal_regulatory_crypto | Андрей Тугарин | 148,037 |
| 21 | P1 | `uNYfylFFQ7g` | Трейдинг криптовалют / Максим HAMAHA - как торгуют профессионалы с Wall Street | 210766 | futures_prop_moex,general_trading | HAMAHA; Максим HAMAHA | 147,619 |
| 22 | P1 | `2BRrcgdBBr0` | Как ЛЕГАЛЬНО Покупать криптовалюту? Забудь про P2P! | 187832 | funding_passive_crypto |  | 147,369 |
| 23 | P1 | `m3Wcrtq36MM` | Как зарабатывают профессиональные трейдеры? Секреты трейдера с Wall Street | 10538 | futures_prop_moex,general_trading | HAMAHA; Максим HAMAHA | 147,114 |
| 24 | P1 | `jBJzuYlcq7s` | Нас ждет полный ЗАПРЕТ и КОНФИСКАЦИЯ крипты? Разбор с юристом | 80920 | legal_regulatory_crypto | Михаил Успенский | 146,54 |
| 25 | P1 | `dLpQ6oHnJIY` | Трейдинг без иллюзий: выгорание, убытки и ошибки всех новичков | 52663 | risk_psychology_playbook,general_trading | Андрей Демченко | 145,608 |
| 26 | P1 | `aPlHVyXlsgc` | Трейдинг криптовалют / Показал свою стратегию на подкасте | 269548 | general_trading | Игорь Андреев | 145,153 |
| 27 | P1 | `pGMQjvJR8fk` | Как заработать на криптовалюте и не слить все деньги? | 22855 | high_winrate_deposit_growth,ai_trading |  | 143,795 |
| 28 | P1 | `BPogxc1t5GM` | Трейдинг криптовалют / Разобрали торговую стратегию на подкасте | 99052 | general_trading | Игорь Андреев | 142,979 |
| 29 | P1 | `ZuOQ2hIDNZw` | Как заработать деньги на бирже в 2022 году. С чего начать и какие акции покупать? | 9702 | high_winrate_deposit_growth,ai_trading |  | 141,935 |
| 30 | P1 | `IpeygkYEk6o` | Крипта / Сергей Хитров - первый публичный крипто миллионер | 549954 | high_winrate_deposit_growth |  | 141,702 |

## 6. Scoring Method

Priority score is a deterministic heuristic based only on available local fields:

- `metadata-only` gap;
- latest RSS delta status;
- strategy clusters from the scorecard;
- title keywords connected to return/win-rate, orderbook/market-maker, funding/P2P/legal/custody, futures/prop;
- named participant and major participant match;
- view count weight;
- upload recency.

Provenance is marked `selected/interpreted-from-context` because the rank is derived from local scorecard fields, not from transcript content. A high rank means “verify this first”, not “this strategy works”.

## 7. Recommended Use

1. Retry transcripts for `P0` rows first with `--stop-on-rate-limit` behavior.
2. If transcript is still unavailable, create a metadata-only source packet and keep all claims weak.
3. Update participant and strategy scorecards only when a new transcript/source packet changes evidence strength.
4. Do not use metadata-only videos as hard proof of win-rate, PnL or strategy mechanics.

## 8. Current Project Impact

This list addresses the remaining channel-coverage gap. It does not change the trading decision: `trading_mvp` still has `0` accepted trading strategies, and the next proof step remains visible 7d funding/basis collection only after explicit user confirmation.
