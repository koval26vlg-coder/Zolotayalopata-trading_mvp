# trading_mvp PIT 10-date futility gate

Timestamp: `2026-07-17T01:58:46+03:00`

## Result

- Implemented an independent embargo-safe 10-date futility checkpoint without modifying any runtime file sealed by the current PIT schedule.
- Added immutable PlanOnly sealing of the earliest 10 technically accepted dates.
- Added deterministic two-repeat evaluation of event frequency and executable-entry eligibility only.
- The checkpoint does not read returns, compute PnL, inspect OOS, tune parameters, run a grid, use network access, or enable execution.
- A branch can close early only when the optimistic one-sided 90% upper bound still misses a frozen OOS sample gate.
- The futility result is forbidden as acceptance evidence. A non-futile result only permits continued train accrual to the 20-date feasibility gate.

## Files

- `trading_mvp/src/pit_membership_drift_futility.py`
  - SHA-256: `7a2b3b3551164180cf2dcb79d867331cea386224593bce92a725d6fb4e9c54a8`
- `trading_mvp/tests/test_pit_membership_drift_futility.py`
  - SHA-256: `2b86d50b936d601f1582fd3f55edd20fed0ec117460289f3b35946f3d3cd6388`
- `trading_mvp/run_mvp.ps1`
  - SHA-256 after wiring: `38b31072ee05af0a99de97312070caa9aa688796ba0c834d2a6a26ac645dcbf2`
- `trading_mvp/tests/test_powershell_tooling.py`
  - SHA-256 after wiring: `048dcf71b5c4f4f239698b949d1b72374b515e82e4af6f4d8f6de74a98437452`

## CLI

- `fast-edge-pit-futility-plan`, hard cap `1200s`.
- `fast-edge-pit-futility-evaluate`, hard cap `1800s` and expected plan hash required.

## Verification

- TDD red state confirmed before implementation: missing futility module.
- Targeted module and PowerShell wiring: `26 tests`, `OK`.
- Full regression: `903 tests in 559.436s`, `OK`, `5 skipped`.
- Python compile: passed.
- PowerShell parser: passed.
- All 12 runtime-tool hashes sealed in schedule `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1` still match exactly.
- Real-ledger fail-closed smoke: `observed=2, required=10`; no premature plan or result artifact was created.

## Runtime state

- Active run gate: `READY_FOR_POSTPROCESS`; no live collector process.
- Technically accepted PIT dates: `2` (`2026-07-14`, `2026-07-15`).
- Latest corrected schedule remains unapproved:
  - `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_primary_immutable_sources_planonly_20260716_234212.json`
  - plan hash: `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1`
- The active heartbeat automation referenced obsolete schedule `14f687...`; it was paused to prevent a stale nightly collector launch.

## Next allowed step

After exact hash-bound approval of schedule `b33e...`:

1. Replace the paused heartbeat prompt with the corrected schedule and retain visible-only collection.
2. Collect and technically certify at most one 20-minute segment per new date.
3. At exactly 10 accepted dates, build the immutable futility PlanOnly and run the deterministic futility evaluation once.
4. On `FUTILE_CLOSE_BRANCH_BEFORE_TRAIN`, close without OOS or retune.
5. On `CONTINUE_TO_20_DATE_TRAIN_GATE`, keep collecting to 20 dates and run the existing train feasibility gate.

Exact approval phrase:

`Подтверждаю ночное расписание trading_mvp plan_hash=b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1 на 2026-07-17T23:00:00+03:00..2026-07-30T23:20:00+03:00, data_type=PIT_UNIVERSE_V2_FORWARD, stage=train_accrual, visible terminal, без grid/live/API keys.`
