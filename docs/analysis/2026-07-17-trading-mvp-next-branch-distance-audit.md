# trading_mvp next-branch distance audit

## Decision

`NO_MATERIALLY_NEW_ACCEPTABLE_EXISTING_CACHE_BRANCH`

The one-week historical candidate `gate_spot_perp_basis_convergence_history_v2` is closed as `INFEASIBLE_ON_CURRENT_DATA`. The frozen 132 bps entry threshold was absent from the 100-day train window, so OOS was not read and the branch cannot be retuned.

This closes the candidate, not the overall `trading_mvp` goal.

## Existing-cache branch audit

| Candidate | Decision | Reason |
|---|---|---|
| Gate spot/perp basis v2 | Closed | Zero train episodes at the frozen economic threshold |
| Cross-venue/perp basis | Closed | Previous historical/public-retention and economics gates already failed |
| Funding/carry families | Closed on current evidence | Price-only, stress, concentration or sample gates failed; no retune |
| Weekend liquidity v6 | Closed on current evidence | Seven OOS events and missing Gate sample; positive point estimate is not sufficient |
| Listing, slow-liquidity, wick, residual dispersion | Closed | Existing frozen evaluations returned reject or insufficient data |
| HFT/order-book continuation/reversal | Closed for fast track | Public-API latency, fees and thin samples did not support an accepted edge |
| New daily time-series trend on `daily_forward_20260713` | Not opened | It would inherit the known current-universe survivorship defect and cannot reach historical acceptance |

The daily cache contains 200 current symbols per venue and about 200 days of public history, but it does not contain a point-in-time delisted/inactive universe. Reusing it for another return factor would change the signal while preserving the dominant bias. That is multiple testing, not independent evidence.

## Product readiness

The reusable paper-only two-leg engine already exists and is tested. It provides:

- depth-derived entry/exit prices;
- stale and thin-book blocking;
- fee and funding accounting;
- append-only hash-chained ledger;
- state/ledger reconciliation;
- fail-closed kill switch;
- a 15-independent-event live-review gate.

No additional OMS rewrite is justified before a strategy passes historical and execution gates.

## Next allowed evidence path

1. Continue `PIT_UNIVERSE_V2_FORWARD` as an independent shadow track: one visible 20-minute segment per new observation date, not repeated scans within the same date.
2. Use the PIT track to repair the dominant point-in-time/survivorship defect before reconsidering a daily factor.
3. A faster alternative is allowed only as a new PlanOnly public-data contract that includes historical delisted/inactive membership. It must not reuse OOS or retune a closed signal.
4. Until one of those inputs exists, no collector, OOS, execution probe, paper-forward or live action is justified for the closed basis branch.

## Verification

- Branch closure read-back: valid.
- Experiment ledger entry: exactly one reject record for the dedicated setup.
- Focused post-fix tests: `15 OK`, `1 skipped`.
- Full visible regression: `940 OK`, `5 skipped`, `0` failures/errors.
- Active-run gate: `READY_FOR_POSTPROCESS`; `replay_allowed=false`.
