# 2026-07-09 14:15 Codex: spot/perp public probe rejected route fix

## Исходный запрос
Пользователь подтвердил `public probe` для текущей ветки `spot_perp_basis_mean_reversion_no_funding`.

## План
- Проверить active-run gate.
- Выполнить подтвержденный короткий public REST probe.
- Не запускать collect/replay/grid/live/API/paper-forward.
- Если probe отвергнет ветку, зафиксировать результат и проверить роутинг следующего PlanOnly шага.

## Что было сделано
- Выполнен подтвержденный `trading_spot_perp_basis_public_probe.ps1` по preflight artifact `spot_perp_basis_availability_preflight_20260709_112347.json`.
- Probe завершился решением `SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE`: 0 paired-ok bases из 10, минимум был 5.
- Выявлен root-cause роутинг-баг: `trading_structural_branch_planonly.ps1` слепо выбирал `spot_perp_basis_mean_reversion_no_funding` после `listing_event_replay_rejected`, не учитывая свежий `SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE`.
- Исправлены роутеры, чтобы `public_probe_rejected` считался rejected-состоянием, а не selected-состоянием.
- Следующий PlanOnly-кандидат после rejected listing-event и rejected spot/perp теперь `slow_liquidity_regime_breakout_retest`.

## Измененные файлы
- `tools/trading_structural_branch_planonly.ps1`
- `tools/trading_goal_status.ps1`
- `tools/trading_next_goal_step.ps1`
- `tools/trading_branch_selector.ps1`
- `trading_mvp/tests/test_visible_ws_collect_wrapper.py`
- `docs/agent-log/active-run-gate.json` обновлен probe-скриптом

## Проверки
- PowerShell parser OK для четырех измененных роутеров.
- `trading_structural_branch_planonly.ps1 -Json` теперь возвращает `SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_SELECTED`, `selected_branch=slow_liquidity_regime_breakout_retest`, `spot_perp_basis_rejected=true`.
- `trading_goal_status.ps1 -Json` показывает `primary_edge_status=spot_perp_basis_public_probe_rejected_rescope`, `spot_perp_basis_selected_gate=false`, `visible_collect_preview_command=trading_structural_branch_planonly.ps1 -Json`.
- `trading_branch_selector.ps1 -Json` показывает `decision=SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE`, `selected_branch=next_non_hft_structural_branch`.
- `trading_next_goal_step.ps1 -Json` показывает primary command `trading_structural_branch_planonly.ps1 -Json` без user approval и без actual collect.
- `python -m unittest trading_mvp.tests.test_visible_ws_collect_wrapper` => 26 tests OK, 4 skipped.
- `git diff --check` по измененным роутерам/тесту => OK.

## Риски и ограничения
- Gate намеренно оставлен в состоянии `SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE`; он не обновлен на slow-ветку автоматически, чтобы не фиксировать новый active branch до отдельного slow PlanOnly scaffold.
- `slow_liquidity_regime_breakout_retest` пока выбран только как следующий PlanOnly-кандидат; это не доказанная стратегия и не разрешение на collect/replay/grid/live/API/paper-forward.
- Spot/perp ветка отброшена на текущем public probe; повторять ее без изменения venue mapping/coverage бессмысленно.

## Следующий шаг
Построить read-only `slow_liquidity_regime_breakout_retest` PlanOnly scaffold: regime labels, OHLCV/spread data requirements, base/VIP0 cost hurdle, OOS/walk-forward/stress/economics gates. До этого не запускать collect/replay/grid/live/API/paper-forward.
