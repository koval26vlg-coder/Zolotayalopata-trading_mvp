# trading_mvp: ЦЕЛЬ — единый документ для Codex

> **Действующий маршрут с 2026-08-01:** [Accelerated Evidence Factory v1](./2026-08-01-trading-mvp-accelerated-evidence-factory-v1.md). Исходные basis-ветки v1/v2 ниже остаются terminal pre-OOS (`INSUFFICIENT_DATA` / `INSUFFICIENT_EXECUTABLE_UNIVERSE`) и не переоткрываются. Текущий materially distinct кандидат — `dense_ws_microstructure_regime_filter_v1`; exact campaign `dense_ws_microstructure_regime_filter_v1_20260803_aef_24h`, plan hash `57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b`, отдельно одобрена пользователем. PIT `PIT_UNIVERSE_V2_FORWARD` продолжается как независимый 20-минутный shadow-track. Разовое 24-часовое окно Dense WS является только exact hash-bound исключением из старого общего лимита трёх часов и не разрешает другие длинные запуски. Authoritative runtime control: `docs/plans/trading-mvp-autopilot-policy-v1.json` и `tools/check_trading_mvp_autopilot.ps1 -Json`. Evaluator semantics/runtime всё ещё требуют отдельного точного разрешения; этот checkpoint не блокирует уже одобренные PIT, campaign quality и causal materialization.

> **Активный спринт с 2026-07-15:** [One-Week Historical Edge Sprint](./2026-07-15-trading-mvp-one-week-historical-edge-sprint.md), продолженный [контрактом v2](./2026-07-16-trading-mvp-one-week-historical-edge-sprint-v2.md). V1 закрыт как `INSUFFICIENT_DATA` из-за retention Gate. V2 `cross_venue_perp_basis_convergence_1h_v2` завершил public collect `120/120`, но закрыт до OOS как `INSUFFICIENT_EXECUTABLE_UNIVERSE`: frozen train-liquidity gate прошли `5/8` активов. OOS, returns и PnL не читались; grid, retune, probe, paper и live запрещены для обеих frozen-веток. Terminal verdict внесён append-only в experiment ledger. PIT membership-drift остаётся отдельным shadow-track: один утверждённый видимый 20-минутный сегмент на новую дату до train gate `20/20`.

---

## 1. Каноническая формулировка цели

Реализовать и провести доказательный цикл **trading_mvp Fast-First**: найти либо честно отвергнуть non-Binance edge (MEXC/Gate) с положительным net expectancy после базовых издержек — на заранее замороженных гипотезах и существующих данных; применять chronological OOS, walk-forward, stress, concentration, execution-capacity и paper-forward ворота; запретить grid/ретюнинг и скрытые/длительные прогоны; ограничить дневные запуски 3 часами, а работу, обоснованно требующую больше, откладывать в ночное окно 23:00–07:00 (Europe/Volgograd) и использовать это окно полностью при наличии утверждённой очереди; допускать live-review только отдельным решением пользователя после успешного paper-forward.

Формула для исполнителя: **минимизировать время от данных до честного вердикта и от принятого вердикта до контролируемого live. Прибыльность — выход ворот, не входная декларация.** Высокий win rate — только диагностика; он не компенсирует отрицательные expectancy, PF, stress PnL или концентрацию.

## 2. Миссия-рамка (постоянный слой, не зависит от исхода текущего трека)

Проект строится как **автономная доказательная торговая фабрика**:

- **живая** — сенсорный слой 24/7 (weekly funding forward работает; PIT/listing — по ночной программе) с heartbeat, self-monitoring, durable-протоколами;
- **работоспособная** — исправленные симуляторы (H1–H9), детерминированные hash-bound evaluator'ы, fail-closed оркестрация;
- **автономная** — цикл «данные → замороженная гипотеза → вердикт → ledger» без ручных шагов; человек — ровно на двух решениях: активация live и лимиты капитала (+ утверждение ночных расписаний);
- **следящая за трендами** — сенсоры режимов и событий: funding-режимы, листинги/делистинги, волатильность/ликвидность, новые контракты, PIT-составы universe;
- **самообучаемая** — банк пре-регистрированных гипотез: при созревании новых данных гипотезы, замороженные ДО этих данных, тестируются автоматически по frozen-протоколу; drift-мониторинг и авто-отзыв стратегий в paper при деградации. Самообучение = автоматизация research-цикла, НЕ онлайн-подгонка на живых деньгах;
- **прибыльная** — через лестницу `ACCEPT_FOR_SHORT_EXECUTION_PROBE → PAPER_READY → LIVE_REVIEW_ELIGIBLE → live с микро-капиталом`, и нигде раньше.

## 3. Исходное состояние (на 2026-07-14 14:47)

- Принятой стратегии нет. Закрыты: funding/carry, listing-event, slow-liquidity, residual dispersion (v2), lottery_max (v3), cross-venue ветки, momentum (до PIT), sweep/reversal.
- **v4** `funding_pressure_reversal_v1` — `INSUFFICIENT_DATA` (18/20 OOS-событий, price-only PnL отрицательный). **v5** `wick_rejection_reversal_v1` — `INSUFFICIENT_DATA` (0 OOS-событий). Обе закрыты, ретюнинг запрещён.
- **v6** `weekend_liquidity_window_v1` заморожена (PlanOnly) — **последний слот текущего трека**; evaluator ещё не построен.
- Все три гипотезы — на одном input Merkle (одни существующие daily-данные).
- Simulator findings H1–H9 исправлены; durable-коллектор проверен боем (72ч = 24 сегмента, 76.0M событий, с ~7.9ч межсегментных разрывов — НЕ непрерывный интервал).

## 4. Протокол гипотез (frozen, no-grid) — обязательные правила

1. **Один frozen configuration на гипотезу.** Grid search, OOS-tuning, TP/SL search, post-hoc пороги — запрещены. Train — только для заранее описанной стандартизации.
2. **One-way порядок**: текст гипотезы и PlanOnly замораживаются и хэшируются ДО любых вычислений по ним; правка после просмотра любого расчёта = новая гипотеза = новая запись реестра.
3. **Feasibility gate (до OOS)**: после заморозки вычисляется детерминированный прогноз OOS-событий; если консервативная нижняя граница (90% CI по train fill-rate) ниже порогов ворот — вердикт `INFEASIBLE_ON_CURRENT_DATA`: OOS не запускается, гипотеза уходит в банк с пометкой data-требований, слот трека не сжигается. Ограничения: эстиматор замораживается один раз на весь трек до первой гипотезы и входит в hash-bound evaluator; **максимум 2 INFEASIBLE на трек, третий сжигает слот**; прогноз прошёл, а OOS не добрал событий → `INSUFFICIENT_DATA` сжигает слот; ретро-переклассификация прошлых вердиктов запрещена.
4. **Бюджеты multiplicity**: ≤3 замороженных гипотез с OOS-оценкой на один input Merkle root (текущие данные исчерпаны: v4, v5, v6); ≤3 Fast-First треков на проект. «Новые данные» = новый ТИП данных (WS/PIT/listing) или существенная дельта, сертифицированная diff'ом Merkle.
5. **Определение события** фиксируется на уровне трека (связанные срабатывания одного дня = 1 событие); связывающее ограничение — уникальные даты.
6. OOS читается только после plan hash, input Merkle и evaluator readiness; два deterministic repeat, совпадение result hash обязательно.
7. Закрытые ветки не переоткрываются на тех же данных. Гипотезы банка, замороженные ДО сбора forward-данных, можно тестировать на этих данных (чистый pre-registration); сочинять/править гипотезы ПОСЛЕ аналитического просмотра forward-данных — запрещено.

## 5. Ворота приёмки (historical, числа обязательны)

- Input hashes match; OOS closed days ≥60; OOS portfolio events ≥20 total и ≥10 на venue; уникальных OOS-дат ≥10.
- Price-only expectancy >0 на обеих venue; combined price-only PF ≥1.2; positive event rate ≥60%.
- Walk-forward: 5 anchored 20-day folds без refit; combined ≥4/5 положительных, per-venue ≥3/5.
- Normal и robustness price-only PnL положительные; stress price-only PnL неотрицательный (в stress благоприятный funding обнуляется, неблагоприятный сохраняется).
- Max drawdown ≤10% peak allocated collateral; single event ≤25% положительного PnL; single base ≤25%; single venue ≤75%.
- Break-even holding ≤3 дней; capacity ≥$500 на ногу.
- Максимальный historical вердикт (из-за survivorship текущего universe): `ACCEPT_FOR_SHORT_EXECUTION_PROBE` — не выше.

Verdict-машина: `INFEASIBLE_ON_CURRENT_DATA` (до OOS) | `INSUFFICIENT_DATA` | `REJECT` | `ACCEPT_FOR_SHORT_EXECUTION_PROBE` | `PAPER_READY` | `LIVE_REVIEW_ELIGIBLE`. У каждого вердикта — единственный разрешённый следующий маршрут, зафиксированный в отчёте.

## 6. Экономика (единственный источник — `costs.py::base_api_cost_profile()`)

| Venue | Market | Maker | Taker | Политика |
|---|---|---:|---:|---|
| MEXC | Spot | 10 bps | 10 bps | консервативная неподтверждённая |
| MEXC | Perp API | 6 bps | 8 bps | официальный API-schedule с 2026-06-01 |
| Gate | Spot | 10 bps | 10 bps | base/VIP0 floor |
| Gate | Perp | 10 bps | 10 bps | base/VIP0 floor; rebates игнорируются |

Каждый цикл учитывает: все entry/exit orders, maker fill probability + taker fallback, спред, impact, slippage, буферы, funding отдельно от price alpha. Неподтверждённая скидка не может оживить отклонённую стратегию; fee evidence может только повышать консервативную точность.

## 7. Время и запуски

- **День (07:00–23:00)**: максимум 10,800 сек на запуск; по умолчанию ≤1,200; historical evaluation ≤1,800; probe ≤1,200. Всё — в видимом терминале с monitor (stage, progress, ETA, rows, last write, ошибки).
- **Ночь (23:00–07:00)**: до 28,800 сек; старт не раньше 23:00, hard-deadline 07:00 на уровне коллектора; frozen config, точный deadline, stop conditions, видимый monitor, durable-протокол, disk guard. Окно используется ПОЛНОСТЬЮ при непустой утверждённой очереди — но окно есть верхний лимит, а не норматив: добивать часы бессмысленной работой запрещено.
- Запрещены всегда: скрытый `Start-Process`, blind background, auto-resume упавшего рана без человека, частичные метрики как результат. Timeout/сеть → `STOPPED_INCOMPLETE`. Resume — только тот же `run_id`, matching hashes, явный видимый запуск.

## 8. Ночная data-программа

Механизм: Codex готовит конкретные frozen collect-планы (объём, символы, deadline, guards) → **пользователь явно утверждает расписание на срок ≤2 недель** → исполнение по ночам → продление только новым явным утверждением. Общие слова («продолжи», «давай») расписание не утверждают.

Очередь приоритетов первого расписания: (1) PIT-universe v2 forward (по исправленному контракту), (2) dense WS сегментированные сборы, (3) listing forward monitoring (после data-quality исторического сбора), (4) углубление funding-history.

**Data embargo**: до окончания сбора и заморозки очередных гипотез forward-данные доступны только для технического мониторинга (объёмы, ошибки, запись); аналитический просмотр (доходности, сигналы, паттерны) запрещён — иначе «замороженные» гипотезы следующего трека сочинены после подглядывания в собственный OOS.

Журнал ночей: дата, план, выполнено/сорвано.

## 9. Confirmation policy (действующая, §20 операционного контракта)

Короткие детерминированные owned no-grid шаги (OOS/evaluation/postprocess/report по уже замороженному PlanOnly, существующие локальные данные, видимый запуск, ≤1,800 сек, gate не RUNNING, без collector/grid/retune/paper/live/API) выполняются без отдельной фразы «подтверждаю»; «продолжи»/«что дальше»/«погнали» — достаточное разрешение. Отдельное явное подтверждение обязательно: collectors, public/execution probes, grid, paper-forward, ночные/длительные (>1,800 сек) раны, live/API keys, leverage/margin.

## 10. Paper-forward и границы live

- Probe: 20 минут, ≥180 валидных снапшотов, coverage ≥80%, p95 impact ≤10 bps на $500/ногу; провал = `REJECT_EXECUTION` без права снизить capacity post-hoc.
- Paper-forward: короткие сегменты ≤20 минут вокруг событий; atomic state; ≥15 завершённых portfolio-наблюдений; paper net expectancy >0, PF ≥1.2, stress reconciliation неотрицателен; ≤1 data-quality/kill-switch инцидента.
- `LIVE_REVIEW_ELIGIBLE` не запускает торговлю. Live требует отдельного документа и отдельного решения пользователя: юрисдикция/withdrawal проверены пользователем; API-key без withdrawal, IP allowlist, отдельный subaccount; секреты вне git/logs/JSON/history; frozen max-risk per position, daily loss limit, kill switch; venue exposure limit; протестированные reconciliation и emergency cancel; **начальный капитал и допустимый убыток утверждает только пользователь**. До этого — research/paper-only.

## 11. Инварианты (не оптимизируются исполнителем)

1. Ворота не ослабляются; пороги не меняются после просмотра OOS.
2. Live включает только пользователь; лимиты капитала задаёт пользователь.
3. Rejected/closed ветки не ретюнятся на тех же данных.
4. Нет скрытых прогонов; каждый ран владеет manifest'ом и heartbeat'ом.
5. Ledger/registry append-only; ошибки правятся reconciliation-записью, история не переписывается.
6. Каждый final artifact: hypothesis id, frozen params, plan hash + SHA-256, input hashes + Merkle, fee provenance, версии runtime, git HEAD, split/folds, метрики normal/robustness/stress, sample/concentration, deterministic result hash, вердикт с причинами, единственная следующая команда.

## 12. Метрики успеха исполнителя (процессные)

- Медианное время «данные готовы → вердикт»;
- выполнение утверждённых ночных планов в срок (не «% занятости окна»);
- uptime/coverage/freshness сенсоров;
- полнота ledger/provenance (0 записей без hash'ей);
- 0 нарушений инвариантов;
- калибровка feasibility gate (предсказанные vs фактические INSUFFICIENT).

Прибыль не является метрикой исполнителя до live; в live единственная прибыле-метрика — consistency live vs paper.

## 13. Запрещённая работа (вне явного решения пользователя)

Новые длинные collectors вне утверждённого ночного расписания; повтор отклонённого PIT-рана v1; grid-search; retune закрытых веток; live/API интеграция; новые signal-families сверх бюджетов §4; косметический рефакторинг вне critical path; анализ новых видео/каналов; установка новых skills/plugins/MCP без конкретного блокера.

## 14. Финал проекта (терминальные состояния обязательны)

**Успех**: стратегия проходит `ACCEPT_FOR_SHORT_EXECUTION_PROBE → PAPER_READY → LIVE_REVIEW_ELIGIBLE`, пользователь отдельно включает live с микро-капиталом, live держит consistency с paper.

**Честный негатив текущего трека**: исчерпание слотов → `NO_FAST_EDGE_ON_CURRENT_DAILY_DATA` (квалифицированный, не глобальный). Развилка (выбирает ТОЛЬКО пользователь; заранее описанная ветка — не предавторизация): (α) новый трек на данных нового типа из ночной программы — по банку замороженных гипотез; (β) sunset-ревью. **Default-to-sunset**: если и трек на новых данных завершается NO_FAST_EDGE — β становится выбором по умолчанию; для продолжения нужен явный аргументированный запрос пользователя.

Непроверяемые состояния («почти нашли», «ещё чуть-чуть») исходами не являются.

## 15. Первые шаги после принятия этого документа

1. **v6: применить feasibility gate ДО построения/запуска OOS** — заморозить эстиматор по правилам §4.3 и посчитать прогноз (по прикидке OOS даст ~16–18 событий против порога 20 — есть шанс сохранить последний слот трека).
2. Подготовить пользователю первое ночное расписание (≤2 недель) на явное утверждение.
3. Продолжать weekly funding forward без изменений.
4. Вести банк гипотез: новые идеи замораживаются с data-требованиями и ждут своих данных — не жгут слоты.
---

## 16. Reconciliation после принятия цели Codex

Дата фиксации: 2026-07-14 15:43 Europe/Volgograd.

Этот документ принят как текущая рабочая цель из вложения пользователя `C:\Users\koval\.codex\attachments\7f46de99-7d6d-4edb-9223-043cc68e31c6\pasted-text.txt`. При конфликте со старыми `current-goal`, handoff, agent-log или отдельными сообщениями использовать эту версию, правила `AGENTS.md`, Visible Run Rule и Active Run Gate Rule.

Фактическая поправка к разделу 3/15: после создания исходного текста v6 уже был реализован, проверен и закрыт. Поэтому пункт `v6: применить feasibility gate ДО построения/запуска OOS` считается историческим и не является следующим действием.

Текущее состояние:

- v4 `funding_pressure_reversal_v1`: `INSUFFICIENT_DATA`, закрыта, ретюнинг запрещен.
- v5 `wick_rejection_reversal_v1`: `INSUFFICIENT_DATA`, закрыта, ретюнинг запрещен.
- v6 `weekend_liquidity_window_v1`: `INSUFFICIENT_DATA`, закрыта, ретюнинг запрещен.
- текущий daily-data Fast-First track: `NO_FAST_EDGE_ON_CURRENT_DAILY_DATA` / `NO_FAST_EDGE_FOUND` для существующего input Merkle.
- execution probe, paper-forward, live/API keys, leverage/margin, grid/search и retune не разрешены.

Следующий разрешенный рабочий маршрут без запуска collector/grid/probe/OOS: подготовить новый data-track contract, feasibility-estimator contract, банк pre-registered гипотез и ночное расписание proposal. Actual collectors/probes/night runs требуют явного утверждения пользователя по разделам 7-9.

## 17. Технический прогресс нового data-track

Дата фиксации: 2026-07-14 15:58 Europe/Volgograd.

- `feasibility-gate-v1` реализован fail-closed.
- Генератор immutable data-track PlanOnly-контрактов реализован и подключен как `fast-edge-data-track-plan`.
- Контракт не читает OOS/returns/PnL и не запускает сеть или collector; его единственный следующий маршрут — feasibility gate.
- Диагностический fixture smoke не открывает реальный PIT/WS/listing/funding track и не разрешает OOS.
- Новый data track, collector, public/execution probe, ночное расписание и OOS по реальным новым данным по-прежнему требуют условий и разрешений разделов 7-9.

## 18. Frozen PIT-universe v2 schedule

Дата фиксации: 2026-07-14 18:48 Europe/Volgograd.

- Первый banked data-track: `pit_universe_membership_drift_reversion_v1` / `PIT_UNIVERSE_V2_FORWARD`.
- Финальный PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_184844.json`.
- Plan hash: `2c484b7b2cbb94ee94f87b8ae65519501d812647ef4848219abc4bf01dff1c45`; file SHA-256: `5459ce95dfe4f13c816d83b7cd947a2282fda00759c7abd4e1700e8f1e27e0a0`.
- Полный hypothesis contract заморожен до forward-данных: contract hash `93895bd0f765d37c3bc78e206749a81ba5b6ec9287cde427233b237559bc4db9`; bank SHA-256 `8c1abf5bf5662ff29e3b422052bb101c6186f5fb7040253bd4b13555a5bea539`.
- 14 ночей по 1 200 секунд, 4 ожидаемых цикла за ночь, visible terminal, E:-storage, 5 GiB disk guard, hard deadline 07:00.
- Runtime hashes wrapper/collector/approval/status/quality/evaluator/hypothesis-validator/costs/feasibility, execution-config и immutable quality policy входят в sealed schedule.
- Двойная validation дала идентичный `VALID`; fast shard `217 OK`, полный regression `642 OK`, `5 skipped`.
- Рой дал содержательный verdict `approve`, но workflow не продвинулся из-за повторного format-gate `workflow_snapshot`; checkpoint зафиксирован как `swarm_limited`, вывод перепроверен Codex по исходникам.
- Этот транш даёт максимум 14 уникальных дат при минимуме 80: 20 technical-train + 60 untouched OOS. Он не является доказательством edge и не разрешает OOS.
- Текущее состояние: `schedule_approved=false`, `collection_started=false`. Следующий шаг требует точной явной фразы утверждения из schedule proposal.
- PlanOnly `20260714_174224` / `bce81a343434bc16c5f85c64ad63825a88ff7964567662565e040d4382eb43ac` и `20260714_182041` / `8fa86b77fc74db86193f304068c8f6885a3aaa9752eeeaadd132a284f118dcaa` superseded; старые approval phrase использовать нельзя. План `182041` fail-closed отвергается по hypothesis-bank provenance mismatch.

## 19. Embargo-safe night journal

Дата фиксации: 2026-07-14 18:04 Europe/Volgograd.

- Реализован `fast-edge-night-schedule-status`, который читает только frozen plan, immutable approval, manifest и collector lock metadata.
- Статусы ночей: `PLANNED`, `DUE`, `RUNNING`, `COMPLETED`, `STOPPED_INCOMPLETE`, `MISSED`, `INVALID`.
- `RUNNING` требует живого lock owner; stale manifest fail-closed становится `STOPPED_INCOMPLETE`.
- Реальный pre-approval status: `14 PLANNED`, collector не запущен, market rows/returns/PnL не читались.
- Technical completion не считается data-quality certification; status всегда оставляет `quality_certified_dates=0` и `oos_allowed=false`.
- Проверки: targeted 29 + 18, новые status tests 8/8, полный regression 628 OK, 5 skipped.

## 20. Hash-bound PIT quality certification

Дата фиксации: 2026-07-14 18:49 Europe/Volgograd.

- Реализован `fast-edge-night-schedule-quality` и append-only JSONL ledger для сертификации сегментов между отдельными утверждёнными траншами.
- Policy `pit_universe_v2_segment_quality_v1` заморожена до market collection: `min_exchanges_per_cycle=2`, `max_error_cycle_ratio=0.05`, `max_duplicate_snapshot_keys=0`, fail при любом thin-exchange cycle, `max_clock_skew_sec=60`, минимум 80 distinct accepted dates.
- Certifier сначала проверяет plan/approval/manifest hashes и approved night window; при отсутствии approval не читает market rows и не пишет ledger.
- Повторная сертификация неизменного сегмента идемпотентна; несовместимое доказательство для существующего `run_id` считается tampering и fail-closed.
- Quality minimum не разрешает OOS автоматически: следующий маршрут только feasibility evaluation уже замороженного contract; OOS разрешается лишь после положительного feasibility verdict.
- Pre-approval status нового плана: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`, `14 PLANNED`, `0 manifests`, `collection_started=false`, `market_rows_read=false`, `returns_read=false`, `pnl_read=false`.
- Текущий pre-approval status: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_status_20260714_184934.json`.
- Проверки: fast shard `217 OK`, full regression `642 OK`, `5 skipped`; двойная hash-bound validation `VALID`.

## 21. Evaluator-first PIT contract and current schedule

Дата фиксации: 2026-07-14 19:32 Europe/Volgograd.

- Каноническая цель: `docs/plans/2026-07-14-trading-mvp-canonical-goal-v3.md`; SHA-256 `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`. Этот файл не изменяется операционными checkpoint-записями.
- До market collection реализован и заморожен hash-bound no-grid evaluator `pit_universe_membership_drift_reversion_v1.1.0`.
- Текущий hypothesis contract hash: `e0d5057dd58ca3399169c3f74fdf11faf4d8909d44798de9749cd8c0ab29fa07`; evaluator SHA-256: `a0f2f6c2eed4c39eb20261689db7cb5338349047cf5cf967b4e5a2a1ca9ef07c`.
- Sample gate усилен до 120 quality-certified dates: 20 technical-train dates + 100 untouched OOS dates. Walk-forward использует пять непересекающихся 20-дневных OOS folds.
- `fast-edge-pit-input-plan` строит immutable input plan; `fast-edge-pit-feasibility` читает только train; `fast-edge-pit-evaluate` допускается только после hash-bound `FEASIBLE_FOR_OOS` и выполняет два детерминированных повтора без grid/retune.
- Реализованы normal/robustness/stress economics, segment-boundary protection, 30-day global event dedup, Wilson lower bounds, drawdown/concentration/capacity checks и fail-closed provenance validation.
- Старый schedule `20260714_184844`, plan hash `2c484b7b...`, стал недействителен после изменения hypothesis bank/contract и считается superseded; его approval phrase использовать нельзя.
- Текущий PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_193046.json`.
- Текущий plan hash: `b5ad5616983a9c807b9159067294045f7ca87f27dab343b39f0b91572d2a9c58`; file SHA-256: `896be70801de4e81db4fabd90ed676285e042a64c382ab000f2bb9f88486f6b8`.
- Текущий статус: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`; `schedule_approved=false`, `collection_started=false`, `network_access=false`, `oos_returns_read=false`.
- Один 14-дневный транш дает максимум 14 из необходимых 120 дат. Он является только накоплением forward evidence и не разрешает feasibility/OOS сам по себе.
- Проверки: полный regression `654 OK`, `5 skipped`; Python compile, PowerShell parse и `git diff --check` прошли.

## 22. Staged PIT proof pipeline v1.2.0

Дата фиксации: 2026-07-14 20:32 Europe/Volgograd.

Этот раздел заменяет операционные значения разделов 18-21 там, где они расходятся. Канонический файл цели не изменён и по-прежнему byte-identical исходному вложению пользователя.

- Frozen contract: `pit_universe_membership_drift_reversion_v1.2.0`, contract hash `178f63b1585569538d180f6fc2fa7d570f060fdcc292a107c7cd30656a6eb595`.
- Наблюдение теперь формируется по quality-certified local dates из двух последних согласованных циклов каждой ночи. Пропуск календарной даты разрывает event/position sequence; события могут продолжаться только по последовательным сертифицированным датам.
- Execution PnL считается по исполняемым BBO: long entry ask/exit bid и short entry bid/exit ask. BBO spread уже встроен в цены и повторно не вычитается. Normal all-in ceiling равен `98 bps`, stress ceiling - `160 bps`.
- Break-even holding измеряет первую дату, на которой cumulative net PnL стал неотрицательным, а не финальную длительность удержания.
- Public snapshot contract дополнен funding, mark/index, contract multiplier, order limits, tick/step и BBO sizes; hash public-probe client входит в schedule seal.
- Proof pipeline разделён на два неизменяемых плана. `train_feasibility` использует только первые 20 accepted dates и не содержит OOS rows. `full_evaluation` на 20 train + 100 untouched OOS dates разрешён только после hash-valid `FEASIBLE_FOR_OOS`.
- Quality policy `pit_universe_v2_segment_quality_v2` обязана остановить дальнейшее накопление на 20 train dates и отправить данные в train-only feasibility. Сбор дополнительных 100 OOS dates до положительного feasibility запрещён.
- Финальный unapproved PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_203246.json`.
- Plan hash: `7212be6dc9adc25916ace8fe3c2987df303a049b849dce76a0ccf24f765325e5`; file SHA-256: `abbc2579480a4e9e17cd3e2c4c1cdd9e1e14f2e0a3b3a1b2d10326aa7ee33314`.
- Текущий статус: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`; 14 segments planned, zero completed, `schedule_approved=false`, `collection_started=false`.
- Все прежние schedule hashes, включая `b5ad5616...`, являются superseded и не должны утверждаться или запускаться.
- Проверки: полный regression `657 OK`, `5 skipped`; Python compile, PowerShell parser, `git diff --check` и две независимые hash-bound validation текущего schedule прошли.
- Никакой collector, network request, OOS read, grid, probe, paper-forward, live order или API-key action при этой фиксации не запускался.

## 23. Enforced collection-stage gate

Дата фиксации: 2026-07-14 21:09 Europe/Volgograd.

Этот раздел заменяет операционные значения schedule из раздела 22. Каноническая цель и frozen hypothesis contract `v1.2.0` не изменены.

- Schedule schema повышена до `fast_first_night_schedule_plan_v2` и теперь явно фиксирует `train_accrual` либо `oos_accrual`.
- План включает точный путь append-only quality ledger, снимок уже принятых сертификаций, stage target и максимум новых accepted dates. Планировщик также запечатывает SHA-256 собственного исходника.
- Перед утверждением и перед каждым segment wrapper вызывает `authorize-segment`. `train_accrual` fail-closed блокируется при достижении 20 accepted dates; создать `oos_accrual` без hash-valid train plan и `FEASIBLE_FOR_OOS` невозможно.
- Quality certifier принимает только ledger path, запечатанный в schedule. Append-only рост ledger разрешён, изменение или исчезновение исходных сертификаций считается tampering.
- Текущий immutable PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_210928.json`.
- Plan hash: `b53c4b9e8049694c992178664da85e650ecfe9f1bcfd314d7957862e7e4fef51`; file SHA-256: `26046d62fddd007b8e6e361beca7285df5af042312c4c7cd62d4b7f6b4f477a8`.
- Stage: `train_accrual`; sealed ledger: `E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl`; accepted dates `0/20`; 14 visible 20-minute segments; статус `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`.
- Первый segment отдельно проверен как `AUTHORIZED` при remaining `20`. Старый plan `7212be6d...` fail-closed отклоняется валидатором v2 и не может быть утверждён или запущен.
- Проверки: полный regression `662 OK`, `5 skipped`; Python compile, PowerShell parser, `git diff --check`, две независимые validation текущего plan и fail-closed проверка старого plan прошли.
- Никакой collector, network request, OOS read/evaluation, grid, probe, paper-forward, live order или API-key action не запускался. Цель остаётся активной; ближайшая market-writing граница требует точной явной фразы из текущего schedule.

## 24. Executable capacity gate v1.3.0 and current schedule

Дата фиксации: 2026-07-14 22:06 Europe/Volgograd.

- Каноническая цель не изменена: `docs/plans/2026-07-14-trading-mvp-canonical-goal-v3.md`, SHA-256 `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.
- Frozen contract повышен до `pit_universe_membership_drift_reversion_v1.3.0`, hash `b5e3abd4942fc117b92c324e931d8d91671df3de99b403875bcf38983c26d857`.
- Capacity больше не оценивается через долю 24h volume. Каждый event требует минимум `$500` реального L1 quantity на обеих ногах при входе и выходе; используется минимум четырех исполнимых BBO-capacity значений.
- Collector получает MEXC L1 depth для dual-venue non-Binance bases, сохраняет depth coverage/errors в cycle journal и manifest; Gate quantity берется из публичного ticker. Quality policy `pit_universe_v2_segment_quality_v3` требует минимум 95% dual-venue BBO-size coverage. MEXC depth enrichment ограничен 120 секундами на cycle и fail-closed при исчерпании бюджета; cadence считается start-to-start, чтобы runtime запросов не растягивал 5-минутный интервал.
- Train-feasibility больше не ведет напрямую к OOS: положительный результат разрешает только отдельный `oos_accrual PlanOnly`. `next_allowed_command` присутствует в планах/результатах и проверяется против подмены.
- Текущий unapproved PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_220219.json`.
- Plan hash `34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362`; file SHA-256 `b1d4264fc577dd84464389b151361bcdfd42a13d56bb67390fc75b516b0071f2`.
- Статус: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`, 14 `PLANNED`, accepted `0/20`, collection/network/OOS/grid/probe/paper/live/API не запускались.
- Планы `b53c4b9e...` и `29d02a46...` superseded; последний fail-closed по collector provenance после введения runtime budget/cadence.
- Verification: 671 tests passed, 5 skipped; targeted tests 97/97; Python compile, PowerShell parser, `git diff --check`, two schedule validations and first-segment stage authorization passed.

## 25. Approved train accrual and segment n01

Дата фиксации: 2026-07-14 23:24 Europe/Volgograd.

- Пользователь дословно утвердил schedule `34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362`; immutable approval SHA-256 `e0d8fffa881056927209ebba904387215e4d315bcf6d7a929860019d804676a4`, expires `2026-07-28T07:00:00+03:00`.
- `pit_universe_v2_forward_20260714_n01` выполнен в подтвержденном видимом Windows Terminal с `23:00:08` до `23:20:09`: `4` cycles, `6,788` rows, `0` errors, `stop_condition=duration_sec`, manifest SHA-256 `c382adb86953a0515d20c66f5ab5d599a8ac773afde6795058dc8a0dcfb053b1`.
- Во всех четырех cycles присутствовали MEXC и Gate; MEXC L1 depth completion был `208/208`, coverage `1.0`, depth errors `0`.
- Hash-bound quality decision `PARTIAL_PIT_QUALITY_CERTIFIED`: evaluated `1`, accepted `1`, rejected `0`; certification id `13bb63cb6f0169fcfffa94b5650ef7ea95db3931d098662fb873e1a478e3ed91`.
- Quality report: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\pit_universe_v2_quality_report_20260714_n01.json`, SHA-256 `714adf386c8749d5d795bb47e042603ce439dba0f3d149833ed15e80c4407727`.
- Append-only ledger теперь содержит `1/20` accepted train dates; train feasibility остается закрыт. Returns/PnL/OOS/grid/probe/paper/live/API keys не читались и не запускались.
- Heartbeat `pit-visible-night-segments` выполняет один scheduler checkpoint в `22:59`: сначала сертифицирует предыдущий completed segment, затем запускает только ближайший утвержденный segment в новом видимом Windows Terminal. Duplicate launch и auto-resume запрещены.
- Следующий разрешенный market-writing шаг: `pit_universe_v2_forward_20260715_n02`, окно `2026-07-15T23:00:00+03:00..23:20:00+03:00`.

## 26. Supplemental 3h PIT segment and duplicate-date guard

Дата фиксации: 2026-07-15 04:40 Europe/Volgograd.

- Пользователь отдельно разрешил непрерывную работу до `09:00`; supplemental PlanOnly `155d211ccf002cd607f0644122b54b2dcbe6b4e1d81d92` был выполнен только как видимый train-accrual segment, без OOS/grid/live/API keys.
- `pit_universe_v2_forward_20260715_n01` завершен по `duration_sec=10800`: `36/36` cycles, `61,092` rows, `0` errors, MEXC/Gate во всех cycles, MEXC L1 depth coverage `1.0`, depth errors `0`.
- Hash-bound quality report `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\pit_universe_v2_quality_report_20260715_n01.json` имеет решение `PARTIAL_PIT_QUALITY_CERTIFIED`; certification id `a2edc63bca8ee8efab732be8c2c54ce01384aafdc415fb77d00ac373c4b3ae42`.
- Append-only ledger содержит `2/20` distinct accepted train dates. Returns/PnL/OOS не читались; frozen train feasibility остается закрыт до `20/20`.
- `tools/check_active_run_gate.ps1` исправлен: PIT cycles, duration и ETA вычисляются по manifest-native `duration_sec`, `interval_sec`, `elapsed_active_sec`, `cycle_count`, а не по stale gate metadata. Regression/PowerShell tooling verification: `33 OK`.
- Запланированный `pit_universe_v2_forward_20260715_n02` не несет новой distinct-date evidence и fail-closed отклоняется `authorize-segment`; heartbeat теперь пропускает его как `SKIP_DUPLICATE_CERTIFIED_DATE` без запуска терминала/collector.
- Следующий полезный sealed segment: `pit_universe_v2_forward_20260716_n03`, окно `2026-07-16T23:00:00+03:00..23:20:00+03:00`. Повторный сбор до `09:00` на уже принятой дате не разрешен, потому что не меняет proof count.

## 27. Train horizon completion PlanOnly and approval pointer restore

Дата фиксации: 2026-07-15 05:05 Europe/Volgograd.

- Аудит календарного покрытия показал: active approved schedule `34363aef...` заканчивается `2026-07-27` и дает максимум `14/20` train dates; для достижения frozen feasibility gate не хватало шести distinct дат.
- Создан отдельный immutable extension PlanOnly `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_extension_planonly_20260715_0448.json`: `2026-07-28..2026-08-02`, 6 visible 20-minute segments, plan hash `d35b65a7415cb37e0fcf6216abc77a204640ba749e19617c355ec43e93570583`, file SHA-256 `edea8e1112e807a4f7203362ee545f70c8c7c795d1d6e22348a446f32b52edfd`.
- Extension status `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`; он не утвержден и не заменяет текущий schedule. Его можно утверждать только отдельной явной командой после завершения active schedule.
- Coverage bridge `pit_universe_v2_train_schedule_bridge_planonly_20260715_0451.json`, SHA-256 `61e7c3694d53319803a572ae56c043e6d04e1ae4f3e207bc1fb4f4bc2b15b1f9`, фиксирует условный путь `2/20 -> 14/20 -> 20/20` при quality acceptance будущих дат.
- Обнаружено, что supplemental run оставил в active gate свой approval pointer `155d211c...`, несовместимый с heartbeat основного schedule. Добавлен fail-closed `tools/restore_trading_night_schedule_pointer.ps1` и восстановлен исходный immutable user approval `34363aef...` без изменения approval record и без запуска collector.
- Restore audit: `docs/agent-log/2026-07-15-0458-pit-night-schedule-pointer-restore.json`, SHA-256 `4dd1fcfff57597c72262afc92a2ecdcd7d811c2991d73b24b1b5d3d1be41835d`; immutable approval SHA-256 остался `e0d8fffa881056927209ebba904387215e4d315bcf6d7a929860019d804676a4`.
- Heartbeat теперь может восстановить pointer только из существующего hash-valid approval после completed supplemental run; новое approval, auto-resume или hidden collector он не создает.
- Verification: pointer restore `3 OK`, schedule/gate shard `66 OK`, full regression `675 OK`, `5 skipped`; PowerShell parse и diff-check прошли.
- Следующий полезный segment остается `pit_universe_v2_forward_20260716_n03`. До `20/20` запрещены feasibility/OOS/grid/probe/paper/live/API keys; market rows/returns/PnL в этом checkpoint не читались.

## 28. Owned visible transition at the 20-date train gate

Дата фиксации: 2026-07-15 05:31 Europe/Volgograd.

- Добавлен `tools/run_pit_train_feasibility_visible.ps1`: bounded owned-run wrapper для единственного перехода `20/20 accepted train dates -> immutable train-only input plan -> two deterministic feasibility repeats`.
- Wrapper запускается только в видимом PowerShell, ограничен `MaxRuntimeSec<=1800`, использует ownership token/launch record, не перезаписывает immutable outputs и fail-closed переводит gate в `STOPPED_INCOMPLETE` при timeout либо nonzero worker exit.
- `trading_mvp/run_mvp.ps1` разрешает `fast-edge-pit-input-plan` и `fast-edge-pit-feasibility` при `RUNNING` только когда `RunId` совпадает с owned visible gate и `next_goal_decision=PIT_TRAIN_FEASIBILITY_RUNNING`. Другие действия этим исключением не открываются.
- Перед принятием результата wrapper требует ровно `20` train dates, `0` OOS dates, совпадающие plan/result hashes и verdict двух повторов, `oos_dates_read=0`, `returns_read=false`, `pnl_computed=false`, `network_access=false`, `grid_search=false`, `retune=false`.
- Полный synthetic end-to-end переход на `20/20` доказан через реальный owned worker: immutable train-only plan создан, оба deterministic feasibility запуска дали `FEASIBLE_FOR_OOS` с одинаковым result hash, custom gate закрылся в `READY_FOR_POSTPROCESS`, а реальный project gate остался byte-identical.
- End-to-end fixture обнаружил и закрыл две ошибки orchestration: `plan_stage` читается из `sealed_input.plan_stage`; deterministic repeat выполняется через один canonical output path с безопасной ротацией первого immutable artifact, поскольку output-bound `next_allowed_command` входит в result hash и evaluator запрещает overwrite.
- Heartbeat `pit-visible-night-segments` обновлен: при `<20` продолжает только утвержденный train schedule; при `=20` прекращает collectors и один раз запускает visible train-only feasibility; при `>20` fail-closed останавливается. Даже `FEASIBLE_FOR_OOS` разрешает только отдельный OOS-accrual PlanOnly, но не OOS collection/evaluation.
- Реальный feasibility не запускался: ledger по-прежнему `2/20`. Следующий полезный segment `pit_universe_v2_forward_20260716_n03` повторно подтвержден `AUTHORIZED`; `accepted_distinct_dates_before_run=2`, returns/PnL не читались.
- Verification: wrapper TDD `7 OK`, pipeline/gate shard `79 OK`, full regression `682 OK`, `5 skipped`; PowerShell parser и read-only PlanOnly smoke прошли. Каноническая цель осталась byte-identical, SHA-256 `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.

## 29. Owned OOS transition and full-evaluation readiness

Дата фиксации: 2026-07-15 06:17 Europe/Volgograd.

- Успешный `run_pit_train_feasibility_visible.ps1` теперь автоматически создаёт только immutable 14-night `oos_accrual` PlanOnly, начиная после последней train date. Он сохраняет schedule path/hash/approval phrase, но не утверждает schedule и не запускает collector/OOS evaluation.
- OOS PlanOnly жёстко связан с 20-date train plan и `FEASIBLE_FOR_OOS`; требует `initial_accepted_distinct_dates=20`, `stage_target_distinct_dates=120`, `schedule_approved=false`, `collection_started=false`, `network_access=false`, `oos_returns_read=false`.
- Добавлен `tools/run_pit_full_evaluation_visible.ps1`: будущий bounded owned wrapper для перехода `20 train + 100 untouched OOS -> two external deterministic no-grid evaluations -> immutable verdict manifest`.
- Scoped gate bypass разрешает full-evaluation worker только для `fast-edge-pit-input-plan` и `fast-edge-pit-evaluate`, только при совпадающем `RunId` и `next_goal_decision=PIT_FULL_EVALUATION_RUNNING`. Timeout/nonzero/hash mismatch закрываются `STOPPED_INCOMPLETE`.
- Synthetic end-to-end `20+100` fixture дал два одинаковых result hash и `ACCEPT_FOR_SHORT_EXECUTION_PROBE`, доказав runtime-механику. Это не реальный trading verdict и не разрешение probe: real ledger остаётся `2/20`, OOS rows/PnL реального трека не читались.
- Heartbeat обновлён: при будущем `FEASIBLE_FOR_OOS` он показывает пользователю созданные OOS schedule path/hash/approval phrase и останавливается. Автоматического approval/OOS collect/evaluate нет.
- Verification: train transition `7 OK`, full-evaluation wrapper `5 OK`, combined proof shard `47 OK`, full regression `687 OK`, `5 skipped`, `261.175s`; PowerShell parser, `git diff --check`, canonical goal hash и real active gate прошли.
- Real next market step не изменён: `pit_universe_v2_forward_20260716_n03` остаётся `AUTHORIZED`, `accepted_distinct_dates_before_run=2`, remaining train dates `18`.

## 30. Hash-bound execution-probe readiness

Дата фиксации: 2026-07-15 07:00 Europe/Volgograd.

- Добавлен immutable PlanOnly-контракт будущего public execution probe для единственного реального исторического verdict `ACCEPT_FOR_SHORT_EXECUTION_PROBE`. План привязан к canonical full-evaluation artifact, deterministic result hash, input Merkle, runtime hashes и полному множеству bases из принятого normal OOS без outcome-based top-N отбора.
- Frozen probe contract: `1,200` секунд, интервал `5` секунд, `240` attempts, `$500` на каждую ногу, depth limit `50`, минимум `180` валидных snapshots, coverage `>=0.80`, worst-leg p95 impact `<=10 bps`.
- Offline evaluator считает p95 отдельно для `mexc_buy`, `mexc_sell`, `gateio_buy`, `gateio_sell` и применяет gate к худшей ноге. Дополнительно для каждой candidate base отдельно требуются coverage `>=0.80` и worst `base x venue x side` p95 `<=10 bps`; pooled coverage/p95 не могут скрыть неисполняемую отдельную монету.
- Добавлен resumable append-only collector с public MEXC/Gate REST, atomic manifest, lock, deterministic round-robin и cached contract discovery. Реальный network run допускается только с exact plan hash и явным `-ConfirmedExecutionProbe` в видимом терминале.
- Добавлен `tools/start_pit_membership_drift_execution_probe_visible.ps1`: показывает progress/ETA/valid/error/last-write, ограничивает run до `1,200` секунд плюс shutdown grace, выполняет два offline deterministic evaluation и fail-closed закрывает timeout, nonzero exit либо hash mismatch.
- `tools/run_pit_full_evaluation_visible.ps1` после будущего реального historical ACCEPT автоматически создаёт только immutable execution-probe PlanOnly и approval packet. Он не запускает network probe, paper-forward, live orders или API keys.
- Synthetic `20+100 -> ACCEPT_FOR_SHORT_EXECUTION_PROBE -> probe PlanOnly/evaluate` использован только для проверки tooling. Реального historical ACCEPT и реального execution probe нет; стратегия не принята.
- Реальный append-only quality ledger подтвержден без чтения доходностей: `2` records, `2/20` distinct accepted train dates (`2026-07-14`, `2026-07-15`), `returns_read=false`, `pnl_read=false`.
- Active gate: завершённый `pit_universe_v2_forward_20260715_n01`, `61,092` rows, `36/36` cycles, `0` errors, `final=true`, live processes отсутствуют. Следующий полезный market-writing segment остаётся `pit_universe_v2_forward_20260716_n03`, окно `2026-07-16 23:00-23:20 +03:00`.
- Verification: execution-probe unit `10 OK`, wrapper/full-evaluation targeted `7 OK`, full regression `699 OK`, `5 skipped`, `309.444s`; Python compile и PowerShell AST parse прошли; `git diff --check` не выявил ошибок. Full log: `docs/agent-log/2026-07-15-full-regression-pit-execution-probe-per-base.log`.
- Каноническая цель не изменена; SHA-256 остаётся `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`. До `20/20` запрещены feasibility/OOS/probe/paper/live/API keys; повторный same-day collector не добавляет evidence и не запускается.

## 31. Hash-bound PIT paper-forward state readiness

Дата фиксации: 2026-07-15 07:50 Europe/Volgograd.

- Добавлен `trading_mvp/src/pit_membership_drift_paper_forward.py`: strategy-specific paper-forward PlanOnly, immutable hash-bound approval artifact и deterministic atomic state evaluator. Legacy `fast_edge.py::record_paper_segment` для PIT не используется и ручной PnL запрещен.
- Paper PlanOnly может быть создан только из реального `PAPER_READY` execution-probe evaluation, ровно после 120 sealed historical dates и до появления любого релевантного paper-date ledger entry. План связывает execution/full-plan hashes, input Merkle, cost profile, runtime hashes, последние две historical dates как warmup и append-only ledger byte-prefix.
- Paper state полностью восстанавливается из accepted quality certifications и hash-verified segment artifacts. События до paper boundary исключаются; позиция считается завершенной только при доступных normal, robustness и stress exits, включая позиции через несколько последовательных quality dates.
- Frozen gates: минимум 15 завершенных portfolio observations, net expectancy `>0`, PF `>=1.2`, stress net `>=0`, максимум один quality/kill-switch incident. `PAPER_REJECTED` и `LIVE_REVIEW_ELIGIBLE` терминальны; live не запускается.
- Fail-closed защита покрывает: historical prefix tamper, позднюю заморозку PlanOnly, state hash tamper, ledger shrink/prefix rewrite, изменение ledger во время evaluation и попытку продолжить terminal state.
- В `trading_mvp/run_mvp.ps1` добавлены только offline actions `fast-edge-pit-paper-plan` и `fast-edge-pit-paper-evaluate`, `MaxRuntimeSec<=1800`. Action для approval/start намеренно отсутствует; network, grid, retune, live/API keys не открываются.
- После будущего реального `PAPER_READY` visible execution-probe wrapper автоматически создает и валидирует только immutable `paper-forward-plan.json`, записывает plan hash и exact approval phrase в gate/терминал. Он не создает approval и не запускает paper; scoped gate открывает PlanOnly только owned probe worker.
- Verification: paper-forward `11 OK`; execution probe `10 OK`; visible probe `2 OK`; full-evaluation wrapper `5 OK`; PowerShell tooling `20 OK`; полная регрессия `711 OK`, `5 skipped`, `554.793s`. Python compile, PowerShell AST и `git diff --check` прошли. Протокол: `docs/agent-log/2026-07-15-full-regression-pit-paper-forward.log`.
- Реальный статус не изменен: quality ledger `2/20` (`2026-07-14`, `2026-07-15`), returns/PnL не читались, реального historical OOS/probe/paper нет. Gate `READY_FOR_POSTPROCESS`, collector-процессов нет; следующий полезный segment `pit_universe_v2_forward_20260716_n03`, `2026-07-16 23:00-23:20 +03:00`.

## 32. Two-leg paper execution safety

- Ожидание sealed PIT-window больше не блокирует изолированную offline-разработку. В `basis_paper_oms.py` добавлен opt-in execution guard, а `historical_basis_v2_paper_oms.py` связывает его лимиты с immutable execution-probe PlanOnly.
- Любой будущий paper transition требует двух синхронных MEXC/Gate depth snapshots. Guard проверяет quote age, timestamp skew, fill, `$500` capacity и impact; вход/выход оценивается по depth VWAP, а не по произвольному trade price.
- Missing/stale/thin depth дает append-only `EXECUTION_BLOCKED`, не открывает/не закрывает позицию и не создает фиктивный PnL. State/WAL reconciliation включает счетчики blocked/executed transitions.
- Verification: targeted OMS/CLI `18 OK`; полный basis-v2 regression `108 OK`; Python compile прошел. Network collector, OOS, returns/PnL, grid, retune, probe, paper-forward и live не запускались.
- Утвержденный PIT segment `pit_universe_v2_forward_20260716_n01` остается отдельным shadow-track и может быть запущен только в sealed window `2026-07-16 23:00-23:20 +03:00` после повторных gate/authorization checks.
- Каноническая цель осталась byte-identical, SHA-256 `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.

