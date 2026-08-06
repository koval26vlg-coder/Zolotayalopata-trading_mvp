# 2026-07-09 14:43 +03:00 - Codex - slow liquidity PlanOnly scaffold

## User request
- Пользователь подтвердил public probe и продолжение цели `trading_mvp` после отклонения `spot_perp_basis_mean_reversion_no_funding`.

## Plan
- Проверить active-run gate.
- Не запускать collect/replay/grid/live/API.
- Добавить PlanOnly scaffold для следующей ветки `slow_liquidity_regime_breakout_retest`.
- Обновить routing так, чтобы старое поле `last_spot_perp_basis_public_probe_decision` не возвращало управление к отвергнутой spot/perp ветке.
- Проверить parser/tests и обновить gate только PlanOnly-командами.

## Done
- Добавлен `tools/trading_slow_liquidity_regime_breakout_retest_planonly.ps1`.
- Обновлены `tools/trading_goal_status.ps1`, `tools/trading_next_goal_step.ps1`, `tools/trading_branch_selector.ps1`.
- Добавлен regression test для slow PlanOnly и обновлены routing assertions.
- Выполнен `trading_structural_branch_planonly.ps1 -UpdateGate -Json`: выбрана ветка `slow_liquidity_regime_breakout_retest`.
- Выполнен `trading_slow_liquidity_regime_breakout_retest_planonly.ps1 -UpdateGate -Json`: active gate переведен в `SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT`.

## Files changed
- `tools/trading_slow_liquidity_regime_breakout_retest_planonly.ps1`
- `tools/trading_goal_status.ps1`
- `tools/trading_next_goal_step.ps1`
- `tools/trading_branch_selector.ps1`
- `trading_mvp/tests/test_visible_ws_collect_wrapper.py`
- `docs/agent-log/active-run-gate.json`

## Verification
- PowerShell parser OK for changed PS scripts.
- `tools/trading_slow_liquidity_regime_breakout_retest_planonly.ps1 -Json` OK; no start, no live/API/collect/replay/grid/paper-forward.
- `tools/trading_goal_status.ps1 -Json` shows `slow_liquidity_regime_selected_gate=true` and `spot_perp_basis_rejected_gate=false`.
- `tools/trading_next_goal_step.ps1 -Json` returns `SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT`.
- `tools/trading_branch_selector.ps1 -Json` returns selected branch `slow_liquidity_regime_breakout_retest`.
- `python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper`: 27 OK, 4 skipped, run before and after gate update.
- `git diff --check` OK for changed files.

## Risks and limits
- This is research-only scaffolding, not evidence of an edge.
- Replay/grid/collect/live/API/paper-forward remain blocked.
- Cost hurdle is intentionally conservative under base/VIP0/no-volume assumptions: minimum gross move hurdle in scaffold is 249 bps.
- Next step must be a read-only data availability preflight, not replay.

## Next allowed step
- Build `slow_liquidity_regime` data-availability preflight PlanOnly: inventory existing OHLCV/spread/liquidity coverage by market/timeframe, report sample sufficiency and reject/rescope if data cannot support OOS/walk-forward/stress.
