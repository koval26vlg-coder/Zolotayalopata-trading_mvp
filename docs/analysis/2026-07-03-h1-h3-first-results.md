# H1 momentum + H3 funding cost gate v2: первые результаты

Дата: 2026-07-03
Агент: Claude Code
Статус: research-only. Не инвестсовет. Ни один результат не является принятой стратегией.

Данные: `exports/trading-mvp/daily/daily_collect_20260702_top200` (400 перп-рынков MEXC/Gate, 170K дневных свечей, 489K funding-записей, ошибок 0).
Издержки: сценарии A–G из `2026-07-02-fee-tier-evidence.md`.

---

## H1: cross-sectional momentum (weekly L/S)

Ledger: `exp_20260703_084900_27d97535f1dc`, setup `cross_sectional_momentum_daily`. Артефакт: `exports/trading-mvp/backtests/momentum_daily_20260703_084744.json`.

Протокол: lookback {30/60/90д} выбирался ТОЛЬКО на train (первые 70% недель, сценарий B + slippage 10 bps); OOS (последние 28 недель) оценивался только для выбранного lookback=30.

### Результаты OOS (extended universe, 287 рынков после dedupe)

| Сценарий | mean/нед | t-stat | PF | hit | maxDD |
|---|---|---|---|---|---|
| A maker/maker (0 bps) | +181 bps | 1.50 | 2.18 | 0.68 | 19.2% |
| B maker/taker (2 bps) | +179 bps | 1.48 | 2.16 | 0.68 | 19.2% |
| D Gate maker/taker (6.5 bps) | +175 bps | 1.45 | 2.12 | 0.68 | 19.4% |
| stress 39 bps | +142 bps | 1.18 | 1.85 | 0.64 | 20.3% |

Walk-forward половины OOS: +125 и +234 bps/нед (обе положительные). Funding-вклад: +73 bps/нед в среднем.

Baseline (non-Binance, 68 рынков): OOS +602 bps/нед, t=2.06 — **не доверять**: цифры раздуты survivorship/илликвидностью, помечено в ledger как `inflated_do_not_trust`.

### Вердикт H1: **promising, НЕ accepted**

Причины не принимать:
1. **Survivorship/look-ahead bias universe**: выборка = сегодняшние top-200 по обороту. Погибшие монеты отсутствуют; попадание в universe коррелирует с недавним ростом → длинная нога завышена. Это главный известный дефект результата.
2. t-stat 1.5 на 28 OOS-неделях — ниже порога значимости.
3. Concentration-check по рынкам не выполнен.

Что нужно для промоушена (в порядке):
1. Survivorship-чистый universe: исторические составы (например, по датам листинга контрактов + архивным снапшотам объёма). Без этого paper-forward не обсуждается.
2. Удлинить OOS (больше истории или forward-накопление).
3. Per-market attribution + concentration cap.

Положительное: эффект пережил все fee-сценарии включая stress 39 bps, обе WF-половины положительные, funding-вклад положительный — гипотеза жива и заслуживает следующего раунда данных.

## H3: funding cost gate v2 (carry разблокирован)

Артефакт: `exports/trading-mvp/analysis/funding_costgate_v2_20260703.json` (373 символа, окно 90 дней).

Старый блокер снят: при сценариях E (MEXC spot maker + perp maker = 0 bps) и G (cross-exchange perp-perp maker = −2 bps) cost gate проходит по построению — вопрос сместился в устойчивость funding и execution/venue-риски.

Сводка (90 дней): медианный annualized funding по universe = 2.3%; **77 символов ≥10% годовых при positive_share ≥0.7; 63 символа ≥20%**. Топ: BROCCOLIF3B (Gate 155% / MEXC 73%), QCOM 96%, SKHYNIX 81%, PTB 80%, SKYAI (Gate 78% / MEXC 70%, positive_share 1.00 на обеих).

Для H2 (cross-exchange): SKYAI и BROCCOLIF3B имеют устойчиво положительный funding на ОБЕИХ биржах с существенным спредом — прямые кандидаты paired-анализа.

Честные оговорки:
- Топ — мем-коины и токенизированные акции: высокий venue/liquidity риск, funding может развернуться, ёмкость мала.
- Сценарий E требует наличия ликвидной spot-пары на MEXC для конкретной монеты — проверять per-symbol.
- 90 дней ≠ доказательство персистентности: нужен multiweek forward-мониторинг (данные уже копятся этим же коллектором).
- Basis-риск между ногами не смоделирован — это execution gate следующего шага.

## Следующие шаги

1. **H3/H2**: paired-анализ carry по кандидатам (funding спред, basis, спот-наличие, глубина стакана) + перезапуск штатного funding final-review с fee evidence v2 вместо 39 bps. Forward-накопление funding продолжать (`daily_collector.py --run-id` еженедельно).
2. **H1**: survivorship-чистый universe как условие следующей итерации; до этого не оптимизировать параметры дальше (стоп по правилу multiple testing).
3. Обновить strategy scorecard: funding-ветка из `blocked` → `reopened_research`, momentum добавить как `promising`.
