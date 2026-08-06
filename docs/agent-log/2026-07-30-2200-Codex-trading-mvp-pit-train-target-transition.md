# PIT train-target transition hardening

- Observed at: `2026-07-30T22:00:00+03:00`
- Scope: metadata/code/tests only; no returns, PnL, OOS rows, network collector, replay, grid, retune, paper, or live execution.
- Finding: `resolve_schedule_window` could expose a remaining preapproved segment after the frozen collection-stage target was reached. A five-night extension sized for four required dates could therefore permit a 21st train date after four successful nights.
- Fix:
  - bind the active pointer, schedule plan, collection stage, quality ledger, hypothesis, data type, and hypothesis-contract hash before resolving a segment;
  - return `STAGE_TARGET_REACHED` before selecting another segment and fail closed on target overshoot;
  - route `20/20` to visible deterministic train feasibility, then to the feasibility verdict/review state, preempting collectors, schedule extension, research fallback, and unrelated long-campaign decisions;
  - expose the bound feasibility manifest/result/OOS-PlanOnly metadata through the guard;
  - validate any reused train-feasibility manifest against the exact current ledger SHA, contract, 20/0 train/OOS split, deterministic repeat artifacts, embargo fields, and inactive OOS PlanOnly before accepting its verdict.
- Verification:
  - `106` linked unit tests passed;
  - Python compile checks passed;
  - PowerShell parser check passed;
  - exact current PIT postrun `-PlanOnly` returned `PLAN_VALIDATED`, `accepted_distinct_dates=4`, target `20`, and `mutation=false`;
  - live autopilot guard remains `ACTIVE`, quota `57%`, next segment `pit_universe_v2_forward_20260731_n03` is `WAITING`, and no writer was started.
- Next: keep the current exact segment schedule unchanged. At the frozen stage target, collectors are suppressed and the bounded train-feasibility transition owns the branch.
