# trading_mvp membership-momentum-v2: global cadence correction

## Метаданные

- Время: 2026-07-17 11:23 +03:00
- Агент: Codex
- Режим: bounded offline engineering; без network collector, returns/OOS на реальных данных, grid, retune, probe, paper-forward, live orders или private API keys

## Исходный запрос

Продолжить активную цель `trading_mvp One-Week Historical Edge Sprint` после того, как повторное подтверждение уже завершённого membership-v2 source probe было отклонено как duplicate.

## Найденный дефект

OOS evaluator начинал семидневную rebalance cadence заново в начале каждого 20-дневного fold. Из-за этого оценочная разметка меняла даты торгового сигнала и создавала 10 fold-local событий вместо единого календаря стратегии. Это нарушало no-retune invariant и не давало однозначного forward anchor.

## Исправление

- Train PlanOnly теперь фиксирует `rebalance_schedule_contract` с единым `anchor_day = train_start_day + 30` и cadence `7` дней.
- Train evaluator выполняет только hash-bound `eligible_signal_days` из этого контракта.
- OOS PlanOnly наследует anchor из hash-valid train PlanOnly; каждый fold только отбирает глобально запланированные события, которые полностью помещаются внутри него.
- Boundary-crossing signals сохраняются отдельно как `boundary_excluded_signal_days`, а не сдвигаются на начало следующего fold.
- Для frozen `120d train / 100d OOS`, `30d lookback / 7d hold / 7d rebalance`: train остаётся `12` событий; OOS содержит `15` глобально запланированных сигналов, из которых `9` fold-contained и `6` boundary-excluded. Coverage gate остаётся `ceil(9 * 0.80) = 8`.
- Следующий forward signal однозначно выводится из того же anchor, без выбора даты по результатам OOS.
- Train/OOS plan и result schemas подняты с `v1` до `v2`, чтобы pre-fix artifacts не могли пройти authorization.

## Изменённые файлы

- `trading_mvp/src/gate_membership_momentum_v2_train.py`
- `trading_mvp/src/gate_membership_momentum_v2_oos.py`
- `trading_mvp/tests/test_gate_membership_momentum_v2_train.py`
- `trading_mvp/tests/test_gate_membership_momentum_v2_oos.py`

## Проверки

- RED до исправления: отсутствовал schedule contract; OOS возвращал `10`, а не `9` событий.
- Targeted train/OOS: `12/12 OK`.
- Membership/history regression: `83/83 OK`.
- Python compile: OK.
- Полный regression: `1023 OK`, `5 skipped`, `0 failed`, `315.848s`.

## Текущий внешний статус

- Active-run gate: `READY_FOR_POSTPROCESS`; активных writers нет.
- Membership-v2 source остаётся terminally rejected: delisted-end coverage `0.3830 < 0.90`.
- Реальный v3 source/history/train/OOS не запускался; edge не доказан.
- Единственный разрешённый следующий network action остаётся exact-approved visible v3 archive-metadata probe `plan_hash=e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.

## Supersedes

Эта запись заменяет только sample/cadence-часть handoff `2026-07-17-1102-trading-mvp-membership-momentum-v2-oos-ready.md`: утверждение о 10 fold-local событиях больше не является действующим. Остальные economics/OOS/embargo gates сохраняются.

## Следующему агенту

Не создавать execution-probe shortlist из OOS frequency. Сначала получить hash-valid v3 source/history/train/OOS. При historical ACCEPT будущий forward portfolio должен вычисляться только на следующем globally scheduled signal day из frozen anchor.
