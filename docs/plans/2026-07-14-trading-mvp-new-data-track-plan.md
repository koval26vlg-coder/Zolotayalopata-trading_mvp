# trading_mvp New Data Track Plan

Date: 2026-07-14
Status: `PIT_UNIVERSE_V2_SCHEDULE_FROZEN_AWAITING_EXPLICIT_APPROVAL`
Canonical goal: `docs/plans/2026-07-14-trading-mvp-canonical-goal-v3.md`

## Current Closure

The existing daily-data Fast-First track is closed as `NO_FAST_EDGE_ON_CURRENT_DAILY_DATA` / `NO_FAST_EDGE_FOUND` for the current input Merkle. v4, v5 and v6 are closed as `INSUFFICIENT_DATA`; retune, grid/search, execution probe, paper-forward, live/API keys, leverage and margin are not allowed for those branches.

## Purpose

Open the next track only on a new data type or a certified substantial data delta. The next track must keep the same proof discipline: frozen hypothesis, feasibility before OOS, no grid, no OOS retune, deterministic repeat, append-only verdict.

## Allowed New Data Types

1. `PIT_UNIVERSE_V2_FORWARD`: point-in-time universe membership and availability snapshots.
2. `DENSE_WS_SEGMENTED`: segmented order book/trade flow data with explicit gap accounting.
3. `LISTING_FORWARD_MONITOR`: event stream for new listings, contract activation, liquidity decay and delisting risk.
4. `FUNDING_HISTORY_EXTENSION`: deeper funding/mark/index history only if cache hash proves new coverage.

## Forbidden For This Track

- Reopening v4/v5/v6 on the same daily data.
- Reading forward-data returns before freezing hypotheses.
- New grid search or parameter hunt.
- Treating partial collector output as accepted evidence.
- Starting collectors/probes/night runs without explicit user approval.

## Required Track Sequence

1. Freeze track data contract: symbols, venues, fields, deadlines, expected coverage, output paths and hash scheme.
2. Freeze feasibility estimator before any hypothesis in the track.
3. Freeze up to three hypothesis PlanOnly artifacts before reading OOS returns for those hypotheses.
4. Run feasibility gate. If infeasible, store data requirements and do not burn OOS slot until the configured infeasible budget is exhausted.
5. Run one visible owned no-grid OOS only for a hypothesis that passes feasibility.
6. Close or advance using the canonical verdict machine.

## Frozen First Tranche

The first new-data candidate is the banked hypothesis `pit_universe_membership_drift_reversion_v1` on `PIT_UNIVERSE_V2_FORWARD`.

- Schedule artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_184844.json`
- Plan hash: `2c484b7b2cbb94ee94f87b8ae65519501d812647ef4848219abc4bf01dff1c45`
- File SHA-256: `5459ce95dfe4f13c816d83b7cd947a2282fda00759c7abd4e1700e8f1e27e0a0`
- Frozen hypothesis-contract hash: `93895bd0f765d37c3bc78e206749a81ba5b6ec9287cde427233b237559bc4db9`
- Scope: 14 nights, one 1,200-second visible segment per night, four expected cycles per segment.
- Window: `2026-07-14T23:00:00+03:00` through final hard deadline `2026-07-28T07:00:00+03:00`.
- Output: `E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2`.
- Current state: `schedule_approved=false`, `collection_started=false`.

The tranche contributes at most 14 unique dates against the 80-quality-date minimum: 20 technical-train dates and 60 untouched OOS dates. It is data accrual and data-quality evidence only; it cannot authorize OOS or prove an edge.

## Implemented Engineering Surface

The `feasibility-gate-v1` and immutable data-track PlanOnly contract generator are implemented. The generator reads only the hypothesis bank, goal hash, dataset identity, input Merkle and explicit technical feasibility counts. It does not collect market data, inspect returns, compute PnL or authorize OOS.

Runner action:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 `
  -Action fast-edge-data-track-plan `
  -Hypothesis <banked-hypothesis-id> `
  -DataType <required-data-type> `
  -Dataset <dataset-id> `
  -InputMerkleSha256 <64-hex-merkle> `
  -OutputPath <immutable-plan.json> `
  -TrainCandidateEvents <count> `
  -TrainValidEvents <count> `
  -OosCandidateEvents <count> `
  -PerVenueOosCandidateEventsJson '{"mexc":10,"gateio":10}' `
  -UniqueOosDates <count> `
  -DualVenueCoverage <0..1> `
  -CapacityProxyQuotePerSelectedLeg <quote> `
  -MaxRuntimeSec 120
```

The immutable schedule generator, one-time hash-bound approval script, visible segment wrapper, disk guard and fail-closed resume path are implemented. The schedule embeds the complete pre-registered hypothesis contract and seals runtime hashes for the wrapper, collector, approval script, status tool, quality certifier, segment-quality evaluator, hypothesis-contract validator, cost module and feasibility estimator. The embargo-safe `fast-edge-night-schedule-status` action derives the required per-night journal from plan/approval/manifest/lock metadata without reading snapshot rows, returns or PnL. The separate `fast-edge-night-schedule-quality` action certifies only completed segments and appends them to a tamper-evident cross-tranche ledger; it never reads returns/PnL or authorizes OOS.

## Next Allowed Project Action

Await the exact explicit approval of the frozen schedule. Until then no collector, public probe, OOS, grid, paper-forward, live order or API-key action is allowed. A fixture smoke or the frozen schedule itself is tooling evidence only and is not market evidence.

## 2026-07-14 Evaluator-First Supersession

The schedule `20260714_184844` and plan hash `2c484b7b...` are superseded and must not be approved. The hypothesis bank and the complete evaluator contract were strengthened before any market collection, so the old schedule now fails provenance validation by design.

Current immutable state:

- Hypothesis contract: `pit_universe_membership_drift_reversion_v1.1.0`.
- Contract hash: `e0d5057dd58ca3399169c3f74fdf11faf4d8909d44798de9749cd8c0ab29fa07`.
- Required sample: 20 technical-train dates plus 100 untouched OOS dates, with five non-overlapping 20-day OOS folds.
- Evaluator SHA-256: `a0f2f6c2eed4c39eb20261689db7cb5338349047cf5cf967b4e5a2a1ca9ef07c`.
- Current schedule: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_193046.json`.
- Current plan hash: `b5ad5616983a9c807b9159067294045f7ca87f27dab343b39f0b91572d2a9c58`.
- Current status: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`; no collector, network call, OOS read, grid, probe, paper-forward or live action has started.

After quality-ledger accrual reaches 120 accepted dates, the only permitted route is immutable input plan -> train-only feasibility -> guarded no-grid OOS. Historical acceptance is capped at `ACCEPT_FOR_SHORT_EXECUTION_PROBE`; it cannot authorize paper or live trading.
