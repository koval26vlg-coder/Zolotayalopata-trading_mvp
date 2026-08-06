# trading_mvp Fast-First Current Goal

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Найти, доказать или честно отвергнуть рабочий non-Binance trading edge с положительным net expectancy после базовых издержек через короткие frozen Fast-First гипотезы. Текущая активная ветка: `venue_local_weekend_liquidity_window_v1` (v6). Длительные сборы данных не входят в критический путь.

**Architecture:** Проект работает как последовательный fail-closed proof pipeline: frozen PlanOnly -> hash-bound evaluator -> один no-grid historical OOS -> stress/concentration/capacity gates -> короткий execution probe -> segmented paper-forward. Короткие owned no-grid evaluation/OOS/postprocess/report шаги по уже замороженному PlanOnly выполняются без отдельной фразы `подтверждаю`, если соблюдены safety-gates из раздела 20. Все тяжелые данные переиспользуются по hash; дневной процесс ограничен тремя часами, а кандидат-специфичный ночной процесс может занять окно `23:00-07:00 Europe/Volgograd` длительностью до восьми часов. Закрытые гипотезы не переоткрываются без нового независимого основания.

**Tech Stack:** Python 3.13, PowerShell 7, public REST MEXC/Gate, существующий `requests` stack, JSON/JSONL, единый `CostProfile`, `unittest`, артефакты на `E:\ZolotyayLopata-data\exports\trading-mvp`.

---

## 1. Каноническая цель

`trading_mvp Fast-First`: в кратчайший разумный срок получить воспроизводимый ответ, существует ли на доступных non-Binance рынках хотя бы один исполнимый edge, который:

- имеет положительное математическое ожидание после всех базовых издержек;
- не зависит от VIP, rebate, промоакций или нереалистичного maker fill;
- сохраняет знак результата на chronological OOS и walk-forward;
- выдерживает стресс по комиссиям, spread, impact, slippage и funding;
- имеет достаточное количество независимых событий и не держится на одной монете, бирже или сделке;
- допускает исполнение минимум `$500` на каждую ногу;
- подтверждается paper-forward до любого рассмотрения реального капитала.

Высокий win rate является только диагностикой. Он не может компенсировать отрицательные expectancy, profit factor, stress PnL или концентрационный риск.

## 2. Определение результата проекта

Цель считается достигнутой одним из двух честных исходов.

### Успешный исход

Хотя бы одна стратегия получает последовательно:

1. `ACCEPT_FOR_SHORT_EXECUTION_PROBE`;
2. `PAPER_READY`;
3. `LIVE_REVIEW_ELIGIBLE`.

`LIVE_REVIEW_ELIGIBLE` не запускает торговлю автоматически. API keys, реальные ордера и капитал требуют отдельного запроса и отдельного risk/security review.

### Отрицательный исход

Три заранее замороженные независимые Fast-First гипотезы, начиная с v4, проходят по одному честному no-grid циклу и получают `REJECT` или `INSUFFICIENT_DATA`. После этого фиксируется `NO_FAST_EDGE_FOUND`, новые signal families не генерируются автоматически, а дальнейший длинный сбор или смена рынка выносятся в отдельное решение пользователя.

## 3. Фактическая исходная точка

- Принятой стратегии сейчас нет.
- Fast-First v1: funding/carry, listing-event и slow-liquidity закрыты на текущих данных.
- Fast-First v2 `venue_local_perp_residual_dispersion_reversion_v1`: `INSUFFICIENT_DATA`, ретюнинг запрещен.
- Fast-First v3 `venue_local_lottery_max_factor_v1`: `INSUFFICIENT_DATA` и отрицательная наблюдаемая экономика; execution probe запрещен.
- Cross-venue spot dislocation, lead/lag, capitulation, HFT/order-book, breakout, momentum и liquidity-sweep ветки не переоткрываются на прежних данных.
- Старый PIT run `spot_pit_event_forward_20260712_225519` остается `STOPPED_INCOMPLETE`, diagnostic-only, без auto-resume.
- Durable WS dataset содержит 24 завершенных сегмента и 76,011,803 события, но имеет около 7.9 часа межсегментных gaps; он не считается непрерывным 72-часовым OOS.
- Недельный funding-forward task продолжает собирать вспомогательные данные. Он не является доказательством edge и не блокирует Fast-First.
- Simulator correctness findings H1-H9 уже исправлены; повторный P0-fix не нужен.

## 4. Непереговорные ограничения

### Время

- Дневной запуск в локальном окне `07:00-23:00 Europe/Volgograd`: максимум `10,800` секунд.
- Значение по умолчанию: `1,200` секунд.
- Historical evaluation target: не более `1,800` секунд.
- Execution probe target: `1,200` секунд.
- Короткий deterministic owned no-grid OOS/evaluation/postprocess на уже замороженном PlanOnly и существующих локальных данных не требует отдельного подтверждения пользователя, если `active-run gate` не `RUNNING`, запуск видимый, `MaxRuntimeSec<=1800`, без network collector, grid, retune, paper-forward, live orders, API keys, leverage или margin. В таком состоянии `продолжи`, `продолжи цель`, `что дальше` или `погнали` считается достаточным разрешением.
- Запуск, которому обоснованно требуется больше трех часов, откладывается на локальное окно `23:00-07:00 Europe/Volgograd` и может работать до `28,800` секунд, не обрываясь на дневном трехчасовом лимите.
- Ночной run должен стартовать не раньше `23:00`, завершиться не позже `07:00`, иметь frozen candidate/config, точный deadline, stop conditions и видимый monitor; при наличии достаточного объема полезной работы разрешено занимать все восьмичасовое окно.
- Ночное исключение не разрешает grid, OOS-retune, hidden/background execution, live orders, API keys, leverage или margin и не превращает общее слово `продолжи` в запуск конкретного длительного процесса.
- Длительный сбор не может быть условием начала реализации базового инструмента.

### Видимость и владение процессом

- Любой процесс, пишущий временные артефакты, запускается в видимом терминале.
- Monitor показывает stage, progress, ETA, rows/events, last write и последние ошибки.
- Скрытый `Start-Process`, blind background run и автоматический resume запрещены.
- Timeout или сеть переводят run в `STOPPED_INCOMPLETE`; частичные метрики не принимаются.
- Resume разрешен только с тем же `run_id`, matching hashes и явным видимым запуском.

### Торговые границы

- Binance используется только как reference/exclusion venue.
- Биржи исследования: MEXC и Gate.
- Режим: research-only и затем paper-only.
- API keys, live orders, leverage, margin и withdrawal permissions запрещены.
- Плечо в экономической модели: `1x`, полностью обеспеченная позиция.
- Новый контент канала, P2P, off-ramp, custody и legal темы не входят в цель.

### Исследовательская дисциплина

- Один frozen configuration на гипотезу.
- Grid search, OOS tuning, TP/SL search и post-hoc threshold changes запрещены.
- Train может использоваться только для заранее описанной стандартизации, не для перебора доходности.
- OOS читается только после plan hash, input Merkle hash и evaluator readiness.
- Отрицательная frozen ветка записывается в ledger и закрывается.
- `INSUFFICIENT_DATA` не превращается в автоматическое разрешение на длительный сбор.

## 5. Единая экономика

Использовать только `trading_mvp/src/costs.py::base_api_cost_profile()`.

| Venue | Market | Maker | Taker | Политика |
| --- | --- | ---: | ---: | --- |
| MEXC | Spot | 10 bps | 10 bps | консервативная неподтвержденная spot ставка |
| MEXC | Perp API | 6 bps | 8 bps | официальный API futures schedule с 2026-06-01 |
| Gate | Spot | 10 bps | 10 bps | base/VIP0 floor |
| Gate | Perp | 10 bps | 10 bps | base/VIP0 floor; отрицательные rebates игнорируются |

Каждый цикл учитывает:

- все entry и exit orders;
- maker fill probability и taker fallback;
- half-spread/full exit spread;
- depth impact;
- slippage;
- operational/rebalance buffer;
- funding cash flow отдельно от price alpha;
- stress: taker execution, p95 spread/impact, doubled buffer и нулевой кредит за благоприятный funding для v4.

Fee evidence может только повысить консервативную точность. Неподтвержденная скидка не может оживить отклоненную стратегию.

## 6. Первая новая гипотеза v4

### Идентификатор

`venue_local_funding_pressure_reversal_v1`

### Экономическая гипотеза

Экстремально положительный нормализованный funding отражает перегруженность long-side и должен предшествовать относительному отставанию цены. Экстремально отрицательный funding отражает перегруженность short-side и должен предшествовать относительному опережению цены. Это directional post-pressure reversal, а не funding carry: стратегия обязана быть прибыльной по price-only PnL после execution costs.

### Отличие от закрытых веток

- Не получает доходность удержанием spot/perp carry.
- Не сравнивает цены двух бирж.
- Не использует order book, trade flow, latency или HFT.
- Не использует listing age/events.
- Не использует liquidity shock как alpha.
- Не использует cumulative momentum, MAX20 или residual-dispersion как основной score.
- Liquidity применяется только для eligibility и capacity.

### Frozen signal contract

- Venue calculation: MEXC и Gate независимо.
- Instrument: USDT linear perpetual.
- Timestamp: только завершенные funding settlements и закрытые UTC daily bars.
- Funding normalization: каждый settlement приводится к 8-часовому эквиваленту через `rate * 28,800 / funding_interval_sec`.
- Main score: среднее нормализованных funding settlements за последние три полностью завершенных UTC дня.
- Candidate pool: максимум 12 наиболее ликвидных eligible рынков на venue, минимум 8.
- Selection: long два рынка с минимальным score, short два рынка с максимальным score.
- Tie-break: normalized base, затем symbol; результат детерминирован.
- Entry: next daily open после закрытия signal day.
- Exit: close третьего полностью завершенного daily bar после entry.
- Rebalance: каждые три дня от frozen anchor `2026-02-24`.
- Overlap: запрещен; максимум один portfolio на venue.
- Notional: `$500` на ногу, `$2,000` gross на venue portfolio.
- Portfolio: четыре perp legs, восемь orders за полный цикл.

### Eligibility

- Не менее 60 предыдущих закрытых daily bars.
- Не менее шести валидных funding settlements за последние три дня.
- Funding interval должен быть известен и положителен.
- Trailing 30-day median quote volume не менее `$5,000,000` для выбранной ноги.
- Capacity proxy минимум `$500` на выбранную ногу.
- Минимум восемь eligible markets на venue в signal date.
- Synthetic equity/index proxies, stablecoins, wrapped/staked assets и Binance spot-listed bases исключаются frozen universe rules.
- Данные после cutoff и открытый текущий bar исключаются.

### Predetermined robustness view

Robustness score вычисляется как same-date cross-sectional residual main score после контроля только за:

- prior five-day cumulative return;
- `MAX20`;
- log trailing 30-day median quote volume.

Это одна заранее заданная robustness-проверка, не отдельный grid dimension.

### Funding treatment

- Funding используется как signal input и отдельно записывается как cash flow.
- Acceptance определяется по price-only PnL после всех execution costs.
- Total PnL including funding публикуется отдельно.
- В stress весь благоприятный funding обнуляется, неблагоприятный сохраняется полностью.
- Funding не может превратить отрицательный price-only result в acceptance.

## 7. Frozen validation contract

### Historical split

- Использовать только common closed calendar, доступный обеим площадкам.
- Target split: 139 train days / 60 OOS days, как в sealed v3 calendar, если hashes подтверждают ту же history boundary.
- Если 60 OOS closed days недоступны, verdict только `INSUFFICIENT_DATA`.
- Train используется для проверки coverage и causal transformations; profit-driven parameter selection отсутствует.

### Walk-forward

- Пять последовательных 20-day folds.
- Anchored expanding history.
- Никакого refit signal parameters.
- Fold boundaries фиксируются в PlanOnly до OOS.

### Historical acceptance gates

- Input hashes match: обязательно.
- OOS closed days: минимум 60.
- OOS portfolio events: минимум 20 total.
- OOS events per venue: минимум 10.
- Unique OOS rebalance dates: минимум 10.
- Both venues OOS price-only expectancy: `> 0`.
- Combined OOS price-only profit factor: `>= 1.2`.
- Positive portfolio-event rate: `>= 60%`.
- Combined positive walk-forward folds: минимум 4 из 5.
- Positive folds per venue: минимум 3 из 5.
- Normal price-only PnL: положительный.
- Robustness price-only PnL: положительный.
- Stress price-only PnL: неотрицательный.
- Maximum drawdown: не более 10% peak allocated collateral.
- Single event positive-PnL share: не более 25%.
- Single base positive-PnL share: не более 25%.
- Single venue positive-PnL share: не более 75%.
- Break-even holding period: не более трех дней.
- Capacity proxy: минимум `$500` на каждую ногу.

Максимальный historical verdict из-за current-universe survivorship: `ACCEPT_FOR_SHORT_EXECUTION_PROBE`. Исторический тест не может сразу выдать `PAPER_READY` или live permission.

## 8. Verdict state machine

### `INSUFFICIENT_DATA`

Используется, если до измерения стратегии не хватает coverage, markets, settlements, events или capacity. Он не означает ни прибыльность, ни убыточность.

### `REJECT`

Используется, если данных достаточно, но нарушен хотя бы один economics/OOS/walk-forward/stress/concentration gate.

### `ACCEPT_FOR_SHORT_EXECUTION_PROBE`

Используется только если пройдены все historical gates. Следующий шаг ограничивается PlanOnly короткого probe.

### `PAPER_READY`

Используется после успешного execution probe и подготовки persistent paper state. Это не live permission.

### `LIVE_REVIEW_ELIGIBLE`

Используется только после минимум 15 завершенных paper portfolio observations, положительного paper net PnL после фактических simulated costs и отсутствия kill-switch/data-quality нарушений.

## 9. Execution probe

Probe запускается только после historical acceptance.

- Visible runtime: 20 минут.
- Snapshot interval: 5 секунд.
- Минимум 180 валидных snapshots.
- Markets: только legs, выбранные historical candidate/report.
- Fields: BBO, top quantities, depth around `$500`, quote age, mark/index, funding interval, API errors.
- Dual-leg/portfolio coverage: минимум 80%.
- p95 estimated impact: не более 10 bps на `$500` для каждой ноги.
- p95 combined spread + impact + slippage должен оставаться ниже historical break-even buffer.
- Stale quote, crossed book, zero depth или venue outage считаются invalid snapshots.
- Failure дает `REJECT_EXECUTION`, а не разрешение снизить capacity post-hoc.

## 10. Paper-forward

Paper-forward не является одним непрерывным процессом.

- Короткие видимые сегменты вокруг signal/entry/exit событий.
- Каждый segment ограничен 20 минутами.
- Позиция, cash, pending orders и funding settlements сохраняются между сегментами.
- State updates atomic; повтор одного event idempotent.
- Никаких API keys или реальных orders.
- Одновременно продолжается обычная инженерная работа; ожидание следующего события не блокирует проект.
- Минимум 15 завершенных portfolio observations.
- Paper net expectancy `> 0`, PF `>= 1.2`, stress reconciliation nonnegative.
- Максимум один data-quality/kill-switch incident; критический mismatch немедленно возвращает стратегию в research.

## 11. Risk gates перед live review

Даже после `LIVE_REVIEW_ELIGIBLE` требуется отдельный документ и отдельное подтверждение:

- exchange/account jurisdiction и доступность withdrawal проверены пользователем;
- API key без withdrawal, с IP allowlist и отдельным subaccount;
- secrets отсутствуют в git, logs, JSON и command history;
- max risk per position, daily loss limit и kill switch frozen;
- venue exposure limit исключает потерю основного капитала при блокировке биржи;
- startup reconciliation и emergency cancel tested в sandbox/paper режиме;
- реальный initial capital и допустимый убыток явно утверждены пользователем.

До этого момента проект остается research/paper-only.

## 12. Артефакты и provenance

Data root:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4`

Структура:

- `plans/` - canonical PlanOnly JSON;
- `manifests/` - run state и hashes;
- `evaluations/` - main и deterministic repeat;
- `reports/` - verdict и rejection reasons;
- `execution-probes/` - короткие BBO/depth samples;
- `paper-forward/` - persistent paper state и event ledger.

Каждый final artifact содержит:

- hypothesis id и frozen parameters;
- plan hash и plan file SHA-256;
- input file hashes и Merkle root;
- universe/config/cache hashes;
- fee provenance;
- Python/PowerShell/runtime versions;
- git HEAD и dirty-worktree marker;
- exact split/folds;
- normal/robustness/stress metrics;
- sample size и concentration metrics;
- deterministic result hash;
- verdict и полный список rejection reasons;
- единственную разрешенную следующую команду.

Эксперимент записывается append-only в setup registry и experiment ledger. Ошибочная provenance исправляется новой reconciliation record, а не переписыванием истории.

## 13. Реализационный план

### Task 1: Freeze v4 PlanOnly

**Files:**

- Create: `trading_mvp/src/funding_pressure_reversal.py`
- Create: `trading_mvp/tests/test_funding_pressure_reversal.py`
- Create: `tools/build_fast_first_v4_planonly.ps1`
- Create: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\plans\fast_first_funding_pressure_reversal_planonly_<stamp>.json`

**Steps:**

1. Написать fixture test canonical hash и frozen schema.
2. Проверить, что signal contract не читает OOS returns.
3. Реализовать только schema, data seal, costs, split, folds и gates.
4. Выполнить PlanOnly с `MaxRuntimeSec<=1200`.
5. Записать setup registry state `plan_frozen_oos_not_evaluated`.

**Acceptance:** plan содержит пустые OOS metrics, matching hashes и `evaluation_allowed=false`.

### Task 2: Build deterministic evaluator

**Files:**

- Modify: `trading_mvp/src/funding_pressure_reversal.py`
- Modify: `trading_mvp/tests/test_funding_pressure_reversal.py`
- Modify: `trading_mvp/src/cli.py`
- Modify: `trading_mvp/run_mvp.ps1`

**Required tests:**

- funding interval normalization;
- no settlement after signal cutoff;
- open daily candle exclusion;
- next-open/third-close execution;
- three-day non-overlap;
- deterministic four-leg selection/tie-break;
- exact eight-order normal/stress costs;
- favorable funding cannot rescue price-only rejection;
- chronological split and fixed folds;
- no OOS leakage or parameter refit;
- concentration, drawdown and verdict ordering;
- deterministic repeat hash.

**Acceptance:** targeted tests, fast shard and static checks pass; readiness artifact says `OOS_NOT_RUN`.

### Task 3: Add visible owned evaluation wrapper

**Files:**

- Create: `tools/run_fast_first_v4_evaluation_visible.ps1`
- Modify: `trading_mvp/tests/test_powershell_tooling.py`
- Modify: `tools/check_active_run_gate.ps1` only if v4 schema cannot be represented by the existing generic fields.

**Contract:**

- visible terminal only;
- `MaxRuntimeSec<=1800`;
- exact expected plan hash;
- owned `run_id` and hard deadline;
- atomic gate/manifest;
- two deterministic evaluations;
- process-tree termination on timeout;
- `STOPPED_INCOMPLETE` on any mismatch;
- no grid/probe/paper/live auto-chain.

### Task 4: Run one no-grid historical evaluation

**Preconditions:**

- gate не `RUNNING`;
- plan/evaluator/input hashes match;
- readiness tests pass;
- visible PlanOnly command shows exact duration, output paths и deadline.

**Run:** один configuration, два deterministic repeats, target runtime до 30 минут.

**Acceptance:** hashes совпадают, manifest final, verdict ровно один из `REJECT`, `INSUFFICIENT_DATA`, `ACCEPT_FOR_SHORT_EXECUTION_PROBE`.

### Task 5: Close or advance branch

- `REJECT`: append ledger closure, запретить retune и probe.
- `INSUFFICIENT_DATA`: append closure; разрешить только отдельный новый PlanOnly candidate, не auto-collect.
- `ACCEPT_FOR_SHORT_EXECUTION_PROBE`: создать probe PlanOnly; actual probe требует отдельного видимого запуска.

### Task 6: Execute bounded probe and paper-forward if eligible

- Probe: максимум 20 минут.
- Paper segments: максимум 20 минут каждый.
- Никаких ожиданий в активном терминале между market events.
- Engineering work не блокируется календарным paper-forward.

### Task 7: Project checkpoint after v4

Если v4 не принят, разрешены максимум две дополнительные независимые frozen hypotheses. Каждая обязана использовать существующие данные, пройти cost precheck до OOS и получить ровно один no-grid verdict. После третьей неудачи цель завершается `NO_FAST_EDGE_FOUND`, а не новым бесконечным циклом сигналов.

## 14. Тестовая матрица

### Unit

- Signal causality и exact timestamps.
- Cost accounting и funding separation.
- Missing data/funding interval handling.
- Split/folds/concentration/drawdown.
- Runtime cap/cache hash/gate state.

### Integration

- Fixture PlanOnly -> readiness -> deterministic evaluation -> report.
- Timeout -> `STOPPED_INCOMPLETE`.
- Hash mismatch -> fail closed до чтения OOS.
- Repeat result hash equality.

### Regression

- `python -m unittest trading_mvp.tests.test_funding_pressure_reversal`
- `pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1 -Shard fast -TimeoutSec 180`
- Existing funding, WS replay, costs, gate и experiment-ledger tests не меняют поведение.

### Prohibited acceptance shortcuts

- Не принимать результат только по train/full-sample PnL.
- Не принимать результат при `<20` OOS events.
- Не принимать один profitable venue при отрицательном втором venue.
- Не принимать total PnL, если price-only PnL отрицателен.
- Не принимать результат с failed stress или concentration gate.
- Не снижать thresholds после просмотра OOS.

## 15. Временной план

- Goal/state reconciliation: завершено этим документом.
- v4 PlanOnly + data seal: до 60 минут инженерной работы, network collect не требуется.
- Evaluator + tests: ориентир 2-4 часа инженерной работы, без длительного run.
- Historical evaluation: target до 30 минут в видимом терминале.
- Verdict/report: в тот же рабочий день после evaluator readiness.
- Execution probe: 20 минут только при historical acceptance.
- Paper-forward: короткие сегменты параллельно основной работе; календарное ожидание не блокирует проект.

## 16. Запрещенная работа до v4 verdict

- Новый 6h/24h/72h/7d/14d collector.
- Повтор старого PIT run.
- Новый grid-search.
- Retune закрытых веток.
- Live/API key integration.
- Косметический рефакторинг, не необходимый для v4 correctness.
- Анализ новых видео/каналов.
- Установка новых skills/plugins/MCP без обнаруженного конкретного blocker.

## 17. Текущий verdict и следующее разрешенное действие

Текущее состояние: `Task 1-4` завершены. Frozen PlanOnly, hash-bound evaluator, visible owned-run wrapper и один явно подтвержденный visible no-grid OOS выполнены.

OOS run: `fast_first_v4_funding_pressure_reversal_oos_20260714_132100`.

Verdict: `INSUFFICIENT_DATA`.

Основания:

- deterministic repeats совпали: `18bacc1aa059069ac96e5cfe9edf3af45fd040fa425c82a22a1da3e77c41ee04`;
- input Merkle совпал: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`;
- OOS closed days: `60/60`;
- total OOS portfolio events: `18/20`;
- Gate OOS portfolio events: `1/10`;
- MEXC OOS portfolio events: `17/10`;
- unique rebalance dates: `17/10`;
- main OOS price-only net PnL: `-383.38272157`;
- robustness OOS price-only net PnL: `-1161.4040304`.

Execution probe, paper-forward, live orders, API keys, leverage, margin, grid search и retune для `venue_local_funding_pressure_reversal_v1` запрещены. Funding-pressure branch закрыта на текущем evidence как insufficient/negative-economics, а следующий разрешенный маршрут: новая независимая Fast-First hypothesis PlanOnly без повторного тюнинга этой ветки.

## 18. Критерий готовности этого документа

- Цель, первая гипотеза, costs, signal, split, gates и stop rules заданы до OOS.
- Старые закрытые ветки явно исключены.
- Длительные сборы исключены из critical path.
- Первый шаг может быть выполнен на существующих данных.
- У каждого verdict есть единственный следующий маршрут.
- Документ не обещает прибыль, но создает кратчайший проверяемый путь к paper-ready стратегии или честному `NO_FAST_EDGE_FOUND`.

## 19. Текущая активная ветка v5

После закрытия v4 как `INSUFFICIENT_DATA` заморожена новая независимая Fast-First гипотеза:

`venue_local_wick_rejection_reversal_v1`

Смысл: same-venue daily wick/rejection reversal на USDT linear perpetual markets. Гипотеза не использует funding/carry, cross-venue spread, HFT/orderbook, listing-event, slow-liquidity, residual dispersion, MAX20 или повторный тюнинг закрытых веток.

Frozen PlanOnly artifact:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\plans\fast_first_wick_rejection_reversal_planonly_20260714_140353.json`

Manifest:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\manifests\fast_first_v5_wick_rejection_planonly_20260714_140353.manifest.json`

Hashes:

- plan hash: `d553c0120b0c3fcb3e4ff80d097bb8270788f690ab703c4b9c3c92d75db5277c`;
- plan file SHA-256: `1dfd997bf7661f9fe8c6e73b5367500f1ea92cfa47ddac2dd3210d8a4135ea4d`;
- input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`.

Проверки:

- targeted v5 unit tests: `12/12 OK`;
- evaluator readiness: `FAST_FIRST_V5_EVALUATOR_READY_OOS_NOT_RUN`;
- readiness artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\manifests\fast_first_v5_wick_rejection_evaluator_readiness_20260714_1411.json`;
- evaluator SHA-256: `28cf56212a58db456564e4dd45f75038471c23b57c4ea5c11f1f48a867d652ec`;
- verified source files: `195`;
- input hashes match: `true`;
- OOS metrics not read: `true`;
- grid/search/probe/paper/live/API: `false`.

Следующее разрешенное действие:

`Run visible owned no-grid v5 OOS evaluation with MaxRuntimeSec<=1800; no collector, no grid, no retune, no paper-forward, no live orders, no API keys, no leverage/margin.`

## 20. Confirmation policy correction

Это целевая корректировка по команде пользователя от 2026-07-14: короткие действия proof-pipeline не требуют отдельного ручного подтверждения и не должны переводить цель в `blocked`, если одновременно выполнены все условия ниже:

- `active-run gate` не находится в статусе `RUNNING`;
- есть frozen PlanOnly artifact, expected plan hash и input Merkle hash;
- evaluator/readiness уже валидирован и имеет статус `*_EVALUATOR_READY_OOS_NOT_RUN`;
- запуск видимый или через visible monitor;
- `MaxRuntimeSec<=1800`;
- выполняется только deterministic owned no-grid OOS/evaluation/postprocess/report по существующим локальным данным;
- нет network collector, grid-search, retune, paper-forward, live orders, API keys, leverage, margin, hidden/background run или автоматического перехода в следующий рискованный этап.

В этом состоянии команды пользователя `продолжи`, `продолжи цель`, `что дальше`, `погнали`, `давай дальше` считаются достаточным разрешением для следующего короткого proof-step. Нельзя снова переводить цель в `blocked` только потому, что такой короткий OOS/evaluation/postprocess не получил отдельную фразу `подтверждаю`.

Отдельное явное подтверждение по-прежнему обязательно для collectors, public probes, execution probes, grid/search, paper-forward, long/night runs, hidden/background процессов, live/API keys, leverage/margin и любых запусков дольше `1800` секунд.

Практическое следствие для текущей цели: после статуса `*_EVALUATOR_READY_OOS_NOT_RUN` агент должен сам выполнить следующий видимый owned no-grid OOS/evaluation/postprocess/report шаг по frozen artifact, если gate не `RUNNING` и все ограничения выше соблюдены. Блокировка допустима только при реальном blocker: `RUNNING` gate, hash mismatch, missing readiness, отсутствующий artifact, превышение лимита времени, требование network/probe/grid/paper/live/API или ошибка, которую нельзя безопасно обойти.

## 21. V5 OOS verdict

Visible owned no-grid OOS evaluation completed:

- run id: `fast_first_v5_wick_rejection_oos_20260714_142908`;
- evaluation: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\evaluations\fast_first_v5_wick_rejection_oos_20260714_142908.json`;
- manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\manifests\fast_first_v5_wick_rejection_oos_20260714_142908.manifest.json`;
- verdict: `INSUFFICIENT_DATA`;
- deterministic result hash: `e5558024c9daeccfa9414e9eaa13b72f050558bf8d47407d10c236a94492a3a2`;
- deterministic repeat equal: `true`;
- OOS portfolio events: `0`;
- main OOS price-only net PnL: `0`;
- rejection reasons: `oos_portfolio_events_total_below_minimum`, `oos_portfolio_events_below_minimum:mexc`, `oos_portfolio_events_below_minimum:gateio`, `unique_oos_signal_dates_below_minimum`, `capacity_proxy_unavailable`.

Decision: `venue_local_wick_rejection_reversal_v1` is closed on current evidence. No grid, retune, execution probe, paper-forward, live orders, API keys, leverage or margin are allowed for v5. The next allowed action is to freeze a genuinely new independent Fast-First hypothesis in PlanOnly, or stop after the configured hypothesis limit if no independent candidate remains.

## 22. Текущая активная ветка v6

После закрытия v5 как `INSUFFICIENT_DATA` заморожена последняя разрешенная независимая Fast-First гипотеза:

`venue_local_weekend_liquidity_window_v1`

Смысл: same-venue fixed UTC weekend-liquidity calendar window на USDT linear perpetual markets. Гипотеза не использует funding/carry, wick-rejection, momentum/breakout, cross-venue spread, HFT/orderbook, listing-event, slow-liquidity, residual dispersion или lottery/MAX branches.

Frozen PlanOnly artifact:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\plans\fast_first_weekend_liquidity_window_planonly_20260714_143640.json`

Manifest:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\manifests\fast_first_v6_weekend_liquidity_planonly_20260714_143640.manifest.json`

Hashes and coverage:

- plan hash: `18af65fc211d31a8a0f38bc6d9161b4adf7a92404aba788dfb66c45d2af850a9`;
- input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`;
- markets total: `97`;
- candidate weekend entry days: `29`;
- evaluation allowed: `false`;
- OOS metrics read: `false`.

Следующее разрешенное действие:

`Implement and test the hash-bound no-grid v6 evaluator. Do not run OOS until evaluator readiness is validated.`

Так как v6 является второй и последней дополнительной гипотезой после v4, ее отрицательный или insufficient OOS verdict должен привести к `NO_FAST_EDGE_FOUND` для текущего Fast-First track, если не появится отдельное явное решение пользователя открыть новый research scope или длинный сбор.

## 23. V6 OOS verdict and Fast-First closure

Hash-bound evaluator/readiness для `venue_local_weekend_liquidity_window_v1` реализован и проверен.

Readiness artifact:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\manifests\fast_first_v6_weekend_liquidity_evaluator_readiness_20260714_1456.json`

Readiness status:

`FAST_FIRST_V6_EVALUATOR_READY_OOS_NOT_RUN`

Проверки readiness:

- plan hash: `18af65fc211d31a8a0f38bc6d9161b4adf7a92404aba788dfb66c45d2af850a9`;
- input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`;
- verified source files: `195`;
- evaluator SHA-256: `dea39bd47c5c166b7a34a79547676d74de2804cf3534d0514ddff5ca3f223528`;
- OOS metrics read: `false`;
- grid/probe/paper/live/API: `false`.

Visible owned no-grid OOS evaluation completed without separate confirmation under the short proof-step policy:

- run id: `fast_first_v6_weekend_liquidity_window_20260714_145633`;
- evaluation: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\evaluations\fast_first_v6_weekend_liquidity_window_20260714_145633.json`;
- repeat: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\evaluations\fast_first_v6_weekend_liquidity_window_20260714_145633.repeat.json`;
- manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\manifests\fast_first_v6_weekend_liquidity_window_20260714_145633.manifest.json`;
- deterministic repeat equal: `true`;
- deterministic result hash: `6c05f8ed9b919371295722a4f8cb06c505bf3ec5e51eddc7fcf382010bdf5a78`;
- verdict: `INSUFFICIENT_DATA`;
- OOS portfolio events: `7`;
- main OOS net PnL: `1334.18586393`;
- OOS profit factor: `29.98637344`;
- OOS positive event rate: `0.85714286`;
- stress net PnL: `1320.88586393`;
- rejection reasons: `oos_portfolio_events_total_below_minimum`, `oos_portfolio_events_below_minimum:gateio`.

Interpretation: v6 showed attractive sample metrics, but the sample is too small and venue coverage fails the frozen gates. This is not accepted evidence and does not authorize execution probe, paper-forward, live orders, API keys, leverage, margin, grid search or retune.

Fast-First track closure:

`E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\reports\fast_first_track_closure_no_fast_edge_found_20260714_1500.json`

Decision:

`NO_FAST_EDGE_FOUND`

Reason: v4, v5 and v6 were the configured frozen independent Fast-First hypotheses. All returned `REJECT` or `INSUFFICIENT_DATA`; none reached `ACCEPT_FOR_SHORT_EXECUTION_PROBE`. Current Fast-First track is therefore closed. Any further work requires a new explicit research scope or explicit approval for new data collection; do not retune v4-v6.
