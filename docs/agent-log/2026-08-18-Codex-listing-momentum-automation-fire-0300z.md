# Listing Momentum — scheduled fire 03:00Z

Дата: 2026-08-18 (UTC)
Агент: Codex

## Запуск

- automation id: `zolotyaylopata-listing-momentum-monitor`
- orchestrator: `tools/start_listing_momentum_forward_automation_visible.ps1 -ScheduledTick -Json`
- visible terminal PID: `19576`
- attempt id: `listing_momentum_automation_20260818T030157Z`
- active-run gate перед запуском: `READY_FOR_POSTPROCESS`
- preflight: оба трека `READY`
- завершение: `2026-08-18T03:02:18.018927Z`, exit code `0`
- следующий scheduled interval: `2026-08-18T09:00:00Z`

## Результат по трекам

### MEXC + Gate v2

- outcome: `COMPLETE`
- tick: `forward_tick_20260818T030159Z`
- manifest: `E:\trading_mvp\listing-momentum-forward\ticks\forward_tick_20260818T030159Z\manifest.json`
- new listings в tick: `5`
- rows в tick: `108`
- cumulative accrual: `6` ticks, `18` new-listing jobs, `273` rows, `5` windows, `0` complete windows
- state: `exports/trading-mvp/analysis/slow_liquidity_listing_momentum_forward_state_20260816.json`
- plan hash: `d98d402fb08065bef58859522b938ec064b2bc4a223f269aa0218cce502e5afb`

### Binance + Bybit + OKX + Bitget

- outcome: `COMPLETE`
- tick: `expansion_tick_20260818T030213Z`
- manifest: `E:\trading_mvp\listing-momentum-forward-expansion\ticks\expansion_tick_20260818T030213Z\manifest.json`
- new listings в tick: `0`
- rows в tick: `0`
- cumulative accrual: `3` ticks, `0` new-listing jobs, `0` rows, `0` windows, `0` complete windows
- state: `exports/trading-mvp/analysis/slow_liquidity_listing_momentum_forward_expansion_state_20260817.json`
- plan hash: `64bf88540d53cf4b9a9f37b38dc80cff3d3f6a8c2fd7ee40251ff2c84f79d516`

## Recovery/status

- automation state: `COMPLETE`, `pending_retry=false`, `retry_count=0`, `worker_pid=null`
- retry/defer reason: отсутствует; краткое сообщение `invalid next_interval_at_utc; treating this fire as due` было техническим признаком наступившего scheduled fire и очищено после успешного завершения
- combined launch record: `docs/agent-log/run-gates/listing_momentum_forward_automation.launch.json`
- attempts ledger: `docs/agent-log/run-gates/listing_momentum_forward_automation_attempts.jsonl`
- status command: `pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_listing_momentum_forward_automation_visible.ps1 -Status -Json`

Запуск был research-only, public-data-only, без evaluator/replay/OOS, private API и live orders. Automation остаётся `ACTIVE` и продолжает работу по следующему scheduled fire.
