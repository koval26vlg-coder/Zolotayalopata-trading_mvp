# trading_mvp: fast-cache provenance audit

Generated: `2026-07-17T01:18:00+03:00`

## Decision

`NO_INDEPENDENT_FAST_CACHE_AVAILABLE`

No existing local dataset can support another materially new, acceptance-grade OOS hypothesis without either reusing already inspected return windows, consuming an incomplete run, or violating a frozen branch closure. A new PlanOnly hypothesis is therefore not opened on the current caches.

This is not a statement that no market edge exists. It is a provenance decision: another test on these inputs would increase multiple-testing risk without adding independent evidence.

## Evidence map

| Dataset | Prior use | Current evidence state | Independent for a new OOS test |
|---|---|---|---|
| `daily_collect_20260702_top200` | Cross-sectional momentum, cross-exchange funding carry, same-venue funding carry | Momentum later rejected for survivorship/look-ahead contamination; funding branches later rejected under base/no-volume fees | No |
| `daily_forward_20260706` | Funding-forward ranking and execution gate | 200-day window `2025-12-18..2026-07-06`; collector had 5 errors; already inspected for carry candidates | No |
| `daily_forward_20260713` | Residual dispersion, lottery MAX, funding-pressure reversal, wick rejection, weekend-liquidity window | All five used the same sealed input Merkle `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`; terminal results were `INSUFFICIENT_DATA`/`NO_FAST_EDGE_FOUND` | No |
| `daily_forward_20260706` vs `daily_forward_20260713` | Same source family and 200-day design | Historical windows overlap by `192.99995` days. Only seven calendar days differ, and the later cache has already been consumed by five hypotheses | No |
| `ws_durable_72h_2exchange_pregap` | Full cross-venue dislocation scan and no-grid liquidity-sweep replay validation | Full scan decision `REJECTED_NO_NET_EDGE_AFTER_BASE_FEES`; full-scan artifact SHA-256 `b1182f82592eb5fc05d29e4b450adb9d9b1a3129c92cb894a85dba8475150169` | No |
| Listing history | Fixed listing-event replay | Decision `LISTING_EVENT_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE`; artifact SHA-256 `c52ea4f6f8c13b49e2266ceaf7785f7139a3700c57d0a795366ce512390a1fe5` | No |
| Slow-liquidity history | Fixed slow-liquidity replay | Decision `SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE`; artifact SHA-256 `62226963ff1b3720d905960b0378d9430aec72f90b151dc51bb188c27cfe1800` | No |
| Historical basis v1 | Five-minute basis sprint | Public retention contract failed (`Candlestick too long ago`); branch closed append-only rather than silently changing the contract | No |
| Historical basis 1h v2 | Basis convergence and funding-regime persistence | Basis branch closed `INSUFFICIENT_EXECUTABLE_UNIVERSE` with 5 survivors vs 8 required; funding-regime branch then consumed the OOS and closed `INSUFFICIENT_DATA` with 11 episodes vs 20 required | No |
| `pit_linear_perp_forward_oos_20260711_211953` | Economic-density diagnostic under its sealed forward plan | Manifest remains `final=false`: 264 attempts, 195 valid cycles, 69 failed cycles, error ratio `26.14%`, `replay_allowed=false`. It was already inspected diagnostically | No |
| `spot_pit_event_forward_20260712_225519` | Spot PIT event diagnostic | Formally archived `REJECTED_INCOMPLETE`; 545 cycles, 719,168 rows, 2 signals and 0 trades; no acceptance gate passed | No |
| `PIT_UNIVERSE_V2_FORWARD` | Current independent shadow track | Only `2026-07-14` and `2026-07-15` are technically accepted dates. The 2026-07-16 segment was rejected only for insufficient dual-venue BBO-size coverage; collector concurrency has since been corrected and verified | Yes, but insufficient today |

## Why the remaining directories do not create a shortcut

1. A different directory or file hash does not make overlapping returns independent.
2. A non-final collector cannot be promoted to OOS evidence after examining diagnostics from it.
3. An `INSUFFICIENT_DATA` result permits a future test only on genuinely new observations, not a new signal fitted to the same OOS window.
4. Historical OHLCV can support train feasibility, but the available MEXC/Gate histories have already been used by the closed fast branches or are blocked by public retention/coverage constraints.
5. Reopening funding, listing, slow-liquidity, spot dislocation or HFT on the same inputs would violate the frozen stop rules.

## Current executable path

- Do not create another strategy branch on the existing caches.
- Keep the corrected PIT collector as the only clean independent evidence track: one visible 20-minute segment per new calendar date.
- The next schedule is sealed but not approved:
  - path: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_ratefix_primary_immutable_sources_planonly_20260716_234212.json`
  - plan hash: `b33e6989d9248f92be3f31ab306848f3f1bf562fc7facc66e000caaf493cf2a1`
  - first eligible segment: `2026-07-17T23:00:00+03:00..2026-07-17T23:20:00+03:00`
- Until a new date is collected, productive work is restricted to paper-only product hardening, deterministic fixtures, code-only baseline/reproducibility and provenance maintenance. These tasks must not read embargoed returns or alter the sealed collector inputs.

## Next decision gate

After each technically accepted PIT date, update only identity, coverage and capacity evidence. Do not inspect PnL before the frozen train-feasibility gate. At 10 accepted dates, run the blind futility check; at 20 accepted dates, run train feasibility once. A failed gate closes the branch without retuning.
