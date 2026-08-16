# Codex Trading Autopilot Rules — Revised

<!-- codex-visible-run-rule -->

## Visible Run Rule

- Любой длительный прогон, collector, backtest, replay, grid-search, paper-forward или процесс, который пишет артефакты во времени, запускать только в видимом терминале или через видимый monitor-скрипт.
- Не запускать такие прогоны в фоне, скрыто или через слепой `Start-Process`, кроме случаев, когда пользователь отдельно и явно разрешил фоновый запуск.
- Для `trading_mvp` routine research-only действия в рамках уже утверждённого scope выполняются автоматически после успешного прохождения технических guard-проверок и не требуют отдельной фразы пользователя.
- К таким действиям относятся:
  - public exchange/API requests без аутентификации;
  - market-data collection в рамках уже утверждённых venue/universe/scope;
  - deterministic materialization/postprocess;
  - evaluator;
  - replay/backtest;
  - OOS/walk-forward;
  - stress/economics/report;
  - paper-only infrastructure и paper-forward, если он не использует private API и реальные ордера.
- Короткий deterministic owned no-grid evaluation/OOS/postprocess/report на уже замороженном PlanOnly и существующих локальных данных может выполняться автоматически, если:
  - `active-run gate` не `RUNNING`;
  - запуск видимый;
  - `MaxRuntimeSec<=1800`;
  - exact code/config/input hashes совпадают;
  - отсутствуют private API keys, реальные ордера, real capital, leverage, margin, withdrawal или transfer.
- Команды `продолжи`, `продолжи цель`, `что дальше`, `погнали`, `давай дальше`, `/goal-continue` считаются указанием продолжать автономный research workflow в пределах standing policy. Не требовать после них дополнительных фраз вида `подтверждаю`, `EXACT_*_APPROVAL` или аналогичных approval tokens для routine research-only шагов.
- Одно immutable hash-bound определение schedule/PlanOnly является достаточным основанием выполнять все перечисленные в нём routine research-only сегменты автоматически, пока `plan_hash`, scope, runtime/code/config hashes, venue, universe и ограничения не изменились.
- Не запрашивать повторное подтверждение каждого сегмента, каждой даты, public network request, collector, materialization, evaluator, replay, OOS или postprocess при неизменном scope.
- Если hash/runtime/config изменился только из-за исправления технической реализации без изменения hypothesis/venue/universe/signal/cost/risk/acceptance contract, выполнить технический rebind автоматически после тестов и provenance-проверки. Не превращать новый SHA сам по себе в пользовательский checkpoint.
- Если задача короткая, несущественная и фон действительно удобнее, можно спросить пользователя о предпочтительном способе запуска, но отсутствие ответа не должно блокировать видимый research-only запуск.
- Если пользователь явно разрешил фоновый запуск, обязательно сохранить metadata: PID, command, cwd, stdout, stderr, output/manifest paths, start time, expected duration и команду проверки статуса.
- Если команда сама почти ничего не печатает, обернуть её видимым monitor-скриптом, который показывает progress, line count, last write, stderr и ключевые ошибки.
- Правило применяется ко всем проектам и чатам в этом локальном Codex-окружении; для `trading_mvp` видимость длительных прогонов остаётся обязательной политикой.

<!-- /codex-visible-run-rule -->

<!-- codex-active-run-gate-rule -->

## Active Run Gate Rule

- Перед любым следующим шагом по активной цели проверить `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json` командой `pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1`.
- `Active Run Gate` является техническим concurrency/integrity gate, а не пользовательским approval gate.
- Если gate-status `RUNNING`, второй collector, второй writer, consumer незавершённого output, конфликтующий postprocess, grid/search и любые пересекающиеся действия запрещены.
- Во время `RUNNING` допускаются bounded offline code work, unit tests, fixture/static analysis и вычисления на другом immutable cache/output namespace.
- Перед такой параллельной offline-работой выполнить scoped-проверку `tools\check_active_run_gate.ps1 -OfflineWork -ReadResourcePath <paths> -WriteResourcePath <paths>` и продолжать только при `scope_decision.allowed=true`.
- Обычный вызов checker без `-OfflineWork` сохраняет глобально закрытое поведение. Необъявленный, повреждённый или пересекающийся scope всегда блокируется fail-closed.
- Если gate-status `READY_FOR_POSTPROCESS`, следующий research-only этап разрешён автоматически: postprocess, materialization, evaluator, replay, backtest, OOS, walk-forward, economics, stress и report — в пределах текущего standing policy и технических лимитов.
- Не требовать отдельного user approval только потому, что этап использует public network request, пишет research artifacts или является следующим этапом proof pipeline.
- Если gate-status `STOPPED_INCOMPLETE`, не продолжать цель как будто данные готовы.
- При `STOPPED_INCOMPLETE` допускается автоматический visible resume того же immutable run, если:
  - writer PID мёртв;
  - exact plan/code/config/input hashes совпадают;
  - output append-safe;
  - hard deadline не прошёл;
  - причина транзиентная;
  - resume не создаёт второй writer.
- Новый пользовательский checkpoint при `STOPPED_INCOMPLETE` нужен только при schema/hash mismatch, corruption, unsafe disk, изменении research contract или после повторного неуспешного recovery.
- Gate должен использоваться для защиты целостности и ресурсов, а не как механизм повторного запроса разрешения пользователя.

<!-- /codex-active-run-gate-rule -->

<!-- grok-goal-controllers -->

## Grok Goal Controllers

- Долговечная цель Grok для этого проекта имеет ID `zolotyaylopata-trading-mvp` и использует канонический файл `docs/plans/2026-07-14-trading-mvp-current-goal.md`.
- В любом чате Codex команда `Grok: продолжи цель` остаётся маршрутом через глобальный MCP `grok_bridge.grok_goal_continue`. Bridge остаётся read-only strategist/reviewer и не переиспользует native Grok Build session.
- В прямом Grok Build `/goal <objective>` является встроенным xAI Goal-runtime.
- Пользовательский `/goal-continue` должен продолжать текущую цель, а не превращаться в бесконечный approval-checkpoint.
- Перед native Goal action он обязан вызвать `C:\Users\koval\.grok\tools\get-grok-goal-snapshot.ps1 -Json`, прочитать SML и контракт `D:\AionUi-Paperclip\docs\GROK-BUILD-GOAL.md`.
- Авторитетными остаются:
  - `tools/check_active_run_gate.ps1`;
  - `tools/trading_next_goal_step.ps1 -Json`;
  - `tools/trading_goal_status.ps1 -Json`.
- Контрольная точка Grok и native Goal checklist не должны создавать дополнительный user-approval layer поверх project controller.
- Состояние `waiting_approval` не является авторитетным само по себе, если причина ожидания относится только к routine research-only действию, которое разрешено настоящей standing policy.
- При расхождении Grok snapshot и project controller:
  - project technical guard определяет, можно ли безопасно выполнить действие;
  - routine research-only действие продолжается автоматически, если technical guard разрешает его;
  - Grok snapshot не должен блокировать действие только из-за отсутствия устаревшего `EXACT_*_APPROVAL`.
- Состояния `running`, `stopped_incomplete` и `unknown_blocked` продолжают обрабатываться fail-closed в соответствии с Active Run Gate.
- После controller-разрешения Grok Build может выполнять local reversible и routine research-only steps в видимом TUI без отдельного native permission approval на каждый шаг.
- Public network research, public exchange discovery, collector, replay/backtest/OOS/evaluator/postprocess не требуют отдельного user approval при неизменном research scope и успешных technical guards.
- Отдельное явное разрешение пользователя остаётся обязательным перед:
  - authenticated/private API access;
  - использованием API secrets/keys;
  - размещением, изменением или отменой реальных ордеров;
  - использованием real capital;
  - withdrawal/transfer;
  - leverage;
  - margin;
  - иными необратимыми финансовыми действиями.
- User hook `~/.grok/hooks/zolotyaylopata-goal-safety.json` должен блокировать только запрещённые safety/integrity/financial действия, а не routine research-only workflow.
- Не использовать `always-approve`, headless `/goal`, подагентов или другой state store для обхода integrity/concurrency/financial gates.

<!-- /grok-goal-controllers -->

<!-- codex-no-idle-autopilot-rule -->

## No-Idle Autopilot Rule

- Для `trading_mvp` ожидание будущего календарного окна, user approval token или внешнего события не является самостоятельным рабочим состоянием, если следующий шаг относится к уже разрешённому routine research scope.
- Если approved segment ещё не `DUE`, active-run gate не `RUNNING`, недельный остаток больше `15%` и нет критического checkpoint, выполнять последовательно bounded offline queue:
  - tests;
  - static/data-quality audit;
  - fixture work;
  - provenance;
  - paper-only infrastructure;
  - public-source research;
  - другие задачи на immutable данных, которые реально приближают доказательство/отбраковку edge.
- После исчерпания ручной очереди использовать hash-bound auto-refill catalog.
- Каждый task id выполняется не более одного раза для того же task/hash.
- Запрещены бессмысленные повторы, busy-loop, grid/retune закрытых веток и чтение закрытого OOS.
- Если hash-bound catalog исчерпан при недельном остатке больше `15%`, состояние `WAITING` запрещено: построить следующий bounded catalog из actionable gaps последнего readiness audit.
- Построение нового bounded catalog в рамках неизменных venue/universe/hypothesis/signal/cost/risk/acceptance contracts не требует пользовательского разрешения.
- Пользовательский checkpoint возникает только при materially new/changed:
  - hypothesis;
  - venue;
  - universe;
  - signal definition;
  - cost model;
  - risk contract;
  - acceptance contract;
  - либо при integrity/safety/financial конфликте.
- Когда approved segment становится `DUE`, он получает приоритет над offline queue.
- Один market-data writer остаётся единственным, видимым и ограниченным `MaxRuntimeSec`.
- При недельном остатке `<=15%` не начинать новую работу.
- После authoritative reset автономная очередь возобновляется автоматически без отдельного сообщения пользователя.
- Остановиться для пользователя только на критическом checkpoint:
  - изменение research contract;
  - terminal ACCEPT/REJECT;
  - необратимый integrity/safety conflict;
  - private API;
  - live trading;
  - real capital;
  - leverage/margin;
  - withdrawal/transfer.

<!-- /codex-no-idle-autopilot-rule -->

<!-- codex-trading-autopilot-rule -->

## Trading Autopilot Rule

- Для `trading_mvp` действует standing policy `docs/plans/trading-mvp-autopilot-policy-v1.json`.
- Все routine same-scope/hash-bound research actions выполняются автоматически без повторного сообщения пользователя.
- Standing authorization охватывает:
  - public exchange/API requests;
  - public asset identity discovery;
  - listing/announcement discovery;
  - market-data collection;
  - normalization/materialization;
  - deterministic postprocess;
  - evaluator;
  - replay/backtest;
  - train/OOS;
  - walk-forward;
  - stress/economics;
  - reports;
  - paper-only infrastructure;
  - paper-forward без private credentials и без реальных ордеров.
- Не создавать отдельные `exact_official_asset_identity_verification_approval`, `EXACT_*_EXECUTION_APPROVAL`, `requires_user_approval` или аналогичные пользовательские checkpoints для routine research-only действий, если:
  - hypothesis/venue/universe/signal/cost/risk/acceptance contract не изменились;
  - technical guards зелёные;
  - required hashes/manifests/provenance валидны;
  - отсутствует конфликт active-run gate;
  - действие не использует private API или реальные средства.
- Hash-binding остаётся обязательной technical integrity проверкой, но изменение runtime/launcher SHA вследствие проверенного bugfix/refreeze не должно автоматически требовать нового user approval.
- В таком случае:
  1. провести synthetic/regression tests;
  2. создать новый immutable manifest;
  3. проверить provenance;
  4. rebind policy/readiness;
  5. продолжить автоматически при зелёном guard.
- User approval требуется при изменении содержательного research scope, а не при каждом техническом SHA.
- `WAITING_EVENT` означает ожидание действительно внешнего события, а не ожидание повторной фразы пользователя для уже разрешённого действия.
- `WAITING_EVENT` не означает простой. Пока утверждённый календарный сегмент ещё не наступил и gate открыт, последовательно выполнять первый невыполненный пункт `productive_fallback_queue`.
- Каждая fallback-задача ограничена 30 минутами, фиксируется в append-only ledger и не повторяется при том же task/hash.
- При наступлении approved schedule window fallback немедленно уступает приоритет точному сегменту.
- Запрещены:
  - второй data writer;
  - чтение незавершённого output;
  - повтор закрытой ветки;
  - искусственная занятость;
  - grid/retune без отдельного содержательного основания;
  - параллельные конфликтующие действия.
- Если one-shot fallback-очередь исчерпана, не создавать busy-loop. Сформировать следующий materially useful backlog в рамках текущей гипотезы.
- Изменение hypothesis/venue/universe/signal/cost/risk/acceptance contract остаётся критическим checkpoint.
- Контролировать недельный Codex rate-limit window `10080` минут через свежую локальную telemetry.
- При `remaining_percent <= 15`:
  - не начинать новые действия;
  - разрешить уже запущенному bounded writer корректно завершиться;
  - записать `PAUSED_WEEKLY_LIMIT`;
  - один раз уведомить пользователя.
- После reset и свежего `remaining_percent > 15` автоматически вернуть `ACTIVE` и продолжить `next_allowed_action` без подтверждения.
- При `STOPPED_INCOMPLETE` допускается один автоматический видимый recovery того же immutable run, если выполняются technical recovery conditions.
- Повторный сбой, schema/hash mismatch, corruption или unsafe disk являются критическим stop.
- Участие пользователя запрашивать только при:
  - materially new/changed hypothesis;
  - изменении venue/universe/signal/cost/risk/acceptance contract;
  - terminal ACCEPT/REJECT;
  - необратимом integrity/safety конфликте;
  - использовании private API keys;
  - live orders;
  - real capital;
  - leverage;
  - margin;
  - withdrawal;
  - transfer.
- Автономность не разрешает busy-loop, второй market-data writer, скрытый writer, повреждение provenance, обход active-run gate или работу, не приближающую доказательство/отбраковку edge.

<!-- /codex-trading-autopilot-rule -->

<!-- codex-trading-edge-scope-rule -->

## Trading Edge Scope Rule

- Не брать на анализ новый контент с канала, YouTube/RSS/transcript/source-packet материалы и похожие внешние медиа, если пользователь явно не открыл эту работу заново.
- Уже собранные материалы канала использовать только как источник гипотез, а не как активный поток новых задач.
- Не тратить рабочие циклы на P2P, уголовно-правовые сюжеты, вывод крипты, хранение, 115-ФЗ, фиатные рельсы и похожий off-ramp/custody/legal контент в рамках цели поиска trading edge.
- Главная цель `trading_mvp`: найти, доказать или честно отбросить рабочую trading strategy / high-winrate edge через данные, backtest, OOS, walk-forward, stress, economics и paper-forward gates.
- Не оптимизировать winrate отдельно от:
  - expectancy;
  - net PnL after costs;
  - profit factor;
  - drawdown;
  - sample size;
  - liquidity/fill risk;
  - устойчивости вне выборки.
- Следующие инженерные действия должны двигать proof pipeline:
  - сбор рыночных данных;
  - нормализация;
  - replay/backtest;
  - postprocess;
  - evaluator;
  - OOS/walk-forward;
  - gating;
  - risk/economics;
  - paper-forward readiness.
- Public-source research, необходимый непосредственно для проверки текущей trading hypothesis, разрешён автоматически и не требует отдельного approval.
- Канальный мониторинг не является целью.
- Если действие не приближает доказательство или отбраковку edge, его не делать без явного запроса пользователя.

<!-- /codex-trading-edge-scope-rule -->
