# trading_mvp Night Schedule Plan v2

## Scope

`fast_first_night_schedule_plan_v2` freezes a bounded `PIT_UNIVERSE_V2_FORWARD` collection schedule. It is PlanOnly and cannot start network activity. Every plan belongs to exactly one evidence stage: `train_accrual` or `oos_accrual`.

## Seal

`plan_hash` is SHA-256 of canonical JSON for `sealed_schedule`. The seal contains:

- hypothesis id and data type;
- the complete pre-registered hypothesis contract and its canonical SHA-256, including event definition, signal, entry/exit, costs, sample split, feasibility, OOS, walk-forward, stress and multiplicity rules;
- canonical goal and hypothesis-bank hashes;
- timezone, window, dates, duration, interval and output root;
- every segment run id, start, end, hard deadline and output directory;
- projected coverage versus the hypothesis minimum;
- the collection stage, exact append-only quality-ledger path, accepted certification snapshot, stage target and maximum remaining accepted dates;
- for `oos_accrual`, the hash-bound train input plan and `FEASIBLE_FOR_OOS` artifact;
- absolute runtime-tool paths and SHA-256 for the schedule planner itself, visible wrapper, collector, public-probe client, approval script, status tool, quality certifier, segment-quality evaluator, hypothesis-contract validator, cost module, feasibility estimator and membership-drift evaluator;
- the immutable segment-quality policy, including venue coverage, dual-venue L1 quantity coverage, error, duplicate, clock-skew and distinct-day thresholds;
- timeout, minimum contracts per exchange and minimum free-disk threshold.

The plan file also contains executable commands. Approval separately binds the complete plan file SHA-256, so command text cannot be changed after approval.

## Validation

`night_schedule_plan.py validate` fails closed when:

- schema/mode or expected plan hash differs;
- sealed and runtime segments differ;
- a runtime command loses its plan path, plan hash or run id;
- the canonical goal, hypothesis bank or runtime-tool hash changes;
- the embedded hypothesis contract differs from the current bank entry, its canonical hash, conservative cost profile or canonical acceptance gates;
- the sealed quality policy is missing, unsupported or differs from the validator contract;
- the current quality ledger loses or mutates any certification sealed at planning time;
- a train plan schedules more dates than remain before the 20-date feasibility gate;
- an OOS plan lacks a hash-valid train plan or `FEASIBLE_FOR_OOS` artifact, or either upstream artifact reads OOS;
- PlanOnly state claims approval, collection, network, OOS or PnL access.

## Approval

`tools/approve_trading_night_schedule.ps1` is the sealed receipt writer. It requires `-ConfirmedNightScheduleApproval`, refuses a `RUNNING` or `STOPPED_INCOMPLETE` gate, revalidates the plan, calls `authorize-segment` for the first segment, writes one immutable approval record and adds its hash-bound reference to the gate. The approval seals the collection stage and quality-ledger path. It never starts the collector.

New schedules must be activated through `tools/activate_approved_trading_night_schedule_pointer.ps1`, not by calling the receipt writer directly. The activator validates the same immutable plan and stage, creates or reuses the exact approval receipt, verifies the gate binding, and writes the authoritative dynamic schedule pointer last. `-PreflightOnly` performs all validation without writes. Repeating an exact completed activation is read-only and idempotent; repeating after an interrupted receipt/gate write repairs only the missing exact bindings. A tampered receipt, changed plan, active writer, incomplete run, or expired window fails closed before the pointer changes.

One approval covers only the listed segment run ids until the final deadline. Changing the plan, tools, run id, duration, interval, output root or window invalidates authorization.

## Execution

Every segment runs through `tools/start_pit_universe_snapshot_collect_visible.ps1` in a visible terminal. Before collection it verifies:

- active-run gate is not `RUNNING` or unresolved `STOPPED_INCOMPLETE`;
- plan, plan-file and approval-record hashes;
- approval is active and unexpired;
- exact segment run id, duration, interval, output root and time bounds;
- a fresh `authorize-segment` result against the current ledger, stage target and upstream feasibility evidence;
- enough remaining time before hard deadline;
- free disk is at or above the sealed threshold.

The collector repeats the disk check during execution. For every currently listed dual-venue non-Binance base it also requests MEXC L1 depth, while Gate L1 quantities come from its public ticker payload. MEXC depth enrichment has a 120-second per-cycle runtime budget; any unqueried symbols are recorded as budget-exhausted errors and the segment fails closed through the size-coverage gate. Cycle cadence is start-to-start, so request runtime does not silently extend the sealed five-minute interval. The cycle journal and manifest expose depth target/completion/coverage, per-symbol depth errors and cumulative depth-error counts. Success writes a final manifest and `READY_FOR_POSTPROCESS`. Network, timeout, disk or runtime failure writes `STOPPED_INCOMPLETE`. Resume requires the same run id, compatible manifest/journal and a new explicit visible resume decision; there is no auto-resume. A train segment cannot start after the ledger reaches 20 accepted dates. OOS accrual cannot start before a separately sealed positive train-feasibility verdict.

## Data Embargo

During the forward tranche, only technical health fields may be inspected: cycles, rows, errors, timestamps, last write and manifest consistency. Returns, PnL, signal patterns and OOS outcomes remain embargoed until data-quality certification and the next hypotheses are frozen.

## Technical Status Journal

`night_schedule_status.py` derives the required night journal from the immutable plan, approval record, segment manifests and collector locks. It never reads snapshot rows, returns, PnL or signals. The unified entry point is:

```powershell
.\trading_mvp\run_mvp.ps1 -Action fast-edge-night-schedule-status `
  -PlanPath <schedule.json> `
  -ExpectedPlanHash <plan_hash> `
  -OutputPath <status.json> `
  -MaxRuntimeSec 120
```

Each scheduled night is classified as `PLANNED`, `DUE`, `RUNNING`, `COMPLETED`, `STOPPED_INCOMPLETE`, `MISSED` or `INVALID`. `RUNNING` requires a live lock owner. A stale running manifest becomes `STOPPED_INCOMPLETE`; a final manifest counts as technically completed only when its schema, run id, duration, interval, stop condition, cycle floor and row floor match the sealed segment.

Technical completion is deliberately separate from data-quality certification. The status report exposes the sealed collection stage, current accepted ledger dates and dates remaining to that stage target. It keeps `oos_allowed=false`; a later hash-bound quality step must certify each completed date, and only a separate `oos_accrual` plan can authorize OOS data collection.

## Quality Certification Ledger

`night_schedule_quality.py` evaluates only technically completed segments from an approved, hash-valid schedule. It uses the sealed `pit_universe_v2_segment_quality_v3` policy and appends immutable certifications to one cross-tranche JSONL ledger. The unified entry point is:

```powershell
.\trading_mvp\run_mvp.ps1 -Action fast-edge-night-schedule-quality `
  -PlanPath <schedule.json> `
  -ExpectedPlanHash <plan_hash> `
  -QualityLedgerPath <quality-certifications.jsonl> `
  -OutputPath <quality-report.json> `
  -MaxRuntimeSec 1800
```

The certifier requires the exact quality-ledger path sealed by the schedule. It fails closed when approval, plan, runtime-tool, manifest, snapshot hash, night-window, venue-coverage, error-ratio, duplicate-key or ledger-chain validation fails. A segment is rejected if any cycle has fewer than two exchanges or if fewer than 95% of dual-venue eligible markets contain positive bid and ask quantities on both venues. Re-running an unchanged certification is idempotent; changing evidence for an existing `run_id` is treated as ledger tampering.

The quality report may read technical market rows only after structural approval and completion checks. It never reads returns or PnL and always emits `oos_allowed=false`. At 20 accepted consecutive dates it stops further accrual and permits only a train input seal plus train-only feasibility evaluation of the already frozen contract. OOS dates may be collected only after a hash-valid `FEASIBLE_FOR_OOS` verdict.

## Evidence Limit

The current 14-night `train_accrual` schedule contributes at most 14 unique dates. A separately approved second train tranche may add only the dates still needed to reach the 20-day train gate. Segment authorization re-counts the ledger immediately before every run, so a stale approval cannot cross the gate. At 20 accepted train dates collection pauses: the evaluator seals the earliest 20 accepted dates, reads no OOS rows and issues `FEASIBLE_FOR_OOS` or `INFEASIBLE_ON_CURRENT_DATA`.

Only `FEASIBLE_FOR_OOS` permits a separately planned 100-day untouched OOS tranche. The complete frozen sample is therefore 20 train plus 100 OOS dates, with five non-overlapping 20-day folds. The append-only ledger may accumulate accepted dates across separately approved tranches, but no tranche by itself authorizes OOS, execution probe, paper-forward or live review.

## Executable Capacity And Next Route

Contract v1.3.0 forbids the prior `0.5% * 24h volume` capacity proxy. Every simulated event must have at least `$500` executable top-of-book quantity on both legs at entry and exit. Capacity is the minimum quote value across long-entry ask, short-entry bid, long-exit bid and short-exit ask. Missing or insufficient quantity rejects the event; daily volume cannot substitute for it.

The immutable input plan, train-feasibility artifact and final OOS artifact each carry one `next_allowed_command`. Plan validation recomputes and verifies that command outside the sealed payload. Positive train feasibility may only build a separately approved `oos_accrual` schedule PlanOnly; it cannot jump directly to OOS evaluation. A terminal reject emits a no-command closure sentinel, while a historical accept emits only an explicit-approval request for a PIT execution-probe PlanOnly.
