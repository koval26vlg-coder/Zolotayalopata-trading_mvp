# trading_mvp Edge Goal V3 Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Найти, доказать или честно отбросить рабочий non-Binance trading edge с положительным net expectancy после базовых издержек.

**Architecture:** Проект двигается только через gate pipeline: data quality -> detector/full scan -> OOS/walk-forward/stress -> economics -> paper-forward readiness. Текущая ветка — MEXC/Gate cross-venue spot dislocation на существующем clean WS slice; live orders, API keys, leverage/margin и grid запрещены до отдельного acceptance gate.

**Tech Stack:** Python 3.13, PowerShell wrappers, normalized WS JSONL, `trading_mvp/src/cross_venue_dislocation.py`, `trading_mvp/run_mvp.ps1`, artifacts in `exports/trading-mvp`.

---

### Task 1: Run Visible Full Cross-Venue Scan

**Files:**
- Read: `docs/agent-log/active-run-gate.json`
- Read: `exports/trading-mvp/normalized/ws_market_filtered_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.jsonl`
- Write: `exports/trading-mvp/backtests/cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json`

**Step 1: Verify active gate**

Run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1 -Json
```

Expected: `status=READY_FOR_POSTPROCESS` and `next_goal_decision=CROSS_VENUE_DISLOCATION_SMOKE_DONE_NEEDS_VISIBLE_FULL_SCAN`.

**Step 2: Start visible full scan**

Run in visible terminal:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1" -Action cross-venue-dislocation -InputPath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_market_filtered_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.jsonl" -OutputPath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json" -CrossVenueProgressEveryRows 1000000 -CrossVenueMaxEvents 1000
```

Expected: terminal prints progress every `1,000,000` rows.

**Step 3: Interpret full scan**

Acceptance to continue this branch:

```text
eligible_events > 0
max_net_edge_bps > 0
events not concentrated in one tiny stale/liquidity artifact
candidate capacity is economically meaningful after base-tier fees
```

If not met: reject or park cross-venue dislocation under current base-fee assumptions.

---

### Task 2: Build Validation Only If Full Scan Passes

**Files:**
- Create/modify only after Task 1 passes: validation module and tests for cross-venue events.

**Step 1: Add OOS split**

Split events by time: train 70%, OOS 30%.

Expected: selected thresholds from train must survive OOS without better assumptions.

**Step 2: Add walk-forward**

Use rolling windows and require majority pass ratio.

Expected: no single-window or single-market artifact can pass.

**Step 3: Add stress**

Stress base assumptions:

```text
fee +5 bps
slippage +5 bps
stale_quote_sec tighter
min_top_notional_quote higher
venue concentration cap
```

Expected: edge remains positive after stress, otherwise reject.

---

### Task 3: Economics Gate

**Files:**
- Write: `exports/trading-mvp/backtests/cross_venue_dislocation_economics_*.json`

**Step 1: Calculate real constraints**

Include:

```text
base-tier fees
inventory split across MEXC/Gate
rebalance/withdrawal latency
API reliability
top-of-book capacity
capital lockup
venue/counterparty risk
```

**Step 2: Decide readiness**

Accepted only if expected net value remains positive after operational costs.

---

### Task 4: Paper-Forward Readiness Gate

**Files:**
- Create only after validation/economics pass.

**Step 1: Create paper-forward plan**

No live orders. No API keys. Use public data or paper-only simulation.

**Step 2: Define kill criteria**

Reject if forward net expectancy, event frequency, fill feasibility, or venue stability fail.

---

### Current Branch State

Implemented:

```text
cross_venue_dislocation.py
CLI command: cross-venue-dislocation
PowerShell wrapper support
unit tests
200k-row smoke
```

Smoke result:

```text
rows_read=200000
bbo_rows=106493
matched_bases=12
candidate_events=101
eligible_events=0
max_gross_edge_bps=5.32197977647586
max_net_edge_bps=-63.67802022352414
decision=REJECTED_NO_NET_EDGE_AFTER_BASE_FEES
```

This smoke is not enough to reject the branch because it is truncated, but it already shows the cost hurdle is severe.
