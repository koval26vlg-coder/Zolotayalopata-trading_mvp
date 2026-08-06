# trading_mvp PIT train-accrual n01

## Request

User supplied the exact hash-bound approval phrase for schedule `34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362`.

## Execution

- Approval record created and validated; SHA-256 `e0d8fffa881056927209ebba904387215e4d315bcf6d7a929860019d804676a4`.
- Visible Windows Terminal launcher started only the sealed run id `pit_universe_v2_forward_20260714_n01` at the approved boundary.
- Collector PID `10320` ran for `1200` seconds with `300`-second start-to-start cadence.
- No duplicate collector, hidden collector or auto-resume was used.

## Technical result

- Final manifest SHA-256: `c382adb86953a0515d20c66f5ab5d599a8ac773afde6795058dc8a0dcfb053b1`.
- `4` cycles, `6,788` rows, `0` errors, both exchanges in every cycle.
- MEXC depth targets/completed: `208/208` in every cycle; coverage `1.0`; depth errors `0`.
- Stop condition: `duration_sec`; collector exited normally.

## Quality result

- Decision: `PARTIAL_PIT_QUALITY_CERTIFIED`.
- Segments evaluated/accepted/rejected: `1/1/0`.
- Certification id: `13bb63cb6f0169fcfffa94b5650ef7ea95db3931d098662fb873e1a478e3ed91`.
- Quality report SHA-256: `714adf386c8749d5d795bb47e042603ce439dba0f3d149833ed15e80c4407727`.
- Ledger SHA-256: `e095c035deeaa03178217522610031a3f1f57338761075ca8f460d967657865e`.
- Accepted train dates: `1/20`; feasibility gate remains closed.
- Technical market rows were read only by the quality certifier. Returns and PnL were not read.

## Scheduler

- Heartbeat id: `pit-visible-night-segments`.
- It runs one daily scheduler checkpoint before the next approved window, certifies any prior completed segment, prevents duplicates and launches only the sealed due run id in a visible Windows Terminal.
- It never auto-resumes `STOPPED_INCOMPLETE` runs and cannot run OOS/grid/replay/probe/paper/live/API-key actions.

## Next step

Wait for the approved visible segment `pit_universe_v2_forward_20260715_n02`. Do not run other research work while a segment is active. At `20` accepted train dates, stop accrual and run frozen train-feasibility before any OOS schedule.
