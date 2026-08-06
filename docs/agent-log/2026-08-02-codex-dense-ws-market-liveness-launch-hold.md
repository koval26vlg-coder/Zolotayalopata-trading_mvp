# Dense WS market-liveness launch hold

- Found a launch-blocking evidence defect in the frozen raw writer and quality boundary check.
- A silent open WebSocket can reach the duration deadline as `completed=true` with zero market messages.
- Quality checks gaps only between observed events, so a long silent tail can still pass.
- Preserved the old contract, PlanOnly, receipt, writer, runner, and quality files unchanged.
- Suspended only the old dense campaign approval in the autopilot policy.
- Kept the goal `ACTIVE`, `stop_new_actions=false`, and PIT n06 scheduled for 2026-08-03 01:00 +03:00.
- Updated the active heartbeat to bind policy SHA-256 `33ad7a32e28fd396da7ee7d7cf1e3b2c08f5dcf42fac930a2cb7525a9103330f` and prohibit the old dense launch.
- Old dense launcher PreflightOnly now fails closed with `policy.candidate.status mismatch`.
- Local no-network regression suites passed: 56 tests, 0 failures, 0 errors.
- Audit: `docs/agent-log/readiness/dense-ws-market-liveness-integrity-audit-20260802T2110+0300.json`.
- Refreeze proposal hash: `cb070b3d88b23ff4a1cc46dbd68407d467f4c8ed110ee870d0fd72a5e4e5be3a`.
- No collector, evaluator, returns/PnL/OOS, grid/retune, paper/live, private API, capital, leverage, or margin action was run.
