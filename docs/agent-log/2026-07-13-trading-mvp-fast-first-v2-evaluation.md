# trading_mvp Fast-First v2 evaluation

Date: 2026-07-13
Agent: Codex, manual mode; swarm disabled

## Run

- Run ID: `fast_first_v2_residual_dispersion_20260713_1845`.
- Visible launcher completed two deterministic evaluations in the same sealed run.
- First attempt was stopped safely by the active-run ownership gate; the same run ID was resumed after fixing ownership validation.
- Final gate: `READY_FOR_POSTPROCESS`; replay, probe, paper and live remain disabled.

## Verdict

- `INSUFFICIENT_DATA`.
- OOS closed-day coverage: 59/60.
- Gate events: 0 total, 0 MEXC, 0 Gate.
- Primary cause: `insufficient_eligible_markets` on all 399 venue-days.
- Result hash matched across both evaluations: `f2edd8391b088fcec12214601ac8364adcea1fd651d8b9f0a9a135efc13f6e75`.

## Verification

- Full unit/regression suite: 538 passed, 5 skipped.
- Python compile: passed.
- PowerShell parser checks: passed.
- `git diff --check`: passed.

## Handoff

Do not retune residual dispersion, funding, listing-event or slow-liquidity on the same evidence. The only permitted research continuation is a new frozen Fast-First PlanOnly hypothesis.
