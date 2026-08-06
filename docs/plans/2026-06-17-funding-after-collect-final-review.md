# Funding After-Collect Final Review

Дата: 2026-06-17

## Назначение

После видимого 7d funding/basis collect не нужно вручную собирать команды для rank/backtest/OOS/walk-forward/stress/sensitivity. Для этого подготовлен wrapper:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\run_funding_final_review_visible.ps1
```

Если `InputPath` не указан, wrapper берет `output_path` и `manifest_path` из `docs/agent-log/active-run-gate.json`.

## Защита от преждевременного запуска

Wrapper прерывается, если:

- active-run gate показывает `RUNNING`;
- active-run gate показывает `STOPPED_INCOMPLETE`;
- manifest не найден;
- `manifest.final != true`;
- `completed_cycles < cycles`;
- число строк JSONL не совпадает с `manifest.rows`.

## Что запускается

Foreground-команда `trading_mvp/run_mvp.ps1 -Action funding-final-review`, без фонового запуска и без скрытого окна.

После успешного final-review wrapper автоматически запускает:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_watchlist_review.ps1
```

Это сравнивает rank/postprocess с predeclared funding watchlist и защищает от cherry-picking.

Если `funding-final-review` создал `ready_for_paper_forward`, но watchlist review не поддерживает promotion, wrapper сохраняет backup исходного paper plan и заменяет его на `blocked_by_watchlist_review`. Дополнительно пишется `funding_paper_plan_watchlist_block_*.json`.

Создаваемые артефакты:

- final review;
- rank;
- backtest;
- OOS;
- walk-forward;
- gate report;
- regime report;
- frontier report;
- sensitivity;
- watchlist review;
- watchlist paper block;
- decision report;
- paper plan only if gates accept the setup.

## Экономические gates

Базовые параметры:

- `NotionalQuote=100`;
- `FundingTargetHoldIntervals=6`;
- `FundingMinExpectedNetCarryBps=0`;
- `FundingMinRiskAdjustedEdgeBps=0`;
- `FundingMaxBreakEvenHours=168`;
- `FundingAcceptMinTrades=20`;
- `FundingAcceptMinWinRate=0.60`;
- `FundingAcceptMinProfitFactor=1.2`;
- stress enabled: adverse basis `25 bps`, spread widen `5 bps`, funding flip `5 bps`.

Sensitivity grid:

- spot fee: `0,2.5,5,10`;
- perp fee: `0,1,2.5,7.5`;
- slippage: `0,0.25,0.5,1`;
- hold intervals: `1,3,6,12`;
- break-even hours: `24,72,168,336`.

## Интерпретация

Если final review не принимает setup, следующий шаг не live trading и не ручная оптимизация. Нужно либо продолжать longer collection, либо менять strategy family.

Если final review принимает setup, но watchlist review показывает `ACCEPTANCE_CONFLICT_NO_WATCHLIST_SUPPORT` или `OFF_WATCHLIST_ONLY_REQUIRES_CHERRY_PICK_REVIEW`, это не готовый edge. Такой результат считается новой гипотезой и требует независимого сбора.

Если paper plan был создан до такого конфликта, wrapper обязан заменить его на blocked plan. `ready_for_paper_forward=true` допустим только при supporting watchlist review.

Если final review принимает setup и watchlist review не конфликтует, это только допуск к paper-forward. Live orders остаются заблокированы до отдельного live-readiness gate.
