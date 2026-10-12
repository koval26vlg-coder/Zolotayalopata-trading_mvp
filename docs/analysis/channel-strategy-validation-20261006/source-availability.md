# Доступность исторических источников

Проверено 6 октября 2026. Наличие страницы загрузки не равно наличию полного входа для модели.

| Источник | Что подтверждено | Чего пока недостаточно |
|---|---|---|
| Локальный E:\ZolotyayLopata-data | Каталог недоступен в текущей среде | Нельзя проверить старые входы, coverage и просмотренные периоды по старым отчётам |
| Gate | Официальная документация описывает месячные свечи, сделки, стаканы и funding. Разовая выборка: 12/12 gzip-файлов BTC/ETH успешно получены и распакованы | Только три месяца двух активов; нет полного PIT состава, исключённых/делистнутых активов и всей временной сетки |
| MEXC | Официальная страница показывает ежедневные и ежемесячные спотовые данные | Не проверено полное синхронное покрытие Gate/MEXC и история стаканов/funding за нужные периоды |
| Binance | Официальный public-data repository документирует daily/monthly архивы и SHA256 checksum | Только справочный источник. Не подменяет исполнение на Gate/MEXC и исторический Gate universe |
| OKX | Исторический портал доступен; региональная страница отдаёт оболочку, не проверенную таблицу контрактов | Бесплатные полные исторические option bid/ask chains не подтверждены; свечи underlying не являются заменой |
| Dukascopy | Официальный экспорт исторических bid/ask и объёмов документирован | Нужно проверить точный инструмент, календарь, валюту, размер контракта и покрытие; CFD не равен биржевому DAX future |
| Aave | Официальные subgraphs поддерживают исторические запросы по номеру блока | Нет проверенного бесплатного полного пакета v3 Ethereum USDC: index + gas + USDC price + withdrawal liquidity |
| Акции США | Полный point-in-time intraday набор здесь не получен | Нужны delisted, corporate actions, regular sessions и borrow evidence для short |
| Ethereum wallets | Полный исторический набор здесь не получен | Нужны прошлые адресные rankings, исчезнувшие токены, продаваемость, block-lag quotes, gas и impact |

## Первичные источники

- [Gate: Historical quotation data](https://www.gate.com/developer/historical_quotes).
- [MEXC: исторические рыночные данные](https://www.mexc.com/ru-RU/market-data-download).
- [Binance Public Data](https://github.com/binance/binance-public-data).
- [OKX Historical Data](https://www.okx.com/en-us/historical-data).
- [Dukascopy: Historical data export](https://www.dukascopy.com/api/data/get/historical-data-export).
- [Aave protocol-subgraphs](https://github.com/aave/protocol-subgraphs/blob/main/README.md).

Binance отдельно предупреждает об изменении spot timestamps на микросекунды с 2025 года.
Нормализатор должен явно переводить единицы, а не угадывать их по первой цифре.

## Разовая проверка Gate

`history_sources_v1_20261006`, видимое окно, один global writer, 12 запросов, без повторов,
без proxies и redirects. Источник каждого файла, его SHA256, размер и первые/последние строки
сохранены в `runs/history_sources_v1_20261006/artifacts/public-history-sample/source-audit.json`.
Воспроизводимый снимок метаданных: `gate-source-audit.json` рядом с этим документом.
Архивы остаются локальными, не публикуются в Git.

Колонка объёма в полученных CSV не должна автоматически называться quote-turnover.
До проверки единиц нельзя ранжировать universe по предположению volume * close:
это не точный дневной оборот. Отсутствие такого доказательства является блокером данных,
а не поводом выбрать сегодняшний топ-10 или подменить рынок Binance.

`BLOCKED_DATA` в текущей матрице означает отсутствие полного проверенного входа сейчас.
Это **не утверждение, что бесплатная история нигде не существует**.
