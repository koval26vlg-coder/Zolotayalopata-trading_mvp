# Gate Historical Membership v2 Repair

## Status

- The previous `gate_historical_membership_v1` PlanOnly is superseded append-only and must not be executed.
- Root cause: v1 omitted `quanto_multiplier`, so archived contract volume could not be converted to quote notional without an unsupported assumption.
- Frozen v2 PlanOnly is ready, but the public network probe has not been run.
- No returns, PnL, OOS, grid, probe, paper-forward, live orders, private API keys, leverage, or margin were accessed or started.

## Frozen v2

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\gate_historical_membership_v2_20260717_055756.json`
- `plan_hash`: `6dbd939b31327af6e09f01cf6773931f0fcf7d0dfc7ec52a4821d30f84d47aed`
- Plan file SHA-256: `b0bc4da3811acdeb67578fab5963ce7c54a0233867c9a6238700952dcedf0b69`
- Frozen module SHA-256: `e1aa13cae17d45c7b15a1d246a1d1508b7b18a2070b01a013aa7b79ca22b4bae`
- Decision: `GATE_HISTORICAL_MEMBERSHIP_V2_PLAN_READY_AWAITING_EXPLICIT_PUBLIC_PROBE_APPROVAL`

## Implemented pipeline

- Public Gate metadata probe with multiplier/funding interval/order-bound coverage gates.
- Hash-bound visible probe launcher with duplicate prevention and fail-closed `STOPPED_INCOMPLETE` handling.
- Deterministic 220-closed-day history PlanOnly for Gate archive `candlesticks_1h` and `funding_applies` inputs.
- Resumable visible archive collector with cache reuse, gzip CRC/full-read validation, file SHA-256, disk guard, token-bounded concurrency, and a 120-minute runtime ceiling.
- History quality stage with lifecycle masks, duplicate/open/gap checks, no interpolation, funding-settlement alignment, and quote-volume reconstruction as `contracts * close * quanto_multiplier`.
- `run_mvp.ps1` actions for v2 PlanOnly, probe, history PlanOnly, history collect, and history quality.

## Verification

- Python compile: passed for v2 probe, history PlanOnly, collector, and quality modules.
- PowerShell parser: passed for `run_mvp.ps1` and both visible launchers.
- Targeted tests after the final progress-output change: `24/24 OK`.
- Earlier full regression on the same substantive implementation: `974 OK`, `5 skipped`.
- `git diff --check`: no whitespace errors; only the existing LF-to-CRLF warning for `run_mvp.ps1`.

## Next allowed transition

The next transition is one visible public metadata probe, bounded by `MaxRuntimeSec=600`. It does not collect market returns and cannot authorize OOS or live trading.

Exact approval phrase:

```text
Подтверждаю visible Gate historical-membership v2 public probe plan_hash=6dbd939b31327af6e09f01cf6773931f0fcf7d0dfc7ec52a4821d30f84d47aed, run_id=gate_historical_membership_v2_20260717_055756, MaxRuntimeSec=600, public API only, без returns/OOS/grid/live/private API keys.
```

If the probe is accepted, the next step is to freeze a new history PlanOnly. The archive collector still requires its own hash-bound visible-run approval and remains capped at 120 minutes.
