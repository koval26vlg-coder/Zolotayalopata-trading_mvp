# Gate membership source closure and v3 PlanOnly

## Decision

The visible Gate historical-membership v2 public probe completed successfully as a process but failed its frozen source-quality gates. The result does not evaluate the trading signal or its economics.

- Probe decision: `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Branch/source verdict: `INSUFFICIENT_SOURCE_QUALITY`.
- Branch status: `CLOSED_WITHOUT_HISTORY_OR_OOS`.
- No history, returns, signals, PnL, train, OOS, grid, execution probe, paper-forward, live orders, private API keys, leverage, or margin were used.

## v2 evidence

| Metric | Observed | Frozen gate |
|---|---:|---:|
| Normalized rows | 1,387 | n/a |
| Unique symbols after diagnostic dedupe | 1,353 | n/a |
| Unique delisted contracts | 516 | at least 1 |
| Unique delisted contracts with an end timestamp | 201 | n/a |
| Unique delisted end coverage | 38.95% | at least 90% |
| Unique delisted contracts missing an end timestamp | 315 | n/a |
| Exact duplicate symbols | 34 | 0 |
| Conflicting duplicate symbols | 0 | 0 |

The v2 adapter also has an isolated normalization defect: when a symbol appears more than once, it discards all extended raw fields for that symbol. This explains the multiplier failure for the duplicate groups. Exact deduplication would repair that local defect, but it cannot repair the lifecycle gap: delisted-end coverage remains only 38.95% after diagnostic dedupe.

## Immutable closure

- Closure: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\closures\gate_membership_v2_source_closure_21506188c66c.closure.json`.
- Closure SHA-256: `eb8199d342e29aa999272e9bfe96e031ff341631dd34a553f8715bcb62608159`.
- Closure artifact hash: `d4f22e9ddb95323b93592091d81cbe384390d2cf5c1e78aea313bb2ead0e7efb`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\closures\gate_membership_v2_source_closure_21506188c66c.closure.manifest.json`.
- Manifest SHA-256: `6e1489cece5c401e84277ac758dd85b559474d79c1d74a52560632a782952845`.
- Independent read-back validation: passed.

The frozen v2 plan and probe are preserved. They must not be mutated or rerun after changing their code.

## v3 source-repair contract

The branch-distance audit allowed one faster alternative: a new PlanOnly public-data contract with an independent historical delisted/inactive source. The v3 contract uses Gate archive object availability only; it does not load archive candle payloads.

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_v3_20260717_0845.json`.
- Plan file SHA-256: `d31ea79c8757387e6f1b89562b0fcb4e53d09b127dacfc6990bcdeb9ee01793e`.
- `plan_hash`: `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- Run id: `gate_membership_v3_archive_source_20260717_0845`.
- Candidate universe: 364 canonical Gate/non-Binance assets after conservative exclusions.
- Deterministic sample: 10 active, 10 delisted with missing end, 5 delisted with known end.
- Probe tasks: 189 monthly `candlesticks_1h` archive objects.
- Runtime cap: 600 seconds; workers capped at 8.
- Request policy: `HEAD`; one-byte Range `GET` fallback only when the server returns HTTP 405.
- Archive payload, returns, signals, PnL and OOS remain unread.

A v3 pass can authorize only a separate full-history PlanOnly. It cannot authorize collection, signal evaluation, OOS, execution probe, paper-forward or live trading automatically. A v3 reject closes membership momentum without another source loop.

## Verification

- Focused v2/v3 tests: `14/14 OK`.
- Related Gate membership/archive/momentum suite: `62/62 OK`.
- Python compile: passed.
- Visible-wrapper PowerShell parse: passed.
- Frozen v3 authorizer read-back: passed.

## Next approval

The network probe has not started. Its exact hash-bound approval is:

```text
Подтверждаю visible Gate archive-membership v3 public probe plan_hash=e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3, run_id=gate_membership_v3_archive_source_20260717_0845, MaxRuntimeSec=600, public archive metadata only, без archive payload/returns/OOS/grid/live/private API keys.
```
