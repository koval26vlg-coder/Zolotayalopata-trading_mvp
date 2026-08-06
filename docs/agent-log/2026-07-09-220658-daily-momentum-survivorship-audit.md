# trading_mvp daily momentum survivorship audit

Дата: 2026-07-09
Агент: Codex

## Исходный контекст
Активная цель: найти, доказать или честно отбросить рабочий non-Binance trading edge через данные, OOS/walk-forward/stress/economics gates и paper-forward readiness.

Фактический gate перед работой:
- `READY_FOR_POSTPROCESS`, но `replay_allowed=false`.
- Текущая ветка: `cross_sectional_momentum_daily`.
- Следующий шаг: survivorship/point-in-time universe audit и max drawdown/concentration policy.

## Что сделано
- Добавлен модуль `trading_mvp/src/momentum_survivorship_audit.py`.
- Добавлен wrapper `tools/trading_daily_momentum_survivorship_audit.ps1`.
- Добавлены тесты `trading_mvp/tests/test_momentum_survivorship_audit.py`.
- Обновлен `tools/trading_next_goal_step.ps1`, чтобы audit-revise не вел к paper-forward/live/grid.
- Исправлен Python runtime fallback в wrapper: hard path -> `py` -> `python`.
- Запущен audit на existing daily dataset и текущем momentum report.
- Получен независимый review от субагента: `approve` для audit decision.

## Проверки
- `python -m unittest trading_mvp.tests.test_momentum_survivorship_audit trading_mvp.tests.test_momentum_backtest`: 18 OK.
- Wrapper smoke: decision `DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_REVISE_REQUIRED`.
- Router smoke: decision `DAILY_CROSS_SECTIONAL_MOMENTUM_ACCEPTANCE_BLOCKED_BY_SURVIVORSHIP_AND_RISK`.

## Результат audit
Artifact: `exports/trading-mvp/analysis/cross_sectional_momentum_survivorship_audit_20260709_220239.json`

Decision: `DAILY_CROSS_SECTIONAL_MOMENTUM_SURVIVORSHIP_AUDIT_REVISE_REQUIRED`.

Причины:
- `survivorship_pass=false`: нет point-in-time universe metadata, нет delisted/inactive coverage, manifest выглядит как current top-volume snapshot.
- `history_pass=false`: 72/400 рынков имеют историю короче 120 дней.
- `risk_policy_pass=false`: `non_binance_baseline` max DD 35.42% при лимите 25%.

## Вывод
`cross_sectional_momentum_daily` остается research candidate по OOS/stress числам, но не accepted edge. Paper-forward/live/API/grid запрещены.

## Следующий шаг
- Либо source point-in-time/delisted universe только после явного approval на новый data sourcing/collect.
- Либо признать daily momentum `research-inconclusive/rejected for acceptance` на текущих данных и выбрать новую PlanOnly-гипотезу.
