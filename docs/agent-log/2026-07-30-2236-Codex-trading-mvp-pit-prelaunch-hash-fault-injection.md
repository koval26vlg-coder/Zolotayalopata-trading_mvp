# PIT prelaunch hash fault injection

- Observed at: `2026-07-30T22:36:33+03:00`
- Scope: bounded offline test on a temporary synthetic PlanOnly artifact; no real schedule, sealed runtime file, collector, market data, returns, PnL, OOS, grid, retune, paper, or live execution was changed or started.
- Test:
  - supplied valid current paths and hashes for the sealed schedule planner and visible wrapper;
  - supplied a deliberately false SHA-256 for a synthetic `collector` entry;
  - invoked the real countdown wrapper with a unique run id and temporary plan.
- Verified fail-closed behavior:
  - non-zero exit with `Sealed runtime tool hash mismatch: collector`;
  - failure occurred before Python segment authorization;
  - no countdown metadata or immutable launch record was written;
  - no test residue remained under `docs/agent-log/run-gates`.
- Regression:
  - focused visible-pipeline tests: `8/8`;
  - linked schedule, pointer, guard, postrun, train-target, and completion-audit tests: `130/130`;
  - exact `pit_universe_v2_forward_20260731_n03` read-only preflight remains `READY_NOT_DUE`;
  - `12/12` sealed runtime tools verified, `NO_RUN_OR_OUTPUT_WRITES`, matching writer processes `0`.
- Next: preserve the exact current schedule and run the same independent audit again at the visible launch boundary.
