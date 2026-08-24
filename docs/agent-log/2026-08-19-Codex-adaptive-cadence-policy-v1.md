# Adaptive cadence policy v1 — 2026-08-19

## Decision

All five research tracks use one proximity-based cadence policy. The scheduler wake is fixed at 300 seconds (5 minutes) and is wake-only: an orchestrator performs public network/write work only when its persisted `next_interval_at_utc` is due.

| Stage | Interval | Entry condition |
|---|---:|---|
| `SEARCH` | 21,600 s (6 h) | No qualified upcoming event |
| `SOON` | 10,800 s (3 h) | Candidate/expected event within 72 h or an active pre-market contract |
| `CONFIRMED` | 3,600 s (1 h) | Official non-proxy event is confirmed, but no near exact time is available |
| `SCHEDULED` | 300 s (5 m) | Exact official non-proxy timestamp is within 24 h |

Proxy/expected timestamps never escalate beyond `SOON`. Cancelled, expired, delisted, completed or transitioned events return to `SEARCH`. Each track stores the selected stage, reason, event ETA and next due time in its state; the combined spot orchestrator chooses the most urgent due track while keeping the two spot workers sequential.

## Track binding

1. Spot Listing Momentum v2: MEXC + Gate.
2. Spot Listing Momentum expansion: Binance + Bybit + OKX + Bitget.
3. Crypto pre-market perpetual: Bybit + OKX + Gate; application automation remains explicitly paused.
4. Pre-IPO perpetual: OKX + Gate; application automation remains active.
5. Pre-IPO candidate: Bybit; candidate-only and not scheduled until an official contract/timestamp method is bound.

All tracks remain research-only, public-data-only, without private credentials, authenticated trading, real orders, real capital, leverage, margin, evaluator/replay/OOS or live execution.

## Recovery and integrity

The combined listing orchestrator now invokes child launchers in isolated PowerShell processes so a child `exit` cannot prevent final state, launch-record and append-only ledger writes. If a visible worker is dead while state says `RUNNING`/`QUEUED_VISIBLE`, the next status or scheduler wake records `RETRY_NEXT_INTERVAL`, clears only the stale worker PID, preserves state/manifest/ledger/claims, repairs a still-running launch record and queues the next due interval. No tight-loop retry is introduced.

One validation call was initially interpreted by the legacy listing script as a scheduled tick; both child launch records completed, while the parent finalization was interrupted by the stale-worker path. The recovery record was preserved in the append-only attempts ledger; no additional tick was launched afterward.

## Verification

- Focused regression suite: 45 passed.
- Python compilation: `PY_COMPILE_OK` for adaptive cadence, pre-market, pre-IPO and both listing monitors/plan generators.
- PowerShell parser: `PS_PARSE_OK` for the three visible orchestrators.
- Listing preflight: both spot tracks `READY`, `gate_status=READY_FOR_POSTPROCESS`.
- Pre-market PlanOnly: `PLAN_OK`.
- Pre-IPO PlanOnly: `PLAN_OK`.
- Core and expansion PlanOnly generators match their checked-in immutable plans and hashes.

## Quiet five-minute scheduler mode

- Listing Momentum and Pre-IPO automations are standalone local project jobs, not thread heartbeats; this keeps ordinary scheduler wakes out of the active chat.
- Both remain active with a five-minute wake, `reasoning_effort=minimal` and failed-runs-only notifications.
- The persisted `next_interval_at_utc` is read as a string (`ConvertFrom-Json -DateKind String`) before due comparison. This prevents locale-dependent PowerShell date coercion from turning every wake into a false due tick.
- A non-due wake returns `NOT_DUE` immediately and performs no network request, collector, writer claim, terminal launch or report. The verified listing smoke tick returned `NOT_DUE` with next interval `2026-08-19T18:40:17.5523609+00:00`; the verified Pre-IPO smoke tick returned `NOT_DUE` with next interval `2026-08-19T13:50:35.751909Z`.
- When a window is actually due, the project safety contract still requires the bounded public collector to run in a visible terminal where applicable. Quiet mode suppresses normal chatter, not safety visibility or recovery records.
- The crypto pre-market automation remains `PAUSED` as previously requested and was not resumed by this change.
