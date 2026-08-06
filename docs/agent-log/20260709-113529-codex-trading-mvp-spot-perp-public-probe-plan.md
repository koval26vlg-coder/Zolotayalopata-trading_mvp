# Codex trading_mvp spot/perp public probe PlanOnly

Дата: 2026-07-09 11:35:29 +03:00
Агент: Codex
Исходный запрос: продолжить цель; goal-context упоминал cross-venue full scan, но active-run-gate указал текущий разрешенный шаг SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE.

## План
- Проверить Aion bootstrap и active-run-gate.
- Не запускать cross-venue full scan, collect, replay, grid, live/API, так как текущий gate требует spot/perp public probe confirmation.
- Подготовить безопасный PlanOnly wrapper для короткого public REST probe.
- Обновить routing и gate командой после явного подтверждения.

## Сделано
- Добавлен 	rading_mvp/src/spot_perp_basis_public_probe.py.
- Добавлен 	ools/trading_spot_perp_basis_public_probe.ps1.
- Добавлены unit tests 	rading_mvp/tests/test_spot_perp_basis_public_probe.py.
- Обновлены 	ools/trading_next_goal_step.ps1, 	ools/trading_goal_status.ps1, 	ools/trading_branch_selector.ps1.
- Gate дополнен command_after_explicit_approval для запуска confirmed public probe.
- Выполнен только PlanOnly: would_start=false, confirmed_public_probe=false, candidate_count=10.

## Проверки
- PowerShell parser OK для измененных wrapper/routing scripts.
- Unit tests OK: 15 tests.
- Readback OK: gate/status/next_goal_step/branch_selector показывают ожидание явного подтверждения и confirmed command.

## Артефакты
- $artifact

## Ограничения
- Actual public REST probe не запускался.
- Cross-venue full scan не запускался, потому что это конфликтует с текущим active gate.
- collect_allowed_now=false, eplay_allowed_now=false, grid_allowed_now=false, live_orders=false, pi_keys=false, leverage_or_margin=false, paper_forward_allowed=false.

## Следующий шаг
- После явного подтверждения пользователя запустить команду из ctive-run-gate.json.command_after_explicit_approval.
