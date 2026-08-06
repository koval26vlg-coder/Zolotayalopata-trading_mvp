# trading_mvp Night Data Schedule Proposal

Status: `FROZEN_PLANONLY_AWAITING_EXPLICIT_APPROVAL`
Timezone: `Europe/Volgograd`
Window: `23:00-07:00`
Canonical maximum per night: `28800` seconds
Frozen PIT v2 segment runtime: `1200` seconds
Approval horizon: up to 14 days after explicit user approval.

## Purpose

Collect new data types without blocking daytime engineering. This proposal is not permission to run. Actual execution requires explicit approval from the user with schedule/date scope.

## Frozen Schedule

- Hypothesis: `pit_universe_membership_drift_reversion_v1`.
- Data type: `PIT_UNIVERSE_V2_FORWARD`.
- Artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_184844.json`.
- Plan hash: `2c484b7b2cbb94ee94f87b8ae65519501d812647ef4848219abc4bf01dff1c45`.
- File SHA-256: `5459ce95dfe4f13c816d83b7cd947a2282fda00759c7abd4e1700e8f1e27e0a0`.
- Hypothesis contract hash: `93895bd0f765d37c3bc78e206749a81ba5b6ec9287cde427233b237559bc4db9`.
- Hypothesis bank SHA-256: `8c1abf5bf5662ff29e3b422052bb101c6186f5fb7040253bd4b13555a5bea539`.
- Dates: 14 nightly segments from `2026-07-14T23:00:00+03:00`; final hard deadline `2026-07-28T07:00:00+03:00`.
- Per night: 20 minutes, five-minute interval, expected floor four cycles.
- Storage: `E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2`.
- Execution: visible PowerShell terminal only; no hidden scheduler has been installed.
- Evidence status: 14 scheduled dates versus 80 required quality dates, so this tranche cannot prove or reject the edge.
- Runtime provenance: plan seals SHA-256 of nine runtime components: visible wrapper, collector, approval script, status tool, quality certifier, segment-quality evaluator, hypothesis-contract validator, cost module and feasibility estimator.
- Preregistration: the full event, signal, entry/exit, cost, sample split, feasibility, OOS, walk-forward, stress and multiplicity contract was sealed before any forward market row was read.

Earlier schedule artifacts ending in `162615`, `163030`, `163906`, `173129`, `174224` and `182041` are superseded diagnostics and must not be approved or executed. In particular, plan hashes `bce81a343434bc16c5f85c64ad63825a88ff7964567662565e040d4382eb43ac` and `8fa86b77fc74db86193f304068c8f6885a3aaa9752eeeaadd132a284f118dcaa` plus their approval phrases are invalid. The `182041` plan fails closed against the current hypothesis-bank provenance hash.

## Embargo-Safe Status

The schedule can be checked without approval or network activity using `fast-edge-night-schedule-status`. The current pre-approval report is:

- Artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_status_20260714_184934.json`.
- Decision: `AWAIT_EXPLICIT_SCHEDULE_APPROVAL`.
- Segments: `14 PLANNED`, `0 DUE`, `0 RUNNING`, `0 COMPLETED`, `0 MISSED`.
- `collection_started=false`, `market_rows_read=false`, `returns_read=false`, `oos_allowed=false`.

This status report is a technical journal only. It neither approves the schedule nor certifies data quality.

## Sealed Quality Certification

After a segment is technically complete, `fast-edge-night-schedule-quality` applies the sealed policy and appends the result to an immutable cross-tranche ledger. The policy requires final positive-row manifests, at least two exchanges in every cycle, error-cycle ratio not above 5%, zero duplicate snapshot keys, timestamps inside the approved window with at most 60 seconds clock skew, and 80 accepted distinct dates before the minimum-data gate can be satisfied.

Quality certification does not read returns or PnL and cannot authorize OOS. Even after 80 dates, the next permitted step is feasibility evaluation of the already frozen contract.

## Priority Queue

1. `PIT_UNIVERSE_V2_FORWARD`
   - Goal: point-in-time market availability, listings, delistings and symbol eligibility.
   - Output: `E:/ZolotyayLopata-data/exports/trading-mvp/pit-universe-v2/`.
   - Guard: no analytical return review during collection.

2. `DENSE_WS_SEGMENTED`
   - Goal: segmented order book/trade-flow data with explicit gap manifest.
   - Output: `E:/ZolotyayLopata-data/exports/trading-mvp/ws-segmented/`.
   - Guard: segments remain usable even if a later segment fails.

3. `LISTING_FORWARD_MONITOR`
   - Goal: listing/contract activation and early liquidity decay observations.
   - Output: `E:/ZolotyayLopata-data/exports/trading-mvp/listing-forward/`.
   - Guard: event metadata only until hypotheses are frozen.

4. `FUNDING_HISTORY_EXTENSION`
   - Goal: extend funding/mark/index history if cache hash proves new coverage.
   - Output: `E:/ZolotyayLopata-data/exports/trading-mvp/funding-history/`.
   - Guard: no repeat if cache/config hash matches an existing valid artifact.

## Required Run Guards

- Visible terminal or visible monitor only.
- No hidden/background `Start-Process`.
- Active-run gate must be written before start and cleared/finalized on completion.
- Hard deadline at 07:00 local time.
- Disk guard before start and during run.
- Manifest includes run id, config hash, expected outputs, PID/process tree, stdout/stderr, last write and stop reason.
- Timeout/network interruption writes `STOPPED_INCOMPLETE`, not partial success.
- Resume only with same run id, matching hashes and explicit visible user approval.

## Explicit Approval Phrase Needed

Exact approval for this immutable plan:

`Подтверждаю ночное расписание trading_mvp plan_hash=2c484b7b2cbb94ee94f87b8ae65519501d812647ef4848219abc4bf01dff1c45 на 2026-07-14T23:00:00+03:00..2026-07-27T23:20:00+03:00, data_type=PIT_UNIVERSE_V2_FORWARD, visible terminal, без OOS/grid/live/API keys.`

After that phrase, Codex may run the approval script once. Approval writes an immutable record but does not itself start a collector. Each scheduled segment remains bound to its exact visible command, time window and run id. A failed segment is `STOPPED_INCOMPLETE` and is never auto-resumed.

## Supersession Notice - 2026-07-14 19:32 +03:00

The approval phrase above for plan hash `2c484b7b...` is invalid and must not be used. The old plan fails closed after the evaluator-first contract update.

Current exact approval phrase:

`Подтверждаю ночное расписание trading_mvp plan_hash=b5ad5616983a9c807b9159067294045f7ca87f27dab343b39f0b91572d2a9c58 на 2026-07-14T23:00:00+03:00..2026-07-27T23:20:00+03:00, data_type=PIT_UNIVERSE_V2_FORWARD, visible terminal, без OOS/grid/live/API keys.`

Current plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_night_schedule_planonly_20260714_193046.json`. It is unapproved and no collection has started. This 14-date tranche is only a subset of the 120-date evaluator requirement.
