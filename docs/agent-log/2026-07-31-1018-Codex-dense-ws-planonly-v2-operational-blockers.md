# Dense WS campaign PlanOnly v2: fail-closed operational blockers

## Scope

- Authorization: contract freeze and immutable PlanOnly only.
- Campaign: `dense_ws_microstructure_regime_filter_v1_20260731_weekend`.
- Candidate contract hash: `4cebe947e9997df1ae061231bd24a78d10bb7735697a259bf2eabd7a6bbb1386`.
- No collector, network writer, replay, OOS, returns/PnL read, grid, retune, paper, live, private API, leverage, or margin action was run.

## Immutable artifacts

- Contract v1:
  - path: `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-microstructure-regime-filter-contract-20260731-weekend-v1.json`
  - file SHA-256: `cd27a0d385b2e6451801431be066dad5301f067a3e9a70d46ef0aee9801d7dfd`
  - contract hash: `f71c094f9ac4334a70eed3fef2e9b9de81809001cface62b51d42d64d4261612`
- PlanOnly v2:
  - path: `E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-microstructure-regime-filter-planonly-20260731-weekend-v2.json`
  - file SHA-256: `3decdcd0343b25ce574c8571c9c2d1082c97d022b429ab13503b5010de3e4e18`
  - plan hash: `16b41763a4fa2e0f1e76188ff2a74d80ac8f2136e50192d727285f3ae1566dba`
  - approval state: `NOT_APPROVED`
  - collection allowed: `false`

## Fail-closed decision

- Launch control status: `CONTROLS_IMPLEMENTED_OPERATIONAL_REVIEW_REQUIRED`.
- Blocker `ZERO_RUNTIME_HEADROOM`: each frozen phase window equals its writer duration, leaving zero startup/finalization margin.
- Blocker `GLOBAL_ACTIVE_WRITER_CAS_NOT_IMPLEMENTED`: the shared active-run gate check is not an atomic cross-launcher writer claim.
- Next allowed action: revise the timing contract and implement/test the global active-writer claim. A new immutable PlanOnly and separate exact user approval would then be required.

## Verification

- Contract and policy binding validation: `VALID`.
- Relevant Python/PowerShell suite: `102 passed`.
- Ruff: clean.
- PowerShell parser: clean.
- Real top-level `PreflightOnly`: `BLOCKED`, wrapper exit `0`, `no_run_or_output_writes=true`, campaign root absent.
- Independent exact-SHA review: no P0-P3 findings.
- Authoritative guard: `USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT`; PIT schedule remains active.
