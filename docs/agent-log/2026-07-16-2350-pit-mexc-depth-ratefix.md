# PIT MEXC depth rate fix

Date: 2026-07-16 23:50 +03:00

Status: `RATE_FIX_VERIFIED_NEW_SCHEDULE_AWAITS_APPROVAL`

## Rejected segment

- Run ID: `pit_universe_v2_forward_20260716_n01`
- Collector result: `4/4` cycles, `6864` rows, `0` endpoint errors, `final=true`.
- Technical quality verdict: `PIT_SEGMENT_QUALITY_REJECTED`.
- Only rejection: `dual_venue_bbo_size_coverage_below_minimum`.
- MEXC depth completion by cycle: `136/210`, `145/210`, `172/210`, `210/210`.
- Root cause: sequential per-symbol depth enrichment exhausted its 120-second budget.

## Failed first concurrency attempt

- Artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\mexc_depth_concurrency_probe_20260716_v2.json`
- Policy: `8` workers, `0.11` second submission interval.
- Result: `151/210`, coverage `0.7190476190`.
- All 59 failures: MEXC error `510`, requests too frequent.

## Verified fix

- Global request start interval: `0.25` second.
- Maximum depth workers: `3`.
- Runtime budget remains `120` seconds.
- Frozen quality threshold remains `0.95`.
- Live artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\mexc_depth_concurrency_probe_20260716_v3.json`.
- Live result: `210/210`, coverage `1.0`, `0` depth errors.
- Decision: `PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL`.

## Verification

- TDD regression added for conservative defaults and report provenance.
- Relevant PIT/night-schedule suite: `45/45 OK`.
- Full `unittest discover` was stopped by the external 300-second command timeout and is not claimed as passed.
- Active-run gate after verification: `READY_FOR_POSTPROCESS`; no active collector.

## New immutable schedule

- Primary PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_primary_immutable_sources_planonly_20260716_234212.json`.
- Primary plan hash: `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1`.
- Primary dates: `2026-07-17..2026-07-30`, 14 visible 20-minute segments.
- Extension PlanOnly: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_extension_immutable_sources_planonly_20260716_234212.json`.
- Extension plan hash: `90dc9ddc9f9bf0176f45592c0a58efdeb099f8a1c927035c389b71b1fa85cab3`.
- Both validators returned `verdict=VALID`.
- Sealed public-probe SHA-256 equals current source SHA-256: `8924d31a80de6633ecf3dde5ae5bad8d8c53766db7eab1c5c55a53be062c340f`.

The old approved `14f687e...` schedule and approval record remain immutable but are superseded for future segments because their runtime-tool hash is stale. No approval pointer was changed and no new collector was launched.

## Next allowed action

Approve the new primary plan hash, then wait for and run only its next visible segment. Do not approve the extension until the primary horizon is exhausted or accepted-date coverage is recalculated.
