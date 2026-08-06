# trading_mvp STOP-PIT-AND-FIX

Date: 2026-07-10
Mode: research-only; no live orders, API keys, leverage, margin, replay, grid execution, or new collector.

## Run Disposition

- Stopped run: `pit_universe_snapshot_collect_20260709_224521`.
- Retained output: 149 cycles, 244,757 rows, 8 recorded errors.
- The run is non-final and incompatible with the audited v2 PIT contract. It must not be resumed, replayed, or used as strategy evidence.
- Strict quality verdict: `PIT_UNIVERSE_DATA_QUALITY_REJECTED`.
- Rejection reasons: `manifest_not_final`, `cycle_journal_missing`, `cycle_journal_count_mismatch`, `missing_required_fields`, `state_invariant_errors`, `error_cycle_ratio_exceeded`.
- Quality artifact: `E:\trading_mvp\pit-universe-snapshots\pit_universe_snapshot_collect_20260709_224521\data_quality.json`.

## Audit Remediation

| Finding | Implemented control | Status |
| --- | --- | --- |
| H1 mixed run state | Immutable launch record, authoritative `current-run.json` pointer, pointer-first checker, output/PID precedence | fixed |
| H2 PIT survivorship contract | Persistent first/last seen state, cycle-safe tombstones, Binance spot reference/exclusion, BBO/spread/liquidity fields | fixed for new v2 runs |
| H3 unsafe resume | Explicit resume only, writer lock, atomic state/manifest, monotonic counters, strict schema/journal compatibility | fixed; old run rejected |
| H4 optimistic maker fill | Queue consumption plus own-order quantity, partial fills, stale quote rejection | fixed |
| H5 continuous funding PnL | Realized funding only at discrete `next_funding_ts` settlement | fixed |
| H6 daily risk never resets | UTC daily reset plus online MTM drawdown and kill switch | fixed |
| H7 listing horizon fallback | Missing target horizon returns no candle/trade | fixed |
| H8 global execution costs | Venue-aware maker/taker/slippage maps exposed through replay CLI and wrapper | fixed |
| H9 ledger/provenance divergence | Dataset/result hashes, git/runtime/fee/evaluation provenance, append lock/fsync, reconciliation records | fixed for new and reconciled records |

Additional P2 controls:

- Sharded `fast/core/integration/slow` test runner with per-shard timeout.
- Replay grid sorts events once and forwards `assume_sorted=True`.
- WS/perp grid search now fails closed above `max_grid_combinations`, labels all results in-sample, and requires a sealed holdout before acceptance.

Not represented as complete:

- No git commit was created because the user did not request one and the worktree contains unrelated changes.
- Full decomposition of the large CLI/basis modules and a true disk-streaming replay iterator remain maintainability work; neither is required to start the next data-only v2 collection.

## Verification

- PowerShell parser: all scripts under `tools` and `trading_mvp` passed.
- Python compileall: `trading_mvp/src`, `trading_mvp/tests`, and `tools` passed.
- `git diff --check`: passed.
- Full test runner: 435 passed, 5 skipped, 0 failed across 97 fast, 101 core, 90 integration, and 147 slow tests.
- No market-data run was started during remediation.

## Current Gate

- No accepted trading edge.
- Current branch: `forward_pit_universe_event_liquidity_anomaly`, `CONTINUE DATA-ONLY`.
- Replay, grid, paper-forward, and live remain blocked.
- Next step is only a non-starting preview of a new clean PIT v2 collection. Actual collection requires explicit approval and a visible terminal.
