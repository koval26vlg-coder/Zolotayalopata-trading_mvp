# trading_mvp: варианты цели после предложения Claude

Дата: 2026-07-15  
Статус: `PROPOSED_NOT_ACTIVE`  
Режим: research-only, MEXC/Gate, non-Binance, без live orders, private API keys, leverage и margin.

## Решение

Предложение Claude правильно меняет критический путь с многонедельного forward-сбора на быстро доступную историческую выборку. Однако вариант `4h + daily + funding x top-200 x 2 venues за 12-18 месяцев` нельзя принимать без изменений.

Рекомендуемая цель: создать новый неизменяемый контракт `cross_venue_perp_basis_convergence_4h_v2`, переиспользовать существующие daily/funding данные и загрузить только недостающие 4h trade/mark/index series для небольшого frozen universe. За 1-3 рабочих дня получить один терминальный исторический verdict, без grid-search и перебора запасных гипотез.

Закрытый контракт `cross_venue_perp_basis_convergence_history_v1` не изменяется и не переоткрывается. Его `INSUFFICIENT_DATA` относится к публичной 5m retention Gate и не доказывает отсутствие edge на 4h данных.

## Проверенные факты

1. Текущий active-run gate находится в `READY_FOR_POSTPROCESS`; 5m historical-basis ветка закрыта с причиной `GATE_5M_PUBLIC_HISTORY_RETENTION_LT_FROZEN_220D` и `replay_allowed=false`.
2. Кэш `daily_collect_20260702_top200` уже содержит 730-дневный запрос по 400 venue-symbol: `170216` daily rows, `488862` funding rows, `0` ошибок, runtime около `251` секунды. Повторный полный daily/funding backfill не создаёт новой информации.
3. После canonical identity и category exclusions в существующем кэше есть 32 dual-venue non-Binance assets. Историю не менее 300 дней имеют 12 текущих кандидатов с худшей текущей ногой не ниже `$1m` quote volume; не менее 365 дней при том же статическом фильтре имеют только 7, а 540 дней только 2. Поэтому обязательные 12-18 месяцев конфликтуют с минимумом восьми исполнимых активов.
4. Публичный точечный probe старых 4h trade/mark/index series для `HYPE`, `KAS` и `XMR` дал `18/18` успешных ответов MEXC/Gate. Это подтверждает техническую доступность нового 4h слоя, но ещё не его полную coverage и корректность схемы.
5. Текущая реализация historical-basis жёстко привязана к 5m/220d. Для 4h нужен новый versioned PlanOnly и новый output namespace, а не изменение frozen v1.

## Что исправить в предложении Claude

| Предложение | Решение Codex | Причина |
|---|---|---|
| Повторно собирать `4h + daily + funding` | Собирать только отсутствующие 4h trade/mark/index; daily/funding брать из immutable cache | Daily/funding уже собраны глубже требуемого окна |
| Загружать top-200 на каждой бирже | Сначала canonical join, затем максимум 20 кандидатов | Снижает трафик, collision и multiple-testing risk |
| Требовать 12-18 месяцев | Freeze 300 закрытых дней | 365/540 дней оставляют меньше восьми статически исполнимых кандидатов |
| Новый Merkle даёт три новых hypothesis slots | Один новый materially-different primary contract | Новый датасет сам по себе не отменяет hypothesis farming |
| Дать 2-3 вердикта за неделю | Один primary verdict и deterministic repeat | Серийный перебор после просмотра результатов создаёт selection bias |
| Вероятность ACCEPT около 30-50% | Не публиковать вероятность до evidence | Число не имеет эмпирической калибровки |
| При reject перейти к резервной гипотезе | Закрыть sprint; следующая ветка требует нового PlanOnly | Исключает ретюнинг и условный перебор |
| 10 делистнутых символов как survivorship-check | Детерминированный lifecycle census либо явная survivor-conditional маркировка | Малый ручной sample не устраняет survivorship bias |

## Варианты цели

### A. Узкий 4h historical proof sprint

**Вердикт: рекомендован.**

- Новая информация: только 4h trade/mark/index MEXC/Gate.
- Календарное время до исторического verdict: 1-3 рабочих дня.
- Сетевой runtime: один видимый collector, максимум 90 минут.
- Один frozen signal contract, no-grid, no-retune.
- Максимальный результат: `ACCEPT_FOR_EXECUTION_PROBE`.
- Главный риск: 4h bars могут скрыть кратковременную конвергенцию и дать мало независимых episodes.

### B. Внешний архив 5m/tick данных

**Вердикт: только отдельным решением.**

- Потенциально даёт лучшую модель path, entry и execution.
- Требует проверки лицензии, provenance, полноты delisted symbols и стоимости.
- Не переоткрывает v1; создаёт отдельный v2 с новым источником данных.
- Имеет смысл только если вариант A вернёт `INSUFFICIENT_DATA` именно из-за временного разрешения, а не отрицательной экономики.

### C. PIT membership-drift forward track

**Вердикт: оставить shadow-track.**

- Наиболее чистое forward evidence.
- Не может дать быстрый verdict: доказательная единица равна новой календарной дате.
- Один 20-минутный сегмент на новую дату; не находится на критическом пути.

### D. Paper OMS/product readiness без нового edge

**Вердикт: делать параллельно как engineering track.**

- Можно подготовить deterministic paper OMS, reconciliation, kill-switch, fee accounting и venue health.
- Ускоряет путь после historical ACCEPT.
- Не считается доказательством alpha и не разрешает live.

### E. Полный backfill top-200 и 2-3 последовательные гипотезы

**Вердикт: отклонён в исходном виде.**

- Дублирует daily/funding cache.
- Увеличивает acquisition и QC без роста доказательности.
- Создаёт multiple-testing и hypothesis-slot farming.
- Срок больше, а terminal verdict слабее контролируется.

## Рекомендуемая каноническая цель

`trading_mvp 4H Historical Proof Sprint v2`: за максимум три рабочих дня создать воспроизводимый терминальный verdict для одного нового MEXC/Gate non-Binance edge `cross_venue_perp_basis_convergence_4h_v2`. Использовать существующий immutable daily/funding cache и загрузить только недостающие 4h trade/mark/index данные. Не применять grid-search, TP/SL/trailing tuning, резервный перебор гипотез или чтение OOS до train-feasibility. Результат: `ACCEPT_FOR_EXECUTION_PROBE`, `REJECT` или `INSUFFICIENT_DATA`.

### Frozen data contract

- Venues: только MEXC и Gate.
- Instruments: совпадающие USDT linear perpetual.
- Binance: reference/exclusion only.
- History: 300 полностью закрытых дней.
- Split: 30 дней warm-up, 135 дней train, 135 дней OOS.
- Walk-forward: пять непересекающихся OOS folds по 27 дней.
- Universe: максимум 20 canonical candidates до чтения returns; минимум 8 после quality и train-only liquidity gates.
- Series: 4h trade, mark и index обеих venues; funding по фактическим settlement timestamps из существующего cache.
- Output: новый immutable namespace и новый Merkle; v1 не изменяется.
- Selection: identity, lifecycle, non-Binance и data availability; liquidity вычисляется только на warm-up/train.

### Frozen strategy contract

- `venue_basis_bps = (mark - index) / index * 10000`.
- `basis_spread_bps = high_basis - low_basis`.
- Long low-basis venue, short high-basis venue.
- Сигнал только после закрытия 4h bar; entry по open следующего trade bar.
- Exit при convergence до frozen exit level либо по frozen max hold.
- Threshold вычисляется один раз из conservative `CostProfile`, exit level и safety margin.
- Position size `$500` на каждую ногу, fully funded `1x`.
- Funding обеих ног учитывается отдельно; positive funding не может компенсировать отрицательный price-only expectancy для ACCEPT.
- Параметры не меняются после plan freeze.

### Этапы

1. `PlanOnly/preflight`, до 30 минут: immutable code snapshot, canonical universe, source schema, pagination, lifecycle и cache hashes. Returns/PnL не читать.
2. `4h collect`, до 90 минут: один видимый owned collector, concurrent token buckets per venue, resume по page hash, fail-closed manifest.
3. `Quality`, до 30 минут: coverage, duplicates, open bars, timestamp convention, mark/index semantics, gaps, lifecycle masking и funding alignment.
4. `Train feasibility`, до 30 минут: только episode/date/asset/direction counts до открытия OOS.
5. `OOS evaluate`, до 30 минут: один no-grid run на frozen hashes и один deterministic repeat.
6. `Report`, до 30 минут: terminal verdict и ровно одна next allowed command.

### Feasibility gate

- Минимум 8 canonical assets после quality filtering.
- Trade/mark/index coverage каждой ноги не ниже 98%.
- Dual-venue aligned coverage не ниже 95%.
- Funding settlement coverage не ниже 98%.
- Минимум 20 независимых train episodes, 10 дат и обе стороны направления.
- При провале OOS не читается; verdict `INSUFFICIENT_DATA`.

### OOS acceptance gate

- Минимум 40 независимых episodes, 20 дат и 8 assets.
- Price-only net expectancy after costs больше нуля.
- Total net expectancy after costs и funding больше нуля.
- Profit factor не ниже 1.2.
- Не менее 4 из 5 folds положительны.
- Stress net PnL неотрицательный.
- Cluster-bootstrap 95% lower bound expectancy больше нуля.
- Оба направления `MEXC-cheap` и `Gate-cheap` отдельно неотрицательны.
- Концентрация одной base/date/episode не выше 25% положительного PnL.
- Max drawdown не выше 10% одновременно обеспеченного капитала.
- Deterministic repeat даёт тот же result hash.

### Stop rules

- Negative train economics, OOS, walk-forward или stress закрывают ветку как `REJECT`.
- Недостаток истории, universe или episodes даёт `INSUFFICIENT_DATA`, а не ослабление gate.
- После просмотра train/OOS нельзя менять threshold, hold, exit, universe или costs.
- Reject не запускает резервную гипотезу в этом sprint.
- Historical ACCEPT разрешает только короткий execution-probe PlanOnly; не paper/live автоматически.

## Ожидаемый календарь

| День | Результат |
|---|---|
| D1 | Freeze v2, schema/pagination/lifecycle preflight, universe hash |
| D2 | Видимый 4h collect, quality и Merkle freeze |
| D3 | Train feasibility, один OOS, deterministic repeat, terminal report |
| D4-D7 | Только при ACCEPT: plan execution probes; иначе sprint завершён |

Это быстрее предложения Claude, потому что критический путь содержит один новый слой данных и один гипотезный контракт. При этом скорость достигается устранением лишней работы, а не ослаблением evidence gates.

## Что не активировано

- Новый PlanOnly ещё не создан.
- Collector, evaluator и OOS не запускались.
- Гипотезный банк и frozen v1 не изменялись.
- Текущий документ является предложением цели для принятия, а не разрешением на market-data run.
