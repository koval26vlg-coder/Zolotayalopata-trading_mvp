# trading_mvp paper causal funding checkpoint

Date: 2026-07-17 16:03 +03:00

## Result

- Paper execution evidence now requires actual `execution_ts` for both entry and exit and validates each timestamp against the frozen execution window.
- Paper funding evidence is derived from normalized Gate funding history. Pre-summed `funding_rate_sum` input is no longer trusted.
- Every settlement must be strictly inside the hash-bound holding interval `entry_ts < settlement_ts < exit_ts`.
- The adapter infers funding interval and phase from the observed settlement sequence, requires at least `0.80` confidence for both, and requires final settlement coverage of at least `0.98`.
- The transitive chain is now `entry/exit source hashes + funding history hashes -> funding raw input -> immutable raw manifest -> source -> evidence -> event -> ledger`.
- Added offline CLI `build-funding-raw` and PowerShell action `fast-edge-membership-momentum-v2-paper-funding-raw`; runtime remains bounded to `MaxRuntimeSec<=1800`.

## Verification

- Targeted paper tests: `10/10` passed.
- Fifteen-event lifecycle test passed.
- Python compile: passed.
- PowerShell AST parse: passed.
- CLI help smoke for `build-funding-raw` and `build-source`: passed.
- Full regression: `1069 OK`, `5 skipped`, `0 failures` in `536.037s`.
- Full test log: `C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\2026-07-17-paper-causal-funding-full-tests.log`.

## Active research state

- No network collector, OOS, grid, paper-forward or live action ran.
- No edge is proven by this checkpoint.
- Membership-v2 remains terminally rejected because delisted-end coverage is `0.3830 < 0.90`.
- The only next network action remains the exact-approved visible membership-v3 archive-source probe with plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- A real paper entry/exit depth collector remains a future runtime gap; normalized execution source fixtures are not market evidence.
