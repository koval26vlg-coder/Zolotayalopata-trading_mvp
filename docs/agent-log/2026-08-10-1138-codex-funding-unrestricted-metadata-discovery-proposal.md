# Funding unrestricted metadata discovery proposal

- Fresh autopilot guard: `ACTIVE`, weekly remaining `55%`, no active writer; bounded offline work allowed.
- Funding asset policy remains unrestricted: every coin/category is eligible, with MEXC/Gate availability and exact identity gates preserved.
- The current top-200-per-venue cache cannot prove full-universe coverage. Its audit decision remains `CURRENT_CACHE_FIXED_HOLD_STRESS_INSUFFICIENT`; no horizon, signal, universe rank or OOS value was retuned.
- Frozen proposal: `docs/plans/drafts/funding-unrestricted-active-perp-metadata-discovery-proposal-20260810-v1.json`.
- Proposal hash: `0ac65470275e28819583bf6599d57674cda0cf6a523e4dbb1d85583997380f77`.
- Proposal file SHA-256: `8270be9ae66e546e0f5eca4d774d8f85985e732527bab0fc92415766c08b4de0`.
- Future approved scope is limited to the official active-contract endpoints for MEXC and Gate, all active USDT perpetuals, no top-N/Binance/category filters, visible runtime `<=300` seconds, output cap `50 MB`.
- Ticker matches remain provisional and cannot prove same-underlying identity. A separate exact-candidate PlanOnly is required after discovery.
- TDD: red state confirmed before implementation; targeted tests passed `4/4`; all funding tests passed `82/82`; `py_compile`, canonical proposal-hash readback and `git diff --check` passed.
- Swarm command was validated in dry-run only. No independent verdict was claimed; local deterministic boundary tests are authoritative for this freeze.
- No network request, collector, evaluator, OOS value read, returns/PnL, grid/retune, execution probe, paper/live, private API, capital, leverage or margin occurred.
- Next checkpoint: one exact approval bound to the proposal hash and file SHA-256 for offline runtime implementation, synthetic tests and one visible public metadata run. Strategy/data collection remains a later separate checkpoint.
