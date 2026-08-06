# Night launch readiness preflight

- Result: `READY_WAITING_APPROVED_WINDOWS`.
- PIT n06 dry run: `READY_NOT_DUE`; 12 sealed runtime tools verified; no owner and no output writes.
- Dense WS 24h dry run: `STRUCTURALLY_VALID_NOT_DUE`; no owner and no output writes.
- Disk: 768.406 GiB free; dense campaign hard cap is 25,000,000,000 bytes.
- The PlanOnly `NOT_APPROVED` field is immutable by design. Runtime authorization is the separate exact user approval plus `ConfirmedLongCampaign`.
- Dense postrun remains runtime-refrozen to quality 1800 sec, materialization 1800 sec, total 3600 sec, not before 2026-08-04 01:30 +03:00, hard deadline 02:30 +03:00.
- No collector, postrun, evaluator, returns/PnL/OOS, grid/retune, paper/live, private API, capital, leverage, or margin action was started.

Evidence: `docs/agent-log/readiness/night-launch-readiness-preflight-20260802T180738+0300.json`.
