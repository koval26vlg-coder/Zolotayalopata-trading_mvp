# Gate historical membership PlanOnly

## Decision

`GATE_HISTORICAL_MEMBERSHIP_PLAN_READY_AWAITING_EXPLICIT_PUBLIC_PROBE_APPROVAL`

This is a data-repair branch, not a new signal family and not a retune of a rejected strategy. It addresses the known current-universe survivorship defect that blocks confirmatory use of the existing daily Gate history.

Gate documents a separate public endpoint, `GET /futures/{settle}/contracts_all`, for active and delisted futures contracts. The contract schema includes creation, launch, delisting and delisted timestamps. Gate also publishes an archive family for historical futures candles and funding data:

- https://www.gate.com/docs/developers/apiv4/en/futures/
- https://www.gate.com/announcements/article/21688

The current MEXC public contract API remains a current-contract source; this plan does not claim that MEXC historical membership is solved:

- https://mexcdevelop.github.io/apidocs/contract_v1_en/

## Frozen artifact

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_plan_20260717_052145.json`
- Plan hash: `07ea7df9103792cf45e56dfe96217c061b10bab35e6817110e3650ef5319bcf8`
- File SHA-256: `49a04ff84a00f305b5c073eb18f04ec96ad04a76adbb5c9ef69e291d58b7353c`
- Code SHA-256: `c2cc994bbf2ed07e67b33b3e99c796a4411d6f251c57447e4360664f18c172e2`
- Input manifest SHA-256: `3c7794dcf11dd2b456614c614d263fe1498292d7b364e281371ead79e6c23466`
- Runtime cap: `600` seconds
- Page limit: `100`; duplicate non-empty pages fail closed

The earlier unapproved plan `gate_historical_membership_plan_20260717_051712.json` is superseded because pagination, code binding and resumable failure handling were strengthened before any probe. It remains immutable diagnostic history and must not be approved or executed.

## Guards

- Plan generation performs zero network requests.
- Probe execution is bound to both `plan_hash` and evaluator code SHA-256.
- Network/API failure writes `GATE_HISTORICAL_MEMBERSHIP_PROBE_STOPPED_INCOMPLETE` and can only retry the same plan/run visibly.
- A final report with the same plan hash is reused without another request.
- Acceptance requires at least 100 crypto USDT perpetual contracts, at least one delisted contract, lifecycle-start coverage at least 95%, delisted-end coverage at least 90%, no duplicate symbols and no invalid lifecycle interval.
- Historical collect, momentum retest, OOS, grid, retune, execution probe, paper-forward and live remain blocked.
- Gate-only confirmatory evidence is explicitly weaker than dual-venue evidence.

## Verification

- New and related tests: `44 OK`.
- PowerShell parse: OK.
- Frozen artifact read-back authorization: OK.
- Returns, PnL, signals and OOS metrics read: false.

## Next allowed action

Only a visible, public, hash-bound membership availability probe is allowed:

`Подтверждаю visible Gate historical-membership public probe plan_hash=07ea7df9103792cf45e56dfe96217c061b10bab35e6817110e3650ef5319bcf8, run_id=gate_historical_membership_plan_20260717_052145, MaxRuntimeSec=600, public API only, без returns/OOS/grid/live/private API keys.`

If the probe is accepted, the next artifact must be a separate hash-bound history-backfill PlanOnly. The probe itself cannot authorize collection or reopen momentum.
