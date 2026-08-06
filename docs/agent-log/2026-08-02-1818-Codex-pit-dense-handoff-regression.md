# PIT to dense handoff regression

- Observed at: 2026-08-02 18:18 +03:00.
- Agent: Codex.
- Goal: prove that the approved dense campaign cannot overlap an unfinished PIT writer or PIT postrun.
- Code inspection confirmed that PIT releases the global writer claim only after the collector publishes `READY_FOR_POSTPROCESS`.
- Dense phase startup fails closed on `RUNNING` and `STOPPED_INCOMPLETE` gates.
- When a PIT gate is `READY_FOR_POSTPROCESS`, dense additionally requires the exact matching `pit_postrun_disposition.status=COMPLETE`.
- Added `test_phase_start_waits_for_exact_pit_postrun_handoff` to cover RUNNING, STOPPED_INCOMPLETE, missing postrun, mismatched postrun identity, and exact COMPLETE handoff.
- Focused test: 1 passed.
- Dense contract plus global writer claim suite: 28 passed.
- Fast regression: 264 passed, 0 failures, 0 errors, 0 skipped, 31.601 seconds.
- Evidence: `docs/agent-log/readiness/pit-dense-handoff-fast-regression-20260802T1815+0300.json`.
- Evidence SHA-256: `4844f6e371fd2f6c5931ca19b4e528e8f2c92c73fe5db69fd939d6206617b8d5`.
- Deterministic result hash: `56d905fd262602f07f703636479f74a5bab1665d9ad673f5d506290f9698614d`.
- No collector, market-data consumer, evaluator, returns/PnL/OOS, grid/retune, paper/live, private API, capital, leverage, or margin action was run.
