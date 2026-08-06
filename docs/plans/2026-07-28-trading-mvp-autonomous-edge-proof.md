# trading_mvp Autonomous Edge Proof

## Canonical Objective

Continuously find, prove, or honestly reject one non-Binance edge on MEXC/Gate
with positive net expectancy after conservative base-tier costs. The system is
event-driven: it executes every already-authorized technical step without
routine user confirmation. A future calendar window does not stop useful work:
the system executes a bounded one-shot fallback queue without repeating a
closed experiment or fabricating additional evidence from the same date.

## Autonomous Work

The following steps do not require a new user message when they preserve the
frozen hypothesis, universe, costs, risk, acceptance gates, and input hashes:

- gate/status/ETA and disk/schema/hash checks;
- cache reuse, data quality, and idempotent certification;
- exact approved visible collection segments;
- deterministic train, OOS, walk-forward, stress, economics, and capacity
  evaluation authorized by the existing evidence chain;
- unit/integration tests, fixtures, static analysis, paper-only persistence,
  reconciliation, and kill-switch work in an isolated output namespace;
- one bounded recovery attempt for the same immutable run after a transient
  failure, provided all recovery guards pass.

When the next approved calendar segment is not due, the system executes the
first unfinished task from `productive_fallback_queue`. Tasks are limited to 30
minutes, recorded in an append-only ledger, and cannot repeat at the same task
hash. The queue covers code provenance, deterministic regression, data quality,
paper-only product readiness, and materially distinct source research.

No work is performed merely to look busy. If every useful same-scope task is
complete, the state becomes `WAITING_SCHEDULE_WINDOW_NO_FALLBACK`; it cannot be
filled with duplicate scans, retuning, or repeated status checks. The next
materially new hypothesis remains a critical checkpoint.

## Weekly Codex Limit

The authoritative quota signal is the freshest local Codex
`rate_limits.primary` event whose `window_minutes` is exactly `10080`.

- If weekly remaining quota is greater than 15%, autonomous work may continue.
- If weekly remaining quota is 15% or less, no new action starts.
- An already-running bounded market-data writer may finish; it is not killed
  mid-write.
- The state becomes `PAUSED_WEEKLY_LIMIT`, the reset time is recorded, and the
  user is notified once.
- After reset, a fresh telemetry event with more than 15% remaining changes the
  state back to `ACTIVE` and processing resumes from `next_allowed_action`
  without user confirmation.
- Missing, stale, or post-reset-unrefreshed telemetry fails closed for new AI
  work.

## Critical Human Checkpoints

User participation is required only when:

1. A materially new or changed hypothesis is proposed.
2. Venue, universe, signal, cost, risk, or acceptance contract changes.
3. Evidence accepts a hypothesis or finally rejects it.
4. Recovery encounters a repeated failure, schema/hash mismatch, corruption,
   unsafe disk state, or another irreversible conflict.
5. Live orders, private API keys, real capital, leverage, margin, or withdrawal
   capability are proposed.

Everything else is routine execution and must continue automatically.

## Run And Recovery Guards

- Market-data writers are visible and single-owner.
- Every run is bounded by `MaxRuntimeSec <= 10800`.
- Existing matching cache hashes are reused.
- Between schedule windows, productive fallback tasks run sequentially and
  yield immediately when a hash-bound segment becomes due.
- `RUNNING` means monitor-only for overlapping work.
- `STOPPED_INCOMPLETE` may recover automatically once only when the same run ID,
  immutable hashes, append-safe output, dead writer PIDs, and open hard deadline
  are proven. The recovery is visible.
- A second identical failure or any integrity failure becomes a critical stop.
- Grid search, retuning closed branches, live trading, private keys, leverage,
  and margin remain prohibited.

## Evidence Path

The currently approved PIT schedule remains hash-bound and unchanged. Its
technical dates accrue automatically. At the train gate, deterministic
feasibility runs automatically. A hypothesis-level accept/reject verdict is a
critical checkpoint and is reported to the user before the next evidence
contract is created.
