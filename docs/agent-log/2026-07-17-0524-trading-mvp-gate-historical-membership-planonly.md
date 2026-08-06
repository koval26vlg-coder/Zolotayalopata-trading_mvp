# trading_mvp Gate historical membership PlanOnly

- Active gate checked: `READY_FOR_POSTPROCESS`; closed spot/perp basis branch remains rejected at train with OOS unread.
- Confirmed official Gate endpoint: `/api/v4/futures/usdt/contracts_all` includes delisted contracts and lifecycle fields.
- Added `trading_mvp/src/gate_historical_membership_v1.py`.
- Added `fast-edge-membership-plan` and `fast-edge-membership-probe` actions to `trading_mvp/run_mvp.ps1`.
- Added deterministic plan hash, code hash binding, bounded pagination, cache reuse and resumable `STOPPED_INCOMPLETE` probe reports.
- Added `trading_mvp/tests/test_gate_historical_membership_v1.py`.
- Verification: `44 OK`; PowerShell parse OK; offline hash authorization OK.
- Current plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_plan_20260717_052145.json`.
- Current plan hash: `07ea7df9103792cf45e56dfe96217c061b10bab35e6817110e3650ef5319bcf8`.
- Network requests: 0. Returns/PnL/signals/OOS read: false.
- Next allowed action: explicit hash-bound visible public probe only.
