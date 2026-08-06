<!-- codex-visible-run-rule -->
## Visible Run Rule
- Любой длительный прогон, collector, backtest, replay, grid-search, paper-forward или процесс, который пишет артефакты во времени, запускать только в видимом терминале или через видимый monitor-скрипт.
- Не запускать такие прогоны в фоне, скрыто или через слепой `Start-Process` без отдельного явного подтверждения пользователя.
- Исключение для `trading_mvp`: короткий deterministic owned no-grid evaluation/OOS/postprocess/report на уже замороженном PlanOnly и существующих локальных данных не требует отдельной фразы-подтверждения, если `active-run gate` не `RUNNING`, запуск видимый, `MaxRuntimeSec<=1800`, без network collector, grid, retune, paper-forward, live orders, API keys, leverage или margin. Команды `продолжи`, `продолжи цель`, `что дальше`, `погнали`, `давай дальше` в таком состоянии считаются достаточным разрешением на этот короткий проверочный запуск. Нельзя ставить цель в `blocked` только из-за отсутствия отдельной фразы `подтверждаю` для такого шага.
- Одно точное подтверждение immutable hash-bound multi-segment schedule для `trading_mvp` разрешает все перечисленные в нём сегменты в пределах утверждённых окон. Не запрашивать повторное подтверждение каждого сегмента, не ставить цель в `blocked` между датами и не требовать ежедневного сообщения пользователя. Новый запрос подтверждения допустим только при изменении `plan_hash`, scope, длительности/окон, создании нового schedule либо для явного resume после `STOPPED_INCOMPLETE`.
- Если задача короткая, несущественная или фон может быть удобнее, сначала спросить пользователя: запускать в фоне или в терминале.
- Если пользователь явно разрешил фоновый запуск, обязательно сохранить metadata: PID, command, cwd, stdout, stderr, output/manifest paths, start time, expected duration, и сразу дать команду проверки статуса.
- Если команда сама почти ничего не печатает, обернуть ее видимым monitor-скриптом, который периодически показывает progress, line count, last write, stderr и ключевые ошибки.
- Правило применяется ко всем проектам и чатам в этом локальном Codex-окружении; для проекта `trading_mvp` это обязательная политика запуска прогонов.
<!-- /codex-visible-run-rule -->

<!-- codex-active-run-gate-rule -->
## Active Run Gate Rule
- Перед любым следующим шагом по активной цели проверить `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json` командой `pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1`.
- Если gate-status `RUNNING`, второй collector, probe, consumer незавершенного output, postprocess, grid/search и любые пересекающиеся действия запрещены.
- Во время `RUNNING` допускаются только bounded offline code work, unit tests, fixture/static analysis и вычисления на другом immutable cache/output namespace. Перед этим обязательно выполнить scoped-проверку `tools\check_active_run_gate.ps1 -OfflineWork -ReadResourcePath <paths> -WriteResourcePath <paths>` и продолжать только при `scope_decision.allowed=true`.
- Обычный вызов checker без `-OfflineWork` сохраняет глобально закрытое поведение. Необъявленный, поврежденный или пересекающийся scope всегда блокируется fail-closed.
- Если gate-status `READY_FOR_POSTPROCESS`, следующий основной шаг цели разрешен: постобработка завершенного output/manifest и аналитика результата.
- Если gate-status `STOPPED_INCOMPLETE`, не продолжать цель как будто данные готовы; сначала видимо resume-запускать сбор или явно признать dataset неполным.
- Это правило нужно применять, чтобы не жечь лимиты и не делать бесполезную работу во время активного длительного прогона.
<!-- /codex-active-run-gate-rule -->

<!-- codex-no-idle-autopilot-rule -->
## No-Idle Autopilot Rule
- Для `trading_mvp` ожидание будущего календарного окна не является самостоятельным рабочим состоянием.
- Если approved segment еще не `DUE`, active-run gate не `RUNNING`, недельный остаток больше `15%` и нет критического пользовательского checkpoint, выполнять последовательно bounded offline queue: tests, static/data-quality audit, fixture work, paper-product readiness и другие задачи на immutable данных.
- После исчерпания ручной очереди использовать hash-bound auto-refill catalog. Каждый task id выполняется не более одного раза; бессмысленные повторы, grid, retune и чтение закрытого OOS запрещены.
- Если hash-bound catalog исчерпан при недельном остатке больше `15%`, состояние `WAITING` запрещено: построить следующий bounded catalog из actionable gaps последнего readiness audit, сохранив venue/universe/hypothesis/cost/evidence/safety contracts. Если для продолжения требуется изменить любой из этих контрактов, это критический checkpoint для пользователя.
- Когда approved segment становится `DUE`, он получает приоритет над offline queue. Один market-data writer остается единственным, видимым и ограниченным `MaxRuntimeSec`.
- При недельном остатке `<=15%` не начинать новую работу. После authoritative reset автономная очередь возобновляется автоматически.
- Остановиться для пользователя только на критическом checkpoint: изменение гипотезы/venue/universe/cost/risk contract, terminal ACCEPT/REJECT, integrity/safety conflict либо live/private API/real-capital decision.
<!-- /codex-no-idle-autopilot-rule -->

<!-- codex-trading-autopilot-rule -->
## Trading Autopilot Rule
- Для `trading_mvp` действует standing policy `docs/plans/trading-mvp-autopilot-policy-v1.json`: все routine same-scope/hash-bound действия выполняются автоматически без повторного сообщения пользователя. Ожидание календарной даты или внешнего события является `WAITING_EVENT`, а не основанием ставить цель в `blocked` или тратить лимит на бессмысленные проверки.
- `WAITING_EVENT` не означает простой. Пока утвержденный календарный сегмент еще не наступил и gate открыт, последовательно выполнять первый невыполненный пункт `productive_fallback_queue`: immutable-cache/code provenance, data-quality, deterministic regression, paper-only infrastructure или materially distinct public-source research. Каждая задача ограничена 30 минутами, фиксируется в append-only ledger и не повторяется при том же task/hash.
- При наступлении approved schedule window fallback немедленно уступает приоритет точному hash-bound сегменту. Запрещены второй data writer, чтение незавершенного output, повтор закрытой ветки, искусственная занятость, grid/retune и параллельные конфликтующие действия.
- Если one-shot fallback-очередь исчерпана, не создавать бессмысленный busy-loop: зафиксировать `WAITING_SCHEDULE_WINDOW_NO_FALLBACK` и сформировать следующий materially useful backlog только в рамках текущей гипотезы. Изменение гипотезы/venue/universe/signal/cost/risk остается критическим checkpoint.
- Контролировать именно недельный Codex rate-limit window `10080` минут через свежую локальную telemetry. При `remaining_percent <= 15` не начинать новые действия, разрешить уже запущенному bounded writer корректно завершиться, записать `PAUSED_WEEKLY_LIMIT` и один раз уведомить пользователя. После reset и свежего `remaining_percent > 15` автоматически вернуть `ACTIVE` и продолжить `next_allowed_action` без подтверждения.
- При `STOPPED_INCOMPLETE` допускается один автоматический видимый recovery того же immutable run только если writer PID мёртв, plan/code/config/input hashes совпадают, output append-safe, hard deadline не прошёл и причина транзиентная. Повторный сбой, schema/hash mismatch, corruption или unsafe disk являются критическим stop.
- Участие пользователя запрашивать только при materially new/changed hypothesis, изменении venue/universe/signal/cost/risk/acceptance contract, принятии или окончательном отклонении гипотезы, необратимом integrity/safety конфликте либо перед live orders/private API keys/real capital/leverage/margin/withdrawal permission.
- Автономность не разрешает busy-loop, grid/retune закрытых веток, второй market-data writer, скрытый writer или работу, не приближающую доказательство/отбраковку edge.
<!-- /codex-trading-autopilot-rule -->

<!-- codex-trading-edge-scope-rule -->
## Trading Edge Scope Rule
- Не брать на анализ новый контент с канала, YouTube/RSS/transcript/source-packet материалы и похожие внешние медиа, если пользователь явно не открыл эту работу заново.
- Уже собранные материалы канала использовать только как источник гипотез, а не как активный поток новых задач.
- Не тратить рабочие циклы на P2P, уголовно-правовые сюжеты, вывод крипты, хранение, 115-ФЗ, фиатные рельсы и похожий off-ramp/custody/legal контент в рамках цели поиска trading edge.
- Главная цель по `trading_mvp`: найти, доказать или честно отбросить рабочую trading strategy / high-winrate edge через данные, backtest, OOS, walk-forward, stress, economics и paper-forward gates.
- Не оптимизировать "винрейт" отдельно от expectancy, net PnL after costs, profit factor, drawdown, sample size, liquidity/fill risk и устойчивости вне выборки.
- Следующие инженерные действия должны двигать proof pipeline: сбор рыночных данных, нормализация, replay/backtest, postprocess, gating, risk/economics, paper-forward readiness. Канальный мониторинг не является целью.
- Если действие не приближает доказательство или отбраковку edge, его не делать без явного запроса пользователя.
<!-- /codex-trading-edge-scope-rule -->

<!-- codex-trading-swarm-rule -->
## Trading Swarm Rule
- Для ключевых решений по цели `trading_mvp` использовать инструмент `Рой` как независимую проверку: quality gate, economics, OOS/walk-forward, stress, paper-forward readiness, архитектурные изменения и решение "продолжать или отбрасывать ветку".
- `Рой` не отменяет Active Run Gate Rule, Visible Run Rule, запрет live orders/API keys/leverage/margin и research-only режим.
- Если лимиты агентов из `Рой` исчерпаны, агенты недоступны или workflow не может продолжить работу, зафиксировать это как `swarm_limited` и перейти на личное управление Codex по тем же gate-правилам.
- После восстановления лимитов или доступности агентов снова подключать `Рой` на ближайшем значимом checkpoint, а не ждать отдельного напоминания пользователя.
- Не использовать `Рой` для мониторинга канала, P2P/off-ramp/legal/custody тем или иных задач, не приближающих доказательство/отбраковку trading edge.
<!-- /codex-trading-swarm-rule -->
