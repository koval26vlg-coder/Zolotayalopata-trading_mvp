# trading_mvp: полная карта прогресса цели

- Время: 2026-08-02 13:39 +03:00
- Агент: Codex
- Задача: показать по каждому обязательному этапу, что уже доказано, что ещё не доказано и какое следующее действие разрешено.

## Простое объяснение

Мы ещё не нашли доказанную рабочую стратегию. Старая basis-идея закончилась до проверки прибыли: одной версии не хватило истории, второй не хватило ликвидных активов. Сейчас проверяется новая dense WS идея.

Для новой идеи уже готовы правила, защита от подглядывания в будущее и критерии успеха. Но сами сутки данных ещё не собраны. Поэтому train, OOS, walk-forward, stress и экономика пока честно отмечены как `не запускались`, а не как пройденные.

## Текущее состояние

- Старая basis v1: terminal `INSUFFICIENT_DATA`, повтор того же контракта запрещён.
- Старая basis v2: terminal `INSUFFICIENT_EXECUTABLE_UNIVERSE`, повтор того же контракта запрещён.
- PIT shadow-track: 6 из 20 принятых дат; следующий сегмент n06 уже утверждён.
- Dense campaign: утверждён один непрерывный 24-часовой public read-only сбор.
- Signal/evaluator contract: заморожен, но evaluator не разрешён.
- Edge verdict: ещё отсутствует.
- Live/private API/капитал/leverage/margin: запрещены.

## Следующие ворота

1. PIT n06 в 01:00.
2. Dense writer в 01:30.
3. Проверка качества и causal materialization после завершения данных.
4. Новый PlanOnly, привязанный к точным хэшам materialization.
5. Отдельное разрешение на evaluator.
6. Только затем train, chronological OOS, five-fold walk-forward, stress, economics и execution-capacity verdict.

## Evidence

- Audit: `docs/agent-log/readiness/trading-mvp-goal-progress-audit-20260802T1339+0300.json`
- Audit canonical hash: `ebf7e6f5528b7d7a95b661d6bb67ca3d947804ef1a813d832f5ab6ed8cfec658`
- Audit file SHA-256: `f4a51c8280e3df99fa9afbe4bb965fa02143ee79edc8d4dd5e7b9034b0f86f89`

Ни один collector, evaluator, OOS, returns/PnL, grid, retune, paper/live или private API процесс этим аудитом не запускался.
