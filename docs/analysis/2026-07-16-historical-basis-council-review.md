# Historical Basis Sprint Council Review

Date: 2026-07-16

Status: `DECISION_COMPLETE`

Mode: research-only, MEXC/Gate, non-Binance, public data only.

## Decision

The proposed `cross_venue_perp_basis_convergence_4h_v2` contract is accepted only after material modification.

The executable primary contract is:

`cross_venue_perp_basis_convergence_1h_v2`

The scored history is limited to 179 fully closed UTC days because Gate public funding history rejects requests older than 180 days. The 300-day contract cannot be funding-complete and therefore cannot support the proposed economics test. One-hour candles are preferred to four-hour candles because Gate's 10,000-candle cap still covers more than 179 days while preserving materially better path resolution.

The sequence is:

`A0 offline preflight -> 1h/179d primary -> deterministic repeat -> 4h aggregation robustness -> execution probe`

No collector may start before A0 accepts the complete data contract.

## Evidence Ledger

| Evidence | Verified result | Consequence |
|---|---|---|
| Current active-run gate | `READY_FOR_POSTPROCESS`; old branch terminal; `replay_allowed=false` | No consumer of the rejected 5m branch |
| Gate 5m history | Cannot satisfy frozen 220-day v1 | Keep v1 immutable and closed |
| Gate funding history | Public API returns `from time exceeds 180-day limit` | Score at most 179 closed days |
| Existing daily/funding cache | Daily history is deep; Gate funding is about 179 days | Do not repeat full daily/funding backfill |
| Public candle probe | 18/18 one-hour trade/mark/index probes non-empty for three assets on both venues | One-hour acquisition is technically plausible |
| Candidate audit | 60 dual current-active canonical candidates; 22 with both funding caches at least 175 days | Minimum eight assets is plausible but not proven |
| Existing v1 funding model | Exact candle timestamp join and at most one event per bar | Invalid for jittered or multiple settlements; replace with event ledger |
| Existing episode model | Fixed 72-hour cooldown | Replace with actual close/reset and threshold re-cross |

## Independent Review

Six first-round reviewers and two blind peer reviewers converged on the same critical findings:

1. A0 must validate identity, lifecycle, timestamps, funding cadence/sign, coverage and runtime before any network collector.
2. Changing only the candle interval does not repair the funding data contract.
3. Funding must remain a lossless, timestamped event ledger and be attributed causally to an open position.
4. Universe liquidity selection must use train data only.
5. Five fixed OOS subperiods are not rolling walk-forward and must not be labeled as such.
6. A four-hour view is a robustness aggregation after the one-hour primary, not a second hypothesis.
7. External 5m data is permitted only if native one-hour data has a documented path/causality defect, never to rescue failed economics.
8. Historical acceptance can authorize only an execution probe.

The chairman process did not return within its bounded review window and was stopped. The decision rests on the unanimous first-round and blind-review convergence; no chairman opinion is fabricated.

## Rejected Alternatives

| Alternative | Decision |
|---|---|
| Literal 4h/300d funding-aware test | Rejected: Gate funding cannot cover it |
| Mixed 300d prices and 179d funding | Price-regime diagnostic only; not a scored economics test |
| Full top-200 redownload | Rejected: cache already contains the required daily/funding layer |
| External 5m archive immediately | Deferred until native one-hour path ambiguity is proven |
| PIT as critical path | Shadow-track only |
| Paper OMS before historical evidence | Engineering-only; not proof of edge |
| Grid search, retune, reserve hypothesis | Rejected |

## Binding Stop Conditions

- A0 rejects if fewer than eight unambiguous canonical assets have one common 179-day window with lossless funding and complete candle semantics.
- Acquisition stops at 90 minutes and writes `STOPPED_INCOMPLETE`; the window and interval cannot silently change.
- Any unresolved identity, lifecycle, funding timestamp/sign/cadence, duplicate, gap or causal-availability defect invalidates affected events.
- Train failure keeps OOS sealed.
- Negative OOS, stress, fixed-subperiod or bootstrap evidence closes the branch without retuning.
- A primary rejection prevents the 4h robustness run and execution probe.
- No historical artifact can authorize live orders, private keys, leverage or margin.

## Final Route

The corrected frozen contract is stored in:

`docs/plans/2026-07-16-trading-mvp-one-week-historical-edge-sprint-v2.md`

No market-data collector was started by this council review.
