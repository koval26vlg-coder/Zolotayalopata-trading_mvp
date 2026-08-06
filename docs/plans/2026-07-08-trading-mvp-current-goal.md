# trading_mvp Current Goal Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Найти, доказать или честно отбросить рабочий non-Binance trading edge с положительной net expectancy после базовых комиссий, OOS/walk-forward/stress/economics gates и paper-forward gate до любого live.

**Architecture:** Цель ведется как gate-driven research pipeline: каждый следующий шаг читает `docs/agent-log/active-run-gate.json`, выполняет только разрешенное действие и блокирует replay/grid/live/API keys до прохождения соответствующего data-quality/acceptance gate. Текущая активная ветка: `listing_event_drift_reversal`, потому что текущий clean WS slice не содержит временного overlap по listing events; следующий шаг требует отдельной истории OHLCV по событиям листинга.

**Tech Stack:** Python standard library, PowerShell wrappers, локальные JSON/CSV artifacts, public market data only.

---

### Task 1: Keep Goal Gate As Source Of Truth

**Files:**
- Read: `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json`
- Run: `C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1`

**Step 1: Check gate before any work**

Run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1 -Json
```

Expected: `READY_FOR_POSTPROCESS` or an explicit blocked state.

**Step 2: If gate is RUNNING**

Do only status/ETA checks. Do not run postprocess, grid, replay, collectors, broad analysis or code edits.

**Step 3: If gate is STOPPED_INCOMPLETE**

Resume visibly or explicitly reject the incomplete dataset before continuing.

### Task 2: Current Branch State

**Files:**
- Read: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_history_collect_preview_20260708_210753.json`
- Read: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\listings\non_binance_listing_events.csv`
- Read: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json`

**Current evidence: cross-venue branch is rejected**

The prior cross-venue MEXC/Gate spot-dislocation full scan is not the current next action anymore.

Evidence:

```text
mode= cross_venue_dislocation_planonly_research
decision= REJECTED_NO_NET_EDGE_AFTER_BASE_FEES
rows_read= 51278447
bbo_rows= 36039132
matched_bases= 12
candidate_events= 2266
eligible_events= 0
max_gross_edge_bps= 66.34150236553671
max_net_edge_bps= -2.658497634463288
scan_complete= true
```

Implication: do not re-run replay/grid for this cross-venue artifact. Treat it as rejected under base/VIP0/no-volume fees unless a future branch explicitly changes the cost model with verified non-secret fee-tier evidence.

**Step 1: Confirm preview**

Run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1 -Json
```

Expected decision:

```text
LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL
```

**Step 2: Respect blocked actions**

Do not start actual collect, replay, grid, paper-forward, live orders, API keys, leverage or margin from this state.

### Task 3: Next Step After User Approval

**Files:**
- Create/modify later: public OHLCV listing-event history collector wrapper
- Use contract from: `C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\src\listing_event_history_collect_plan.py`
- Approval packet: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\listing_event_history_collect_approval_packet_current.json`
- Approval verifier: `C:\Users\koval\Documents\ZolotyayLopata\tools\trading_listing_event_history_collect_approval_packet.ps1`

**Step 0: Verify approval packet before implementation/run**

Run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_listing_event_history_collect_approval_packet.ps1 -Json
```

Expected:

```text
status=READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET
would_start=false
collect_allowed_now=false
replay_allowed_now=false
grid_allowed_now=false
start_requires_exact_user_input=подтверждаю visible listing-event OHLCV history collect
```

**Step 1: Implement visible collector only after explicit approval**

The collector must use public REST data only and write:

```text
exports/trading-mvp/listing-history/<run_id>/ohlcv.jsonl
exports/trading-mvp/listing-history/<run_id>/manifest.json
exports/trading-mvp/listing-history/<run_id>/event_plan.json
```

**Step 2: Preserve survivorship controls**

Selected delisted/non-tradable events stay in the manifest even when candles are missing. Missing data is `data_status=no_data_or_delisted`, not a silently dropped event.

**Step 3: Use visible execution**

Any long-running collector must run in a visible terminal or visible monitor and must expose progress, line count, last write, errors and ETA.

### Task 4: Only After History Data Completes

**Files:**
- Future output: listing history manifest
- Existing normalizer: `C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\src\listing_event_normalizer.py`

**Step 1: Run data-quality checks**

Verify exchange coverage, missing-data rate, candle continuity, duplicate rows, timestamp ordering and per-event availability.

**Step 2: Re-run listing-event normalizer**

Only if the history manifest passes data-quality.

**Step 3: Replay remains blocked until gate allows**

No replay/grid until the normalizer produces sufficient event coverage and explicit `replay_allowed=true`.

### Task 5: Acceptance Criteria

**Files:**
- Test command target: `C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\tests`

**Step 1: Keep tests green**

Run:

```powershell
C:\Program Files\Python313\python.exe -m unittest discover -s C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\tests
```

Expected: full suite passes.

**Step 2: Research acceptance remains strict**

A branch can proceed toward paper-forward only if it passes sample-size, OOS/walk-forward, stress, economics, slippage/fill and base-fee gates. Win rate alone is not acceptance.
