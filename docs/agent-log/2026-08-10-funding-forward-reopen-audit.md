# Funding forward branch reopening audit

Date: 2026-08-10.

## Decision

- Audit decision: `CURRENT_CACHE_REQUIRES_MATERIALLY_DISTINCT_PLANONLY`.
- The closed `funding_regime_persistence_carry_v2` strategy is not reopened.
- Same-strategy PlanOnly: not allowed with the current cache.
- OOS evaluation, execution probe, paper-forward and live: not started and not authorized.
- Retune/grid: not used and remains prohibited.

## Frozen inputs

- Hypothesis bank SHA-256: `85ee37afc7e2ba3855084ab9f961cd71677df35894d95263cccd5652a7c317a9`.
- Legacy PlanOnly file SHA-256: `2eebb78dd7fc57f5e0a74ea707e8a9ce2d1dfdd66162dc3b0ad8d1ee5d328cf4`.
- Legacy terminal closure SHA-256: `a821a012c83f9d5b38a76680187f4b38e50f6bf8a6a4b08e5bbd4673b55203cc`.
- Current collector manifest SHA-256: `836f1909a2147b0b514dcfb5cfc389eba819a85d663ea17749bb80dcb222d484`.
- Longitudinal summary audit SHA-256: `ba83e1a769eda8e7725d0e94e0f4fb49980696afff9f913681997111a79d3fe1`.

## Gate evidence

- Historical coverage: `200/90` required days, pass.
- AKE funding rows: MEXC `1200`, Gate `1073`, minimum `180` per leg, pass.
- Frozen summary dual-leg coverage: `1.0`, minimum `0.8`, pass.
- Complete calendar extension after the legacy OOS end: `38` days.
- Current kline resolution: `1d`; legacy entry contract requires the next contiguous `1h` open, fail.
- Independent execution snapshots: `3/180`, fail.
- AKE identity: `OFFICIAL_SAME_ASSET_VERIFIED` in the bound current audit.

Changing the entry from hourly to daily prices is a materially distinct signal/execution contract. It cannot be treated as a resume or as more data for the closed immutable strategy.

## Safety and reproducibility

- Market files were byte-hashed and only their object headers before `rows` were decoded.
- Market row arrays, funding rates, prices, returns, PnL and OOS values were not parsed.
- No collector, evaluator, network market-data task, paper or live process was started.
- Deterministic result hash: `cc2f64c2a95aa3787dbdcfd3e9b9447ba8b1006eaebc02f8e09a5800dbe5ea89`.
- Local audit artifact SHA-256: `127ef671b5808eef4760f9381e22cf86e0d35a98b823da5dafe5ca42e683ef78`.
- Relevant regression: `54 passed`.

## Next allowed checkpoint

Prepare an exact proposal for a materially distinct daily PlanOnly with a pre-OOS candidate freeze, unchanged MEXC/Gate non-Binance scope, fixed base costs, no grid/retune and an OOS embargo. Implementation or evaluation requires explicit user review because the price-resolution and entry contract would change.
