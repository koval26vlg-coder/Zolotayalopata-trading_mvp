# trading_mvp Fast-First v3 evaluator ready

Date: 2026-07-13
Agent: Codex, manual mode; swarm disabled

## Scope

Implement and test the frozen hash-bound no-grid evaluator for `venue_local_lottery_max_factor_v1`. Do not run real OOS.

## Implementation

- Added `trading_mvp/src/lottery_max_evaluator.py`.
- Added `fast-edge-v3-validate` and guarded `fast-edge-v3-evaluate` actions to `trading_mvp/run_mvp.ps1`.
- Evaluation supports exactly one frozen configuration and two predetermined score views: raw `MAX20` and the residualized robustness score.
- Inputs are bound to canonical plan hash plus the 195-file Merkle seal.
- Daily features use only bars closed by signal date; bars after the frozen `2026-07-12` close are excluded.
- Portfolio execution is four legs/eight orders, next open to fifth close, five-day non-overlap, discrete funding settlements and unified normal/stress costs.
- Verdict order is fail-closed: data sufficiency before performance, then all OOS/walk-forward/stress/economics/concentration/capacity gates.
- Direct evaluation is blocked unless an owned visible gate has `FAST_FIRST_V3_EVALUATION_RUNNING` and a matching `RunId`.

## Verification

- TDD red state observed: module import failed before implementation.
- Evaluator tests: 10 passed.
- Targeted regression: 55 passed.
- Full regression with project Python `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe`: 549 passed, 5 skipped, 0 failed.
- The first full-suite attempt used the bundled Python without `requests`; its import errors were an environment-runner failure, not accepted verification. The suite was rerun successfully with the project venv.
- Python compile, PowerShell parser and diff-check passed.
- Real validation-only seal check: 195/195 files, matching Merkle, zero mismatches.
- Direct evaluation negative smoke: blocked before OOS access.
- Forbidden evaluation artifact was not created.

## State

- Readiness: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v3\manifests\fast_first_v3_lottery_max_evaluator_readiness_20260713.json`.
- Gate decision: `FAST_FIRST_V3_EVALUATOR_READY_OOS_NOT_RUN`.
- OOS metrics, signals, PnL and verdict remain unobserved.
- `evaluation_allowed=false`; probe/paper/live/API keys/leverage remain false.

## Handoff

Do not auto-start OOS. Only after a new explicit user request, prepare an owned visible no-grid evaluation run. Do not retune the frozen parameters or launch grid search.
