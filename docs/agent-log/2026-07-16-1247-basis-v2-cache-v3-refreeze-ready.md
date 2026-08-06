# trading_mvp basis-v2 cache v3 and final refreeze ready

Date: 2026-07-16 12:47 +03:00

## State

- Goal remains active: One-Week Historical Edge Sprint.
- Active-run gate is `READY_FOR_POSTPROCESS`; no market-data writer is running.
- No history collect, OOS, execution probe, grid, paper-forward market process, live order, private API key, leverage, or margin action was started.
- PIT shadow schedule remains independent and unchanged.

## Cache fix

- Replaced plan-bound candle cache v2 with content-addressed cache v3.
- Cache identity now binds venue, symbol, series, closed hourly window, public endpoint/base URL, interval, request stack, and normalization contract.
- `plan_hash` is not part of cache identity. The immutable cache records `origin_plan_hash`; each run manifest remains bound to its current PlanOnly.
- Quality validates `data_request_hash`, request descriptor, cache file SHA-256, and rows SHA-256. It accepts reuse from another valid PlanOnly only when the public-data request is identical.
- Candle semantic Merkle now uses `data_request_hash` plus `rows_sha256`, not non-semantic cache metadata.

## Verification

- TDD RED: a second valid PlanOnly with identical data request performed 48 additional fixture calls and had 0 cache hits.
- TDD GREEN: the second PlanOnly performs 0 additional calls, reports 48/48 cache hits, marks every cache as cross-plan reuse, and leaves cache files byte-identical.
- Collector and quality tests: 17 passed.
- All `historical_basis_v2*` tests: 93 passed.
- Full regression: 861 passed, 5 skipped, 0 failed in 319.803 seconds.
- Full log: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\full_tests_basis_v2_cache_v3_20260716.log`.
- Python compilation and `git diff --check` passed.

## Final frozen artifact

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\plans\basis_v2_planonly_20260716_124214.json`
- Plan hash: `1a5cc89ff97fbe9e97a7ba282a675df5dfda6b89592e2e9b4a2a0e91cf9e24dc`
- Plan file SHA-256: `3a61550f17f2443308bdde11a2c6173755be50e78afeb9385519fc0bf72ea362`
- Code snapshot hash: `7b53fcda0e73fb28c592a7a7db0e3d86905684969cdfcc733b4fb828f6b3ef34`
- Snapshot manifest SHA-256: `006714a3bfffb7b94513bd3a845a530f96282162d879dade9e7c71d15f0d42cf`
- Snapshot source hashes match the working collector, quality, evaluator, execution-probe, and paper-OMS modules.
- Previous plan hash `ae2ff278e5efe5c4885b9917fa60ea23d1c09db2012fd7f439790eb2751d04d1` and all earlier v2 plan hashes are archival and must not be collected or evaluated.

## Next gated action

PlanOnly preview passed with 20 candidates, 360 estimated public requests, 750 estimated seconds, 1200-second hard runtime cap, and 780.522 GiB free on the output volume. It did not access the network or start a collector.

Exact approval phrase:

`Подтверждаю visible basis-v2 history collect plan_hash=1a5cc89ff97fbe9e97a7ba282a675df5dfda6b89592e2e9b4a2a0e91cf9e24dc, run_id=basis_v2_history_20260716_124500, MaxRuntimeSec=1200, hard deadline=2026-07-16T22:00:00.0000000+03:00, public API only, без grid/OOS/live/private API keys.`

After exact approval, start only this visible collector. Then run data quality; train feasibility is allowed only after quality acceptance, and OOS remains embargoed until train feasibility passes.
