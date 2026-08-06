# Fee-tier evidence: MEXC / Gate (E0)

Дата снятия: 2026-07-02
Агент: Claude Code
Метод: публичные REST API бирж без ключей (машиночитаемое evidence) + публичные страницы программ. Не инвестсовет.

Назначение: закрыть блокер funding-ветки «reopen only with non-secret fee-tier evidence» (scorecard 2026-06-28) и дать cost model проверяемые сценарии ставок для E0/H1/H2/H3 из `2026-07-02-edge-hypothesis-backlog.md`.

## Первичные артефакты (raw snapshots)

Папка: `exports/trading-mvp/analysis/fee_evidence_20260702/`

| Файл | Источник (public GET, без ключей) | Содержимое |
|---|---|---|
| `mexc_contract_detail.json` | `https://contract.mexc.com/api/v1/contract/detail` | 951 USDT-перп контракт с `makerFeeRate`/`takerFeeRate` |
| `gate_usdt_contracts.json` | `https://api.gateio.ws/api/v4/futures/usdt/contracts` | 823 USDT-перп контракта с `maker_fee_rate`/`taker_fee_rate` |
| `gate_spot_currency_pairs.json` | `https://api.gateio.ws/api/v4/spot/currency_pairs` | 2192 спот-пары с базовым `fee` |
| `mexc_spot_exchangeinfo.json` | `https://api.mexc.com/api/v3/exchangeInfo` | 2218 спот-символов с `makerCommission`/`takerCommission` |

## Распределение ставок (из снимков, per-contract)

### MEXC futures (951 контрактов)

| Ставка | maker | taker |
|---|---|---|
| 0.00% | **877** | **401** |
| 0.01% | 62 | 4 |
| 0.02% | — | 472 |
| 0.04% | 12 | 62 |
| 0.10% | — | 12 |

Базовый режим MEXC futures: **maker 0 bps / taker 2 bps**; на 401 контракте даже taker 0 bps (вероятно промо — при использовании перепроверять по снимку на дату).

### Gate futures (823 контракта)

Единые ставки на всех контрактах: **maker −1 bps (рибейт) / taker 7.5 bps**.

### Spot

- **MEXC spot**: maker 0 bps на 2165 из 2218 символов; taker 5 bps на большинстве (0 bps на 337).
- **Gate spot**: базовый fee 20 bps почти на всех парах (VIP/GT-скидки снижают, но базовый ярус дорогой).

## Программы (публичные условия)

- **Gate MM Program**: spot maker до −0.012%, futures maker ≤ −0.01%; вход по доле maker-объёма за 30 дней или trial при spot-объёме ≥ $20M/30д; контакт mm@gate.io. Источники: [анонс Gate (Medium)](https://gateio.medium.com/gate-io-leads-industry-with-0-012-market-maker-rebate-and-restructured-tier-discounts-75d990352d9f), [VIP/MM notice](https://gate.io/article/27235), [Spot MM Program](https://www.gate.io/announcements/article/27005). Вывод: **вне досягаемости на старте**; базовый futures maker −1 bps и так доступен всем.
- **MEXC**: формальной публичной MM-программы с условиями подачи не найдено ([обзор комиссий MEXC](https://www.mexc.com/learn/article/mexc-fees-explained-complete-trading-futures-withdrawal-fees-guide/1)); MX-токен в futures-аккаунте даёт скидку 20% на комиссии. Вывод: базовые ставки уже почти нулевые, MM-программа не нужна для входа.

## Сценарии для cost model (заменяют старое допущение «retail taker ~39 bps round-trip»)

| Сценарий | Нога | Ставки round-trip (только fees) |
|---|---|---|
| A. MEXC perp maker/maker | perp | **0 bps** |
| B. MEXC perp maker/taker | perp | 2 bps |
| C. Gate perp maker/maker | perp | **−2 bps (рибейт)** |
| D. Gate perp maker/taker | perp | 6.5 bps |
| E. MEXC spot maker + MEXC perp maker (carry) | spot+perp | **0 bps** |
| F. Gate spot base + Gate perp (carry) | spot+perp | ≥ 40 bps — **избегать Gate spot-ноги на базовом ярусе** |
| G. Cross-exchange perp-perp MEXC↔Gate maker | perp×2 | **−2 bps** |

Критически важно: при fees ≈ 0 **биндящим ограничением становится не cost gate, а execution gate** — spread, fill probability post-only, adverse selection, queue position. Пороговые таблицы (`2026-06-17-funding-economic-thresholds.md`, сценарий 39 bps) устарели как основной сценарий; сохранить их как stress-кейс.

## Следствия для backlog

1. **Funding-ветка (H3) разблокирована**: блокер «non-secret fee-tier evidence» закрыт этим документом. Повторный cost gate по сценариям A/E вместо 39 bps.
2. **H2 (cross-exchange funding carry)**: сценарий G даёт отрицательные суммарные fees — экономика решается спредом ставок funding и execution-риском, не комиссиями.
3. **H1 (momentum)**: недельный ребаланс перпами по сценариям A–D — fee-издержки перестают быть kill-фактором; главное — spread/slippage тонких рынков.
4. Kill rules goal v2 не меняются: cost gate остаётся, просто с честными сценариями; execution gate становится главным.

## Ограничения evidence

- Ставки могут меняться биржей в любой момент; снимки датированы 2026-07-02. Перед каждым cost-gate прогоном снимать свежий снапшот тем же методом (однострочные GET без ключей).
- Taker 0 bps на 401 контракте MEXC может быть временным промо.
- VIP-ярусы Gate spot не зафиксированы детально (страница за JS); базовый 20 bps достаточен как консервативный сценарий — spot-ногу планировать на MEXC.
- Withdrawal/deposit fees и venue-риск (кастоди на второэшелонной бирже) — вне этого документа, учитываются в economics/risk gates.
