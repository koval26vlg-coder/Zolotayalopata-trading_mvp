# AEF continuous 24h PlanOnly ready

Observed local time: 2026-08-02 09:50 +03:00.

## Decision

- The historical `cross_venue_perp_basis_convergence_history_v1` branch remains terminally closed as `INSUFFICIENT_DATA`. Gate public 5-minute retention was about 34.7 days versus the frozen 220-day requirement. No edge result was claimed and no retune/repeat was opened.
- The old 72-hour route, reconciled partial datasets, split AEF schedule, and prior campaign candidates remain diagnostic-only and are not launchable.
- The active evidence route is one uninterrupted, public read-only dense WebSocket campaign after PIT n06.
- PIT n07 is explicitly suppressed while the dense campaign owns the single global market-data writer. Later PIT dates remain active.

## Frozen campaign

- Campaign: `dense_ws_microstructure_regime_filter_v1_20260803_aef_24h`
- Writer start: `2026-08-03T01:30:00+03:00`
- Target writer time: `86400` seconds
- Writer deadline: `2026-08-04T01:30:00+03:00`
- Hard deadline: `2026-08-04T02:00:00+03:00`
- Hard aggregate output cap: `25000000000` bytes
- Estimated raw disk: `12278246229` bytes
- Estimated inbound network upper bound: `24556492458` bytes
- Expected RAM: `1 GiB`; hard RAM stop: `2 GiB`
- Hard normalized CPU stop: `75%`

## Immutable evidence

- Feasibility: `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-feasibility-20260802-aef-continuous24h-v3.json`
- Feasibility SHA-256: `e5911d9eebb79fd3a898c0394b6d25b0d28b6d35d746c5a134616d5f54d87d47`
- Contract: `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-microstructure-regime-filter-contract-20260803-aef-24h-v1.json`
- Contract hash: `8f2021053b83551edb9bfb57847810caccdef30fd3368349ff98aedfe1cf9485`
- PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-microstructure-regime-filter-planonly-20260803-aef-24h-v1.json`
- Plan hash: `57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b`

## Verification

- Contract/PlanOnly/policy binding: `VALID`.
- Read-only launcher preflight: `STRUCTURALLY_VALID_NOT_DUE` and `no_run_or_output_writes=true`.
- Guard: `ACTIVE`, decision `AWAIT_EXPLICIT_LONG_CAMPAIGN_APPROVAL`.
- Weekly quota at the checkpoint: `82%` remaining.
- Unit tests: `59` passed.
- No collector, writer, replay, OOS, returns/PnL evaluation, grid, paper-forward, live order, private API, leverage, or margin action was started.

## Next action

Request one exact hash-bound approval for the 24-hour campaign. After approval, the heartbeat launches PIT n06 visibly at 01:00 and launches the dense campaign visibly for the 01:30 writer start. No repeated approval is required during a successful immutable run. `STOPPED_INCOMPLETE` recovery still requires a new exact approval.
