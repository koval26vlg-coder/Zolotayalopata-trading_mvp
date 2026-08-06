# Codex active gate row summary fix

Дата: 2026-07-09 13:00 +03:00
Агент: Codex
Запрос: продолжить активную цель без public probe confirmation.

## Gate перед работой
- status: READY_FOR_POSTPROCESS
- next_goal_decision: SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE
- replay_allowed: false
- requires_explicit_user_approval_for_public_probe: true
- Никаких collect/replay/grid/live/API keys/paper-forward не запускалось.

## Проблема
`check_active_run_gate.ps1 -Json` показывал `rows=0`, хотя текущий listing-event output содержит 2554 строки. Причина: скрипт считал только manifest fields `rows` и `total_events`, но listing-history manifest хранит счетчик как `ohlcv_rows`.

`expected_outputs_complete=false` оставлен по смыслу: это индикатор bundle expected_outputs для validation/replay artifacts, а не признак готовности primary output.

## Что сделано
- tools/check_active_run_gate.ps1:
  - добавлен `Get-ManifestRows` с поддержкой `rows`, `total_events`, `ohlcv_rows`, `row_count`, `total_rows`, `normalized_rows` и fallback на output line_count;
  - добавлен `primary_output_complete` в JSON output;
  - `rows` теперь корректно показывает 2554 для текущего listing-history output.
- trading_mvp/tests/test_active_run_gate.py:
  - добавлен regression test для listing-history manifest с `ohlcv_rows`.

## Проверки
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_active_run_gate -> 9 OK.
- PowerShell parser for tools/check_active_run_gate.ps1 -> OK.
- tools/check_active_run_gate.ps1 -Json -> rows=2554, primary_output_complete=true, expected_outputs_complete=false, replay_allowed=false.

## Следующий шаг
Тот же: ждать явного подтверждения пользователя для short public REST probe. До подтверждения не запускать collect/replay/grid/live/API keys/paper-forward.
