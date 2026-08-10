# Funding daily hold v1 preimplementation disposition

## Result

- Decision: `REJECT_PROPOSAL_PREIMPLEMENTATION_ECONOMICS_MISMATCH`.
- The exact user approval was received but not consumed.
- No identity-network check, strategy/evaluator implementation, PlanOnly build, runtime manifest build, OOS read, collector, returns/PnL, grid, retune, execution probe, paper/live, private API, capital, leverage or margin action was performed.
- The immutable proposal remains unchanged and is now `TERMINALLY_SUPERSEDED_NOT_IMPLEMENTABLE`.

## Pre-OOS economics

The audit used only the frozen 2026-07-20 pair summary. At the proposed four-day hold:

| Candidate | Daily funding spread, bps | Four-day gross, bps | Normal net after 78 bps | Stress net after 116 bps and 0.5 haircut |
| --- | ---: | ---: | ---: | ---: |
| BULLA | 2.556 | 10.224 | -67.776 | -110.888 |
| ESPORTS | 8.637 | 34.548 | -43.452 | -98.726 |
| AKE | 8.149 | 32.596 | -45.404 | -99.702 |
| EVAA | 7.932 | 31.728 | -46.272 | -100.136 |
| SKYAI | 4.279 | 17.116 | -60.884 | -107.442 |
| B | 5.888 | 23.552 | -54.448 | -104.224 |
| BTW | 2.793 | 11.172 | -66.828 | -110.414 |
| RAVE | 15.752 | 63.008 | -14.992 | -84.496 |

The contract requires at least four candidates. Observed positive candidates: normal `0/8`, stress `0/8`. Only RAVE reaches stress break-even within the full 20-day OOS horizon. The proposal contains no frozen basis entry/exit condition, so price PnL cannot be treated as an undeclared alpha that rescues the funding carry.

## Funding asset universe rule

The user's new strategy-level directive is frozen in `docs/plans/funding-asset-universe-policy-v1.json`:

- every coin and every asset category is eligible for funding candidate discovery;
- Binance listing status is not an eligibility filter;
- there is no symbol whitelist, symbol blacklist or category blacklist;
- official same-underlying identity, required venue availability, immutable data completeness, quality, liquidity, capacity and cost gates still apply;
- current venue scope remains MEXC/Gate; this directive expands assets, not venues;
- every future PlanOnly must bind this policy and freeze its exact candidate set under a new hash.

## Evidence

- Proposal hash: `8d824b9c01fcf9ff526b951e8caa6a4f7c146aa6dafc7d55af99ffa919e3a09d`.
- Proposal file SHA-256: `59a7cbceaed2cbb23f86960774c98ace9ae1efa7f6a4f8d41c1f983d66dbc47a`.
- Audit deterministic result hash: `41135dd570708fdc18c10a79fa019b99c29565e5d45cdde320293c0a2543143e`.
- Audit file SHA-256: `d5713d1d76c022e6211171fea82868e5e397f2a5ed7702cb7c1f6f837e9368ec`.
- Approval receipt hash: `1159cb5a9f29de0d7b27f7b78b26cc38842cbf9244c49d02c938f7aef03ee3ab`.
- Disposition hash: `fdf5f85b7e38598b6b0e463d4ecffa991c251d83921e0313c2e235a16e3fd296`.
- Funding asset-universe policy hash: `d1fdfa616a562f9437018e3c2fd0c883483a9fdab78c6c7894012df9efee40a7`.

## Next allowed action

Build a new pre-OOS funding candidate proposal over the unrestricted asset universe. It must pass frozen cost feasibility before any identity-network work, implementation, PlanOnly build or OOS approval checkpoint.
