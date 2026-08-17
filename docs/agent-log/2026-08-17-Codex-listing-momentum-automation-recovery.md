# Listing Momentum — recurring automation и recovery

Дата: 2026-08-17
Агент: Codex

## Automation

Создана heartbeat automation в Codex app:

- automation id: `zolotyaylopata-listing-momentum-monitor`
- name: `ZolotyayLopata Listing Momentum Monitor`
- status: `ACTIVE`
- cadence: каждые 6 часов, слоты 00:00/06:00/12:00/18:00
- target thread: `01a00fb6-6f6e-7b62-88f3-7f0e5c829962`
- readback: `C:\Users\koval\.codex\automations\zolotyaylopata-listing-momentum-monitor\automation.toml`

Automation запускает только:

`tools/start_listing_momentum_forward_automation_visible.ps1 -ScheduledTick -Json`

Orchestrator последовательно запускает MEXC + Gate v2 и затем отдельный Binance + Bybit + OKX + Bitget expansion. Параллельные writers запрещены; каждый запуск видимый и bounded.

## Recovery contract

При ошибке preflight, gate, claim, Python, plan, network, timeout или writer:

- текущая попытка фиксируется в `docs/agent-log/run-gates/listing_momentum_forward_automation_attempts.jsonl`;
- состояние получает `RETRY_NEXT_INTERVAL`, `pending_retry=true`, `next_interval_at_utc`;
- немедленный retry/busy-loop не выполняется;
- следующий scheduled fire повторяет deferred/failed track;
- partial success получает `PARTIAL_RETRY_NEXT_INTERVAL`, а failed track остаётся в очереди;
- automation не переводится в `PAUSED` и не считается terminal.

## Immutable bindings

- expansion PlanOnly hash: `f4a7c0a9dfe955f65064ad5effc28918262e3564bc52b6f69cedd1b614ae9de6`
- expansion PlanOnly file SHA-256: `5ed7b8533162a18f8938a2b4ed7e6dd03690c16886ef294fb88d24ce3f294507`
- automation launcher SHA-256: `9931f4a6969134b969e8bfc2ede76041dc185320ada33e1e876dad3b07f4847b`
- v2 PlanOnly hash: `d98d402fb08065bef58859522b938ec064b2bc4a223f269aa0218cce502e5afb`
- expansion preflight receipt hash: `fb4be6e1d02a2a276f52d518004c6396d6ae4e7bb706e5bda3f759f09f2aa8b9`

## Verification

- automation PowerShell parse: `AUTOMATION_PS_PARSE_OK`
- Python compile: `PY_COMPILE_OK`
- relevant regression suite: `29 passed`
- combined scheduler `-PreflightOnly -Json`: both tracks `ok=true`, gate `READY_FOR_POSTPROCESS`
- synthetic failure injection with missing plan files: `RETRY_NEXT_INTERVAL`, `pending_retry=true`, next interval `2026-08-17T21:00:00Z`; temporary test directory removed
- current automation `-Status -Json`: `IDLE`, no worker, no pending retry before first scheduled fire

No new market-data tick was launched by this change; the next launch is owned by the active automation schedule.
