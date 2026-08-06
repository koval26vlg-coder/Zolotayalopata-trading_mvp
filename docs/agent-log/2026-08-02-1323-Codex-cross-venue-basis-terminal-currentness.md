# Cross-venue basis: проверка текущего статуса

- Время: 2026-08-02 13:23 +03:00
- Агент: Codex
- Задача: проверить, не забыта ли основная историческая basis-ветка исходной цели, не читая закрытые OOS/returns/PnL.

## Простое объяснение

Старая basis-идея не ждёт продолжения. Она дважды остановилась до проверки прибыли:

1. V1 требовал 220 дней пятиминутной истории, а публичный Gate отдавал примерно 34.7 дня. Итог: `INSUFFICIENT_DATA`.
2. V2 собрал данные, но frozen liquidity gate прошли 5 активов при минимуме 8. Итог: `INSUFFICIENT_EXECUTABLE_UNIVERSE`.

В обоих случаях OOS, returns и PnL не читались. Это не доказательство отсутствия edge вообще, но тот же контракт нельзя повторять или ослаблять после результата.

Текущая dense WS ветка является новой: другой тип данных, отдельный causal contract и отдельный no-grid signal/evaluator contract. Поэтому она законно продолжает исходную цель, не переоткрывая закрытый basis-контракт. PIT остаётся отдельным shadow-track.

## Проверено

- V1 immutable closure report: final, `INSUFFICIENT_DATA`, `edge_evaluated=false`, `pnl_read=false`.
- V2 primary/repeat reports имеют одинаковый deterministic result hash.
- V2 final verification: 106 basis-v2 tests OK, OOS/PnL/grid/retune/live не запускались.
- Старый статус V1 в hypothesis bank устарел; reconciliation от 19.07.2026 явно отдаёт приоритет terminal artifacts.
- Текущий guard остаётся `ACTIVE`; basis action не due.

## Evidence

- Audit: `docs/agent-log/readiness/cross-venue-basis-terminal-currentness-audit-20260802T1323+0300.json`
- Audit SHA-256: `8640b20c5a5e9257998646c66afa1b5f574c3295c56a117a9d0f6fc591be83d2`

## Следующий шаг

Не перезапускать и не ретюнить basis v1/v2. Продолжать утверждённый dense collector и PIT; после dense materialization переходить только по frozen evaluator gate и отдельному разрешению.
