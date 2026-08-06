# trading_mvp PIT v1.2 staged proof pipeline

Timestamp: 2026-07-14 20:32:51 +03:00
Agent: Codex

## Canonical goal

- Canonical file: `C:\Users\koval\Documents\ZolotyayLopata\docs\plans\2026-07-14-trading-mvp-canonical-goal-v3.md`.
- Canonical and user attachment are byte-identical, SHA-256 `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.
- The canonical file was not modified.

## Corrected proof semantics

- Contract version: `pit_universe_membership_drift_reversion_v1.2.0`.
- Contract hash: `178f63b1585569538d180f6fc2fa7d570f060fdcc292a107c7cd30656a6eb595`.
- Daily observations aggregate the last two consistent cycles per quality-certified local date; calendar gaps break event and position sequences.
- PnL uses executable BBO on both legs. Embedded BBO spread is not charged twice.
- True break-even is the first non-negative cumulative net point.
- Snapshot rows include funding, mark/index, contract metadata, quantity constraints and BBO sizes.
- Final artifacts bind git HEAD, runtime versions, fee provenance, split definition and all input hashes.

## Staged evidence gate

1. Accumulate at most 20 accepted train dates.
2. Freeze a `train_feasibility` input plan containing no OOS rows.
3. Run train-only feasibility.
4. Stop the branch on `INFEASIBLE_ON_CURRENT_DATA`.
5. Only `FEASIBLE_FOR_OOS` permits a separate 100-day OOS collection and `full_evaluation` plan.

The current 14-night tranche cannot reach the train gate. A later six-night tranche requires its own explicit approval. No OOS accrual is allowed before feasibility.

## Current immutable schedule

- Path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_203246.json`.
- Plan hash: `7212be6dc9adc25916ace8fe3c2987df303a049b849dce76a0ccf24f765325e5`.
- File SHA-256: `abbc2579480a4e9e17cd3e2c4c1cdd9e1e14f2e0a3b3a1b2d10326aa7ee33314`.
- Window: 14 visible 20-minute segments from `2026-07-14T23:00:00+03:00` through `2026-07-27T23:20:00+03:00`; last hard deadline `2026-07-28T07:00:00+03:00`.
- State: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`, zero completed segments, no collection started.
- Older schedules `b5ad5616...`, `2c484b7b...`, `8fa86b...` and `bce81a...` are superseded.

## Verification

- Full regression: 657 tests passed, 5 skipped.
- Static verification: Python compile, PowerShell parser and `git diff --check` passed.
- Current schedule validation repeated twice with identical `VALID` verdict.
- Canonical goal hash rechecked after implementation.
- No collector, network request, OOS read, grid, retune, probe, paper-forward, live order, API key, leverage or margin action occurred.

## Boundary

The project goal remains active. The only market-writing next action is exact explicit approval of the current schedule. PlanOnly engineering and short deterministic local verification do not authorize collection.
