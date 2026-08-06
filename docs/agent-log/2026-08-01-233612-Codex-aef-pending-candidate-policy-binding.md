# AEF pending candidate policy binding

- Observed at: `2026-08-01T23:36:12+03:00`
- Actor: `Codex`
- Scope: pending-state reconciliation only; no contract freeze or launch

The authoritative autopilot policy still pointed at the superseded
`dense_ws_microstructure_regime_filter_v1_20260731_weekend` candidate and asked
to implement timing headroom/global writer controls that are already complete.
The pending pointer was reconciled to the approved AEF proposal without creating
or approving an immutable campaign contract.

- Policy SHA-256 after reconciliation:
  `f81f64dd54a3a9396b2581796bd2e50efa722168cc38f4b12fd0546bafef16ad`.
- Pending campaign:
  `dense_ws_microstructure_regime_filter_v1_20260802_aef`.
- Factory profile: `ACCELERATED_EVIDENCE_FACTORY_V1`.
- Candidate contract hash:
  `905f5f18a2028733894aef112ac857d7c1cecc005fc39ed8c55ac418beafcf5e`.
- Feasibility SHA-256:
  `3b2a4421c5548730b7974972395d80e0a543b36d95c04f2a045113bbb146d8ee`.
- State: `NOT_BUILT_AWAITING_EXACT_CONTRACT_FREEZE`.
- `contract_path`, `contract_hash`, `plan_path`, and `plan_hash` remain null.
- `actual_collection_allowed=false`.
- The old candidate is retained in the policy only as a superseded lineage
  record and remains non-launchable.

Authoritative guard result after the edit:

- `status=ACTIVE`
- `decision=USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT`
- `critical_checkpoint_notification_required=true`
- `next_action=freeze_dense_ws_data_contract_and_build_immutable_campaign_planonly`
- weekly remaining `90%`
- PIT n05 `WAITING`, start `2026-08-02T01:00:00+03:00`
- no active market-data writer

The existing `trading-continuous-production` heartbeat is `ACTIVE` and remains
scheduled for `00:55` local, five minutes before PIT n05. It explicitly forbids
freezing or launching the AEF candidate without the required exact approvals.

