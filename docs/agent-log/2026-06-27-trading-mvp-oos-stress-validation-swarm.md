# trading_mvp OOS/Stress Validation + Swarm Checkpoint

Дата: 2026-06-27 11:22 +03:00
Агент: Codex
Запрос пользователя: использовать `Рой` и продолжить цель trading_mvp.

## План

- Проверить active-run gate.
- Подключить `Рой` для независимого checkpoint.
- Реализовать локальный research-only validation tooling.
- Проверить тестами и acceptance gates.
- Зафиксировать следующий шаг цели без hidden/background long runs.

## Что сделано

- Active-run gate: `READY_FOR_POSTPROCESS`, 2016/2016 cycles, 50583 rows, 657 errors.
- Создан и завершен workflow `2026-06-27-110635-774802-trading-mvp-oos-stress-checkpoint`.
- L1 Antigravity CLI: approve.
- L2 Antigravity CLI: approve.
- L3 Codex: реализация tooling.
- L4 Codex: architecture/risk handoff.
- L5 Claude Code: final-report approve.
- Risk gate passed только для research-only результата; paper/live/long collect остаются заблокированы.

## Измененные файлы

- `trading_mvp/src/event_validation.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_event_validation.py`
- `tools/sweep_reversal_acceptance_gate.ps1`
- `tools/trading_next_goal_step.ps1`
- `docs/plans/2026-06-27-spot-maker-sweep-reversal-proof-plan.md`
- `exports/trading-mvp/analysis/spot_maker_sweep_reversal_next_branch_20260627.json`

## Созданные артефакты

- `exports/trading-mvp/backtests/event_validation_6h_duration_20260614_181422.json`
- `exports/trading-mvp/funding/funding_collect_diagnostics_7d_spotliq_visible_20260617_185732.json`
- `exports/trading-mvp/analysis/sweep_reversal_acceptance_gate_20260627.json`
- `D:\AionUi-Paperclip\docs\agent-workflows\2026-06-27-110635-774802-trading-mvp-oos-stress-checkpoint\final-report.md`

## Проверки

- RED: `test_event_validation` сначала падал с `ModuleNotFoundError: event_validation`.
- Focused tests: `C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_event_validation trading_mvp.tests.test_event_labeler trading_mvp.tests.test_event_slicer` -> 10 OK.
- Full tests: `C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp/tests` -> 194 OK.
- `event-validation-report`: accepted=false; reasons=`oos_rejected`, `walk_forward_rejected`, `stress_rejected`.
- `sweep_reversal_acceptance_gate`: accepted=false; fail_count=15; decision=`SWEEP_REVERSAL_RESEARCH_NOT_ACCEPTED_NEEDS_INDEPENDENT_DATA`.
- `trading_edge_preflight`: ok=true, status=`READY_FOR_EDGE_PROOF_STEP`.
- `trading_next_goal_step`: decision=`SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT`.

## Итог

Sweep/reversal на текущих данных не принят. Это research-only rejection, а не готовая стратегия.

Ключевые метрики отказа:

- event target_before_stop_rate=0.367 < 0.60;
- false_sweep_rate=0.741 > 0.50;
- OOS selected_events=7;
- OOS target_before_stop_rate=0.5;
- walk-forward accepted_windows=0/4;
- stress target_before_stop_rate=0.0;
- v2 execution: 10 trades, winrate=0.1, net_pnl=-0.3901, PF=0.0878.

## Риски и ограничения

- Не тюнить текущий thin/old dataset, чтобы протолкнуть edge.
- Не запускать long collect без явного подтверждения пользователя.
- Live/API/leverage/margin/paper-forward остаются заблокированы.
- Funding diagnostics характеризует data-quality ошибки, но не является trade signal.

## Следующий агент

Перед любым действием снова проверить `tools/check_active_run_gate.ps1`.
Если пользователь хочет продолжить, следующий безопасный шаг:

`pwsh -NoProfile -ExecutionPolicy Bypass -File tools/start_ws_collect_visible.ps1 -Hours 6 -PlanOnly`

Запуск без `-PlanOnly` только после явного подтверждения пользователя и в видимом терминале/monitor.
