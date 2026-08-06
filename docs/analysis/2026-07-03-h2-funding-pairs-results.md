# H2: cross-exchange funding pairs — результаты paired-анализа

Дата: 2026-07-03
Агент: Claude Code
Статус: research-only. Не инвестсовет. Вердикт promising, НЕ accepted.

Ledger: H2 `exp_20260703_090252_380b1c185495` (setup `cross_exchange_funding_carry`), H3 reopened `exp_20260703_090252_8fef38415a4e` (setup `funding_basis_carry`).
Артефакт: `exports/trading-mvp/analysis/funding_pairs_20260703_090100.json` (модуль `trading_mvp/src/funding_pairs.py`, 9 тестов OK).
Метод: 113 общих перп-символов MEXC∩Gate, 105 пар с ≥30 выровненных дней; дневной funding-спред (Gate−MEXC), знак-консистентность, basis-риск по дневным close обеих бирж, наличие спота на MEXC из fee-evidence снапшота. Окно 90 дней.

## Две разные конструкции (важно не путать)

1. **G: perp-perp спред (delta-neutral между биржами)** — собирается только РАЗНИЦА ставок; издержки ~−2 bps round trip (обе ноги maker).
2. **E: short MEXC perp + long MEXC spot** — собирается ВЕСЬ уровень funding ноги; издержки ~0 bps. Для двойне-положительных монет E строго доминирует G по доходу, но несёт спот-инвентарь на второэшелонной бирже.

## G-кандидаты (спред, sign consistency ≥0.75, |спред| ≥15%/год)

| Пара | Спред годовых | Consistency | Мин. объём 24ч | Basis std |
|---|---|---|---|---|
| RAVE_USDT | 91.5% | 0.84 | $2.0M | 106 bps |
| BROCCOLIF3B_USDT | 80.5% | 0.76 | $0.45M | 38 bps |
| EVAA_USDT | 37.1% | 0.88 | $1.0M | 26 bps |
| M_USDT | 28.4% | 0.89 | $6.0M | 31 bps |
| BEAT_USDT | 24.9% | 0.78 | $17.0M | 17 bps |
| NOM_USDT | 23.0% | 0.78 | $2.5M | 33 bps |

Примечание: высокие спреды с низкой консистентностью (GUA 125%/0.53, TAIKO 83%/0.17, H 50%/0.22) — НЕ кандидаты: знак скачет.

## E-кандидаты (short MEXC perp + long MEXC spot; leg ≥40%/год, спот есть)

| Монета | Funding-нога MEXC | Мин. объём 24ч | Basis std |
|---|---|---|---|
| SKYAI_USDT | +69.7% | $5.7M | 18 bps |
| BEAT_USDT | +56.4% | $17.0M | 17 bps |
| EVAA_USDT | +50.6% | $1.0M | 26 bps |
| BAS_USDT | +46.2% | $5.3M | 26 bps |
| PIPPIN_USDT | +44.3% | $0.5M | 23 bps |
| TAC_USDT | +42.8% | $9.8M | 97 bps |
| B_USDT | +40.6% | $1.3M | 15 bps |
| US_USDT | +40.2% | $2.2M | 36 bps |

Лучшие по совокупности (уровень × ёмкость × стабильность basis): **BEAT** ($17M, 17 bps), **SKYAI** ($5.7M, 18 bps), **BAS** ($5.3M).

## Почему promising, а не accepted

1. 90-дневное окно назад ≠ персистентность: funding-режим меняется; нужен multiweek FORWARD-мониторинг (данные копятся `daily_collector.py`).
2. Execution gate не пройден: maker-fill обеих ног, глубина стакана спота, проскальзывание входа/выхода не смоделированы.
3. Basis MtM-колебания (15–107 bps дневных) — не realized PnL, но требуют margin-модели.
4. Venue-риск: мем-коины/токенизированные акции на биржах второго эшелона; кастоди спот-ноги на MEXC.
5. Ёмкость: реалистично 0.1–1% дневного объёма на maker-исполнении — считать economics per-candidate.

## Следующие шаги ветки

1. Еженедельный forward-запуск `daily_collector.py` (тот же run-id для накопления) + пересчёт `funding_pairs.py` — отслеживание деградации кандидатов.
2. Execution gate: модель maker-fill и спот-глубины по топ-кандидатам (BEAT, SKYAI, BAS, M, EVAA).
3. Экономика с ёмкостью: реалистичный годовой доход при лимитах позиции.
4. После 3–4 недель стабильного forward: paper-forward план (без API-ключей, без live) через штатные ворота.
