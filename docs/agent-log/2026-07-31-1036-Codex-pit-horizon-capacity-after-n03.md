# PIT horizon capacity after n03

- Время: `2026-07-31 10:36 +03:00`
- Агент: Codex
- Режим: read-only schedule/provenance projection; без market rows, returns, PnL, OOS, collector, replay, grid или retune.

## Текущее состояние

- Authoritative PIT progress: `5/20` принятых дат.
- Active schedule hash:
  `31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7`.
- Active schedule status:
  - `MISSED`: 2;
  - `COMPLETED`: 1;
  - `PLANNED`: 11.
- Даже если все 11 оставшихся active segments будут приняты, active schedule доведёт track только до `16/20`.

## Extension candidate

- Plan path:
  `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_extension_planonly_20260812_from_31b4b6c7_v1.json`.
- File SHA-256:
  `58f84c63d83da30ada0491d7bdd7c51e7202b7d090ab666a0fcb3cc2664b6297`.
- Embedded plan hash:
  `a0b79dbdb9a6ebe5843e118b7e69465eb6a998708eb429b42117379ade7fa491`.
- Five proposed segments: `2026-08-12` through `2026-08-16`.
- Maximum reachable total with active schedule plus extension: `21/20`.
- At least four of five extension segments must be accepted; extension failure budget is one date.

## Integrity boundary

- Current extension candidate is not approvable as-is:
  - it is sealed against `initial_accepted_distinct_dates=4`;
  - its ledger SHA predates accepted `n03`;
  - authoritative guard already marks horizon freshness as
    `REFRESH_REQUIRED_AT_APPROVAL_WINDOW`.
- Do not activate, approve or rewrite it now.
- At or after `2026-08-10 19:00 +03:00`, rebuild the horizon through
  `tools\build_pit_schedule_horizon_extension_planonly.ps1` using new
  versioned immutable paths, bind the current quality-ledger hash, re-read the
  guard, and only then request the exact hash-bound schedule approval.

## Next

- Preserve the active schedule and launch `pit_universe_v2_forward_20260801_n04`
  only when it is `DUE`.
- Keep the goal `ACTIVE`; calendar waiting is not a blocked state.
