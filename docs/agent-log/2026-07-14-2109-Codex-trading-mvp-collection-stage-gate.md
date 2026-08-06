# trading_mvp collection-stage gate

Date: 2026-07-14 21:09 Europe/Volgograd
Agent: Codex

## Finding

The staged feasibility policy existed in quality-report wording but was not enforced at every planning, approval and segment-start boundary. A stale or oversized schedule could therefore continue collecting beyond 20 train dates, and the planner did not seal its own implementation hash.

## Fix

- Added explicit `train_accrual` and `oos_accrual` stages to schedule schema v2.
- Sealed the quality-ledger path, initial accepted certifications, stage target, remaining-date cap and schedule-planner source hash.
- Added `authorize-segment`; approval and the visible wrapper invoke it before any market-writing segment.
- Train collection stops at 20 accepted dates. OOS collection requires a hash-valid train plan and `FEASIBLE_FOR_OOS` artifact that read no OOS data.
- Bound the quality certifier to the ledger sealed in the schedule and exposed stage progress in technical status.
- Replaced `ZoneInfo` with a fixed UTC+03:00 Volgograd timezone to avoid an undeclared runtime `tzdata` dependency.

## Evidence

- Current plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_210928.json`
- Plan hash: `b53c4b9e8049694c992178664da85e650ecfe9f1bcfd314d7957862e7e4fef51`
- File SHA-256: `26046d62fddd007b8e6e361beca7285df5af042312c4c7cd62d4b7f6b4f477a8`
- Contract: `pit_universe_membership_drift_reversion_v1.2.0`, hash `178f63b1585569538d180f6fc2fa7d570f060fdcc292a107c7cd30656a6eb595`
- Stage: `train_accrual`; accepted dates `0/20`; 14 segments; collection not started.
- Current plan validated twice and first segment returned `AUTHORIZED` with 20 dates remaining.
- Superseded plan `7212be6d...` failed closed with `Expected fast_first_night_schedule_plan_v2 PlanOnly artifact`.
- Full regression: 662 tests passed, 5 skipped.
- Static checks: Python compile, PowerShell parse and `git diff --check` passed.

## Boundary

No collector, network request, OOS read/evaluation, grid search, execution probe, paper-forward, live order, API key, leverage or margin action was started. The next market-writing action remains exact explicit approval of the current immutable visible schedule.
