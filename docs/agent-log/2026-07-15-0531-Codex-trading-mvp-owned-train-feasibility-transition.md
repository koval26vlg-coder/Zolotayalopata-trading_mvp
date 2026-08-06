# trading_mvp owned train-feasibility transition

Дата: 2026-07-15 05:31 Europe/Volgograd  
Автор: Codex

## Состояние

- Active run gate открыт: последний PIT segment final, `36/36` cycles, `61,092` rows, `0` errors.
- Append-only train ledger: `2/20` distinct quality-accepted dates.
- Active immutable schedule: `34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362`.
- Следующая новая дата: `pit_universe_v2_forward_20260716_n03`; `authorize-segment=AUTHORIZED`.

## Изменения

- Реализован visible owned wrapper `tools/run_pit_train_feasibility_visible.ps1`.
- Добавлен scoped owned-run bypass в `trading_mvp/run_mvp.ps1` только для `fast-edge-pit-input-plan` и `fast-edge-pit-feasibility` с совпадающим `RunId` и gate decision.
- Wrapper выполняет два deterministic train-only feasibility повтора, проверяет embargo/provenance и закрывает timeout/nonzero как `STOPPED_INCOMPLETE`.
- Synthetic `20/20` end-to-end worker прошел полностью: два одинаковых `FEASIBLE_FOR_OOS` result hash, `20` train dates, `0` OOS dates, custom gate final `READY_FOR_POSTPROCESS`, реальный project gate не изменен.
- Исправлены две orchestration ошибки, найденные end-to-end тестом: чтение `plan_stage` из `sealed_input` и repeat через один canonical output path с ротацией immutable artifacts.
- Heartbeat `pit-visible-night-segments` останавливает train accrual на `20/20`, запускает wrapper один раз в видимом терминале и не запускает OOS автоматически.

## Проверка

- `test_pit_train_feasibility_visible`: `7 OK`.
- Pipeline/gate shard: `79 OK`.
- Full regression: `682 OK`, `5 skipped`, `261.105s`.
- PowerShell parse: OK.
- PlanOnly smoke: read-only, `network_access=false`, `oos_returns_read=false`, `grid_search=false`, `retune=false`.
- Canonical goal SHA-256: `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.

## Ограничения

- Реальный train feasibility не запускался, потому что текущий ledger только `2/20`.
- OOS, returns, PnL, grid, retune, probe, paper-forward, live orders, API keys, leverage и margin не запускались.
