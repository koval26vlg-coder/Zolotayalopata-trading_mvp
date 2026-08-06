# trading_mvp PIT evaluator and schedule reseal

Timestamp: 2026-07-14 19:32:58 +03:00
Agent: Codex

## Request

Use `docs/plans/2026-07-14-trading-mvp-canonical-goal-v3.md` as the canonical project goal and continue the proof pipeline without reading OOS before the evaluator is frozen.

## Result

- Preserved the canonical goal byte-for-byte; SHA-256 `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.
- Froze `pit_universe_membership_drift_reversion_v1.1.0` before market collection.
- Increased the evidence contract to 20 train plus 100 untouched OOS dates and five non-overlapping 20-day OOS folds.
- Added immutable input planning, quality-ledger and artifact hash verification, train-only feasibility, Wilson projections, guarded no-grid OOS, deterministic repeat, normal/robustness/stress economics, capacity/drawdown/concentration checks and fail-closed verdicts.
- Added PowerShell actions `fast-edge-pit-input-plan`, `fast-edge-pit-feasibility` and `fast-edge-pit-evaluate`.
- Sealed the evaluator hash into the night schedule runtime tool set.
- Superseded old plan `2c484b7b...`, which now fails closed on hypothesis-bank provenance mismatch.
- Generated current unapproved plan `b5ad5616983a9c807b9159067294045f7ca87f27dab343b39f0b91572d2a9c58` at `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_193046.json`.

## Verification

- Targeted tests: 56 passed.
- Full regression: 654 passed, 5 skipped.
- Python compile: passed.
- PowerShell parser: passed.
- `git diff --check`: passed.
- Schedule validation repeated deterministically: valid.
- No collector, network request, OOS read, grid, probe, paper-forward, live order or API-key action was started.

## Current boundary

Status is `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`. The 14-night tranche contributes at most 14 of 120 required quality dates. Approval and visible market collection remain a separate explicit boundary.
