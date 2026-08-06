# Codex trading_mvp public probe status readback

Дата: 2026-07-09 11:38:20 +03:00
Агент: Codex
Исходный запрос: продолжить активную цель; goal-context указывал cross-venue full scan, но active-run-gate требует spot/perp public probe confirmation.

## План
- Проверить Aion bootstrap и active-run-gate.
- Не запускать full scan/public probe без явного подтверждения.
- Сделать status/readback самодостаточным по public-probe confirmation gate.

## Сделано
- Обновлен 	ools/check_active_run_gate.ps1: теперь JSON-статус показывает:
  - equires_explicit_user_approval_for_public_probe
  - last_spot_perp_basis_public_probe_output_path
  - last_spot_perp_basis_public_probe_decision
  - last_spot_perp_basis_public_probe_confirmed
- Actual public REST probe не запускался.
- Cross-venue full scan не запускался, потому что текущий gate требует другой шаг.

## Проверки
- PowerShell parser OK: check_active_run_gate.ps1, routing scripts, public-probe wrapper.
- Unit smoke OK: 	est_spot_perp_basis_public_probe - 5 tests.
- Gate smoke OK: equires_explicit_user_approval_for_public_probe=true, last_spot_perp_basis_public_probe_confirmed=false.

## Следующий шаг
- Только после явного подтверждения пользователя выполнить ctive-run-gate.json.command_after_explicit_approval.
- До этого не запускать collect/replay/grid/full scan/live/API/paper-forward.
