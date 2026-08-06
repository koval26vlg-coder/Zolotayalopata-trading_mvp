# trading_mvp continuous production v1

## Decision

`blocked` and fixed-date waiting are not production states. The project remains
`ACTIVE` while it has a proof-critical task, a future evidence event, or a run
approval to prepare.

Continuous production is not the same as keeping a market-data writer busy.
Every action must either reduce uncertainty at a frozen gate or prepare the
next immutable evidence-producing campaign.

## Operating windows

- Weekdays: a new long campaign may start from `19:00`; hard stop is `08:00`
  the next day.
- Weekend: one envelope runs from Friday `19:00` through Monday `08:00`.
- A campaign can start later inside an open envelope, but its maximum runtime
  cannot cross the envelope hard deadline.
- The old global `MaxRuntimeSec<=10800` ceiling is not authoritative for a
  long campaign. The exact approved hard deadline is authoritative.
- `1800` seconds remains the ceiling for routine offline tasks that do not need
  a long-run approval.
- Writers target a clean finish by `07:45`; `08:00` is the unconditional hard
  stop after a reserved 15-minute shutdown/finalization grace period.

The window is a ceiling, not a target. Filling unused hours without additional
evidence value is forbidden.

## Approval contract

There are three execution classes:

- `OFFLINE_BOUNDED`: no writer and at most 30 minutes; routine authorization.
- `PREAPPROVED_SHORT_SEGMENT`: an exact short segment already listed in an
  immutable approved schedule; no repeat approval.
- `LONG_CAMPAIGN`: a writer above 30 minutes or a multi-phase campaign; exact
  per-campaign approval is mandatory.

At or after `18:30`, or immediately when an open window is discovered, Codex
prepares an approval packet only when a positive-information-gain long
candidate has a complete PlanOnly contract. It contains:

- objective and immutable plan hash;
- exact start, expected duration, maximum runtime and hard deadline;
- early quality gates, resource estimates and stop conditions;
- visible command, output/manifest paths, status command and stop command;
- explicit no-grid, no-live, no-private-API, no-leverage and no-margin scope.

One approval covers only the listed immutable campaign and its named phases.
Any hash, scope, deadline or maximum-runtime extension needs a new approval.
`STOPPED_INCOMPLETE` recovery also needs a new explicit approval.

## Production lanes

1. Daytime lane: code, tests, PlanOnly, provenance, integrity, approved
   postprocess and paper-only infrastructure on isolated outputs.
2. Night lane: one visible market-data writer, either a preapproved short
   segment or an exactly approved long campaign.
3. Post-run lane: technical certification first; returns, PnL and OOS remain
   embargoed until their frozen gate opens.
4. Decision lane: stop only for a changed contract, terminal verdict,
   integrity conflict or live/private-capital decision.

## Current PIT implication

The active PIT track has `4/20` accepted calendar dates. Its remaining gate is
`16` distinct dates. Increasing one date from 20 minutes to 13 hours increases
rows but does not reduce the number of missing dates. Therefore:

- keep each PIT date only as long as its frozen quality contract needs;
- do not consume an entire night with PIT merely for utilization;
- use long windows only for another already pre-registered data track whose
  information gain actually grows with duration;
- selecting such a track still requires an exact campaign packet and user
  approval before the writer starts.

The current sealed schedule contains only 12 future PIT dates after its missed
segments, so a same-contract schedule extension of four or more dates will be
needed later to reach `20/20`.

## Completion criterion

The pipeline is working when there is no mechanical `blocked` state, each open
night has either an approved evidence-producing campaign or a recorded reason
why no run has positive information value, and every completed campaign moves
one frozen gate forward.
