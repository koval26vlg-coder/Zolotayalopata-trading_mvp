# trading_mvp Feasibility Gate v1

Status: `IMPLEMENTED_V1_TARGETED_TESTED`
Owner: Codex
Scope: all future Fast-First tracks after the closed daily-data track.

## Objective

Prevent burning OOS slots on hypotheses that cannot reach the frozen sample-size and coverage gates. Feasibility must be computed after PlanOnly freeze and before any OOS PnL/return metrics are read.

## Inputs

- Frozen hypothesis id and plan hash.
- Input Merkle root and cache hashes.
- Track id and data type.
- Train-only event candidate counts.
- Train-only venue/base/date coverage.
- Train-only fill-rate estimate for event eligibility.
- Frozen OOS calendar size, without reading OOS returns.
- Required gates from canonical goal.

## Forbidden Inputs

- OOS PnL, returns, win rate, profit factor or drawdown.
- Any signal threshold chosen after inspecting OOS.
- Any post-hoc relaxation of venue/event/date requirements.

## Deterministic Output

Verdict is one of:

- `FEASIBLE_FOR_OOS`
- `INFEASIBLE_ON_CURRENT_DATA`
- `FEASIBILITY_BLOCKED_BAD_INPUT`

Each output must include:

- expected OOS event count;
- conservative 90% lower bound;
- expected per-venue event counts;
- expected unique OOS dates;
- expected capacity coverage;
- exact rejection reasons;
- input hashes;
- estimator version hash.

## Minimum Feasibility Thresholds

- lower-bound OOS portfolio events >= 20;
- lower-bound per-venue events >= 10;
- lower-bound unique dates >= 10;
- expected dual-venue coverage >= 80%;
- expected capacity availability >= $500 per leg.

## Budget Rules

- Maximum two `INFEASIBLE_ON_CURRENT_DATA` verdicts per track do not burn OOS slots.
- Third infeasible verdict burns one track slot and requires user-visible closure/replan.
- If feasibility says `FEASIBLE_FOR_OOS` but OOS later fails sample-size gates, the hypothesis becomes `INSUFFICIENT_DATA` and burns its slot.

## Acceptance For Implementation

- Unit tests for deterministic lower-bound calculation.
- Unit tests that OOS PnL/returns cannot be passed into feasibility.
- Regression test that closed v4/v5/v6 verdicts are not reclassified retroactively.
- JSON schema for feasibility artifacts.

## Implementation Status

Implemented in `trading_mvp/src/feasibility_gate.py`.

Runner action:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 -Action fast-edge-feasibility -PlanPath <frozen-plan.json> -OutputPath <feasibility-artifact.json> -MaxRuntimeSec 120
```

Important fail-closed behavior:

- future PlanOnly artifacts must include explicit `feasibility_inputs`;
- older v4/v5/v6 PlanOnly artifacts without explicit `feasibility_inputs` return `FEASIBILITY_BLOCKED_BAD_INPUT`, not `FEASIBLE_FOR_OOS`;
- the gate rejects non-empty `oos_metrics` or `observed_performance` before computing feasibility;
- canonical event/date/capacity thresholds override relaxed thresholds embedded in old plan files.

## Data-Track Contract Integration

Future-track PlanOnly artifacts are built by `trading_mvp/src/data_track_contract.py` through runner action `fast-edge-data-track-plan`.

The integration:

- validates the hypothesis id against the pre-registered bank and requires an exact `required_data_type` match;
- requires a 64-character hexadecimal input Merkle;
- seals explicit train/OOS candidate counts, per-venue counts, unique dates, dual-venue coverage and capacity proxy;
- keeps OOS metrics and observed performance empty;
- records that no network, collector, signal, PnL or returns access occurred;
- refuses to overwrite an existing immutable PlanOnly artifact;
- caps PlanOnly generation at 1,200 seconds;
- leaves `evaluation_allowed=false` and allows only the feasibility gate as the next action.

An actual collector, night schedule, OOS, probe, paper-forward or live action is not authorized by generating this contract.
