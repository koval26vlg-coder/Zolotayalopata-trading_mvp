# 2026-07-09 15:11 +03:00 - Codex - trading_mvp slow liquidity data availability preflight

## User request
- Пользователь подтвердил public probe; текущий gate вел на read-only slow-liquidity data availability preflight PlanOnly.

## Plan
- Проверить active-run gate.
- Не запускать collect/replay/grid/live/API/paper-forward.
- Инвентаризировать существующие OHLCV/WS/market-filter артефакты.
- Зафиксировать gate-решение и следующий безопасный шаг.

## Done
- Добавлен 	ools/trading_slow_liquidity_data_availability_preflight.ps1.
- Подключены routing/status поля в 	ools/trading_next_goal_step.ps1, 	ools/trading_goal_status.ps1, 	ools/trading_branch_selector.ps1.
- Обновлены regression tests в 	rading_mvp/tests/test_visible_ws_collect_wrapper.py.
- Выполнен PlanOnly preflight с -UpdateGate.

## Decision
- SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_HISTORY_PLAN.
- Replay/grid/collect/paper-forward/live/API остаются заблокированы.

## Evidence
- Artifact: $artifact.
- Fail checks:
  - multi_week_ohlcv: max event span 72h; aggregate disjoint span 8272h не считается полноценной multi-week историей.
  - equired_timeframes: есть только 1h, нет 15m и 4h.
  - independent_events: 36 event_id вместо >=200.
- Pass checks: venue diversity 3 exchanges, market diversity 30 bases, liquidity proxy usable, WS market-filter accepted 2 exchanges / 32 markets / ~47.89h.

## Verification
- PowerShell parser OK for changed scripts.
- python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper: 28 OK, 4 skipped.
- Scoped git diff --check OK for touched files.
- Full git diff --check still reports unrelated pre-existing whitespace in 	rading_mvp/run_mvp.ps1; not changed here.

## Next allowed step
- Build slow-liquidity history data plan/approval packet PlanOnly: public OHLCV 15m/1h/4h multi-week coverage plus spread/liquidity proxy.
- Do not start actual collect/replay/grid/live/API/paper-forward without explicit approval.
