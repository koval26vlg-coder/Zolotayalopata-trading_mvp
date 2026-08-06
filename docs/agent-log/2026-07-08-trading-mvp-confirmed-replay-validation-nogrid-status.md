# trading_mvp confirmed replay-validation NoGrid status

Дата: 2026-07-08
Агент: Codex

## Статус
- Wrapper PID `4332` завершился.
- Summary artifact создан: `exports/trading-mvp/backtests/ws_replay_validation_ws_durable_72h_2exchange_pregap_confirmed_replay_nogrid_20260708_133407.json`.
- Event artifacts созданы: event-quality, event-slice, event-validation.
- `ws_replay` artifact отсутствует, хотя summary помечает stage `ws_replay` как completed.

## Вывод
- Это несогласованность artifact-contract: wrapper не проверил существование output после stage.
- Event-validation уже отвергла ветку: `REJECTED_VALIDATION_GATE`.
- Rejection reasons: `no_train_eligible_slice`, `train_selected_rejected`, `oos_rejected`, `walk_forward_rejected`, `stress_rejected`.

## Следующий шаг
Не запускать grid/live/API/paper-forward. Сначала исправить проверку output artifacts в wrapper/run_mvp, затем либо rerun только `ws-replay` для полноты аудита, либо честно закрыть `liquidity_sweep_reversal` как rejected branch и перейти к новой research branch.
