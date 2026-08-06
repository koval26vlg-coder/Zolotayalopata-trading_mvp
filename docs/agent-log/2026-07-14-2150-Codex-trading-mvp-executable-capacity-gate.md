# trading_mvp executable-capacity gate v1.3.0

## State

- Canonical goal: `docs/plans/2026-07-14-trading-mvp-canonical-goal-v3.md`.
- Canonical goal SHA-256: `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.
- Active gate at start: `READY_FOR_POSTPROCESS`; old v6 track closed, no live process.
- No collector, public/execution probe, OOS, grid, paper-forward, live order or API-key action was started.

## Critical findings fixed

1. The evaluator used a fraction of 24h volume as capacity evidence. Contract v1.3.0 now requires actual top-of-book quantity on both venues at entry and exit and rejects missing/insufficient capacity.
2. MEXC bulk ticker does not contain BBO quantity. The public-probe client now enriches only dual-venue eligible MEXC contracts from `contract/depth/{symbol}` with rate pacing; Gate quantity remains sourced from its public ticker.
3. Depth failures were not part of collector health. Cycle journals/manifests now expose targets, complete count, coverage, per-symbol errors, cumulative depth errors and depth-error cycles.
4. Train feasibility incorrectly advertised direct OOS as the next action. It now permits only a separately sealed `oos_accrual` schedule PlanOnly.
5. Final-route text was not a single verified command. Plans/results now carry `next_allowed_command`; input-plan validation recomputes it and fails on tampering.
6. Sequential MEXC depth requests could stretch a cycle or hang on network timeouts. Depth enrichment now has a 120-second cycle budget, fails closed for unqueried symbols, and collector cadence is start-to-start.

## Current immutable proposal

- Path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_220219.json`.
- Plan hash: `34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362`.
- File SHA-256: `b1d4264fc577dd84464389b151361bcdfd42a13d56bb67390fc75b516b0071f2`.
- Contract: `pit_universe_membership_drift_reversion_v1.3.0`, hash `b5e3abd4942fc117b92c324e931d8d91671df3de99b403875bcf38983c26d857`.
- Quality policy: `pit_universe_v2_segment_quality_v3`, minimum dual-venue BBO-size coverage `0.95`.
- State: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`; 14 planned segments; accepted train dates `0/20`; collection not started.
- Status artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_status_20260714_220219.json`.
- Superseded plans `b53c4b9e...` and `29d02a46...` fail current provenance validation.

## Verification

- Targeted branch suite: 97 passed.
- Full suite: 671 passed, 5 skipped.
- Python compile: passed.
- PowerShell parser: passed for unified wrapper, approval script and visible collector wrapper.
- `git diff --check`: passed.
- New schedule validated twice; first segment stage authorization returned `AUTHORIZED`.

## Next boundary

Only the exact schedule approval may create an approval record. Approval itself does not start collection. After approval, only the currently due 20-minute segment may run in a visible terminal. Generic continuation text is not schedule approval.
