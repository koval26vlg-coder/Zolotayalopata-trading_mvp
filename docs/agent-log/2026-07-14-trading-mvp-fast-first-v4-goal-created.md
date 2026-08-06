# trading_mvp Fast-First v4 goal created

## Дата и агент

- Дата: 2026-07-14
- Агент: Codex

## Запрос пользователя

На основе текущих данных, Fast-First результатов и проверки аудита Claude сформировать правильную подробную цель, пригодную для непосредственной реализации.

## Выполнено

- Проверен active run gate: `READY_FOR_POSTPROCESS`, live worker отсутствует, replay/grid заблокированы.
- Проверено, что v3 `venue_local_lottery_max_factor_v1` закрыт как `INSUFFICIENT_DATA` с отрицательной наблюдаемой экономикой и не подлежит retune.
- Проверено, что P0 simulator/gate findings из аудита Claude уже исправлены и не входят в новый backlog.
- Создан новый канонический goal document:
  - `docs/plans/2026-07-14-trading-mvp-current-goal.md`.
- Fast-First остается critical path: default runtime 20 минут, hard cap 3 часа, visible owned runs, existing data/cache first.
- Первой новой независимой гипотезой выбрана `venue_local_funding_pressure_reversal_v1`.
- Гипотеза отделена от отклоненного funding carry: acceptance требует положительный price-only PnL после costs; благоприятный funding не может спасти отрицательный price alpha.
- Зафиксированы signal, economics, OOS, walk-forward, stress, concentration, capacity, probe, paper-forward и live-review gates.
- Активная цель Codex создана. OOS, collect, probe и live не запускались.

## Измененные файлы

- `docs/plans/2026-07-14-trading-mvp-current-goal.md`
- `docs/agent-log/2026-07-14-trading-mvp-fast-first-v4-goal-created.md`

## Ограничения

- Старый `spot_pit_event_forward_20260712_225519` остается diagnostic-only и не resume-ится автоматически.
- Рой не запускался, потому что пользователь ранее его остановил; независимые checks выполняет Codex по frozen artifacts.
- Live orders, API keys, leverage и margin остаются запрещены.
- Любой run дольше трех часов требует отдельного запроса пользователя.

## Следующий шаг

Реализовать только Task 1 нового плана: frozen v4 PlanOnly, schema/data seal/costs/split/gates, без чтения OOS performance.
