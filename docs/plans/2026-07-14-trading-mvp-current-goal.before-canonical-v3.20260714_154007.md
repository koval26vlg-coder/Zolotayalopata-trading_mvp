# trading_mvp: ЦЕЛЬ — единый документ для Codex

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

Дата фиксации: 2026-07-14 15:25 Europe/Volgograd.

Этот документ принят как текущая рабочая цель. При конфликте со старыми `current-goal`, handoff, agent-log или отдельными сообщениями использовать эту версию и правила `AGENTS.md`.

Фактическая поправка к разделу 3/15: после создания исходного текста v6 уже был реализован, проверен и закрыт. Поэтому пункт `v6: применить feasibility gate ДО построения/запуска OOS` считается историческим и не является следующим действием.

Текущее состояние:

- v4 `funding_pressure_reversal_v1`: `INSUFFICIENT_DATA`, закрыта, ретюнинг запрещен.
- v5 `wick_rejection_reversal_v1`: `INSUFFICIENT_DATA`, закрыта, ретюнинг запрещен.
- v6 `weekend_liquidity_window_v1`: `INSUFFICIENT_DATA`, закрыта, ретюнинг запрещен.
- текущий daily-data Fast-First track: `NO_FAST_EDGE_ON_CURRENT_DAILY_DATA` / `NO_FAST_EDGE_FOUND` для существующего input Merkle.
- execution probe, paper-forward, live/API keys, leverage/margin, grid/search и retune не разрешены.

Следующий разрешенный рабочий маршрут без отдельного запуска: подготовить новый data-track contract, feasibility-estimator contract, банк pre-registered гипотез и ночное расписание proposal. Actual collectors/probes/night runs требуют явного утверждения пользователя по разделам 7-9.

