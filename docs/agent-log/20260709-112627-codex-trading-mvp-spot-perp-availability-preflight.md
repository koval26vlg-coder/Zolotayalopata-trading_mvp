# Codex trading_mvp spot/perp availability preflight

Дата: 2026-07-09 11:26:27 +03:00
Агент: Codex
Исходный запрос: пользователь подтвердил visible listing-event OHLCV history collect; active gate показал, что collect уже завершен и текущий разрешенный шаг - spot/perp basis availability preflight PlanOnly.

## План
- Проверить active-run-gate перед действиями.
- Не запускать повторный listing-event collect, так как run уже завершен.
- Довести spot/perp basis availability preflight PlanOnly.
- Обновить routing/status/selector и gate.

## Сделано
- Подтверждено, что listing-event collect listing_event_history_collect_bitget_accepted_20260709_092116 завершен: 2554 OHLCV строки, 36 requests, 0 errors.
- Реализован/подключен spot_perp_basis_availability_preflight для ветки spot_perp_basis_mean_reversion_no_funding.
- Gate обновлен до SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE.
- Preflight нашел 34 non-Binance candidate bases с MEXC+Gate coverage.
- Все required fields доступны через public API endpoint contracts, но existing daily files не backtest-ready.

## Измененные файлы
- 	rading_mvp/src/spot_perp_basis_availability.py
- 	rading_mvp/tests/test_spot_perp_basis_availability.py
- 	ools/trading_spot_perp_basis_availability_preflight.ps1
- 	ools/trading_next_goal_step.ps1
- 	ools/trading_goal_status.ps1
- 	ools/trading_branch_selector.ps1
- docs/agent-log/active-run-gate.json

## Проверки
- PowerShell parser OK: next_goal_step, goal_status, branch_selector, availability_preflight wrapper.
- Unit tests OK: 	est_spot_perp_basis_availability, 	est_spot_perp_basis_mean_reversion - 10 tests.
- Readback OK: gate/status/selector согласованы на ожидание explicit confirmation для short visible public REST probe.

## Артефакты
- $artifact

## Риски и ограничения
- Это PlanOnly/public-data availability stage, не торговля.
- collect_allowed_now=false, eplay_allowed_now=false, grid_allowed_now=false, live_orders=false, pi_keys=false, leverage_or_margin=false, paper_forward_allowed=false.
- Следующий шаг требует явного подтверждения пользователя: короткий visible public REST probe по paired spot/perp fields; не actual collect/backtest/grid.
