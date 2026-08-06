# trading_mvp membership-momentum-v2 OOS contour ready

Date: 2026-07-17 11:02 +03:00

## Status

- Active-run gate remained `READY_FOR_POSTPROCESS`; no network writer or live process was started.
- Membership-v2 source remains terminally closed at `delisted-end coverage 0.3830 < 0.90`; it was not relaunched.
- Membership-v3 source probe, archive history, real train and real OOS have not run. No edge is proven.
- The only next network action remains the exact-approved visible membership-v3 archive-metadata source probe with plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.

## Implementation

- Added `trading_mvp/src/gate_membership_momentum_v2_oos.py` as a separate hash-bound OOS PlanOnly/evaluator for the v3 `100d` sealed OOS contract.
- Preserved the frozen strategy and economics without retuning: `30d` lookback, `7d` hold/rebalance, minimum `5` per side, normal/stress costs `46/72 bps`.
- The OOS contract is exactly five non-overlapping `20d` folds. It can schedule at most `10` independent weekly rebalances and requires at least `8` from the same frozen `80%` schedule-coverage rule; limited statistical power is explicit.
- OOS PlanOnly is generated only after a hash-valid v2 train `FEASIBLE` result. Train result validation occurs before any sealed OOS manifest access.
- The evaluator revalidates quality, train plan/result, train/OOS manifests, code hashes, input hashes, lifecycle identity, root containment and non-overlap before reading OOS rows.
- Frozen OOS gates: positive price-only and total expectancy after costs, PF `>=1.2`, stress expectancy `>=0`, bootstrap lower 95% bound `>0`, at least `4/5` positive folds, drawdown `<=10%`, base and rebalance concentration `<=25%`.
- Maximum positive historical verdict is `ACCEPT_FOR_EXECUTION_PROBE`. Historical OHLCV cannot authorize paper/live or prove fill/capacity.
- Added bounded offline CLI routes:
  - `fast-edge-membership-momentum-v2-oos-plan`
  - `fast-edge-membership-momentum-v2-oos`
- Module SHA-256: `132f5c95a662831eadb36a52f08e23f422b435364eda4229f38438c8af454f93`.
- Test SHA-256: `cc1adb010e47dc1506d417d724d01e3529cd8a8cd16401b48dea8140e98a5b58`.

## Verification

- New OOS TDD suite: `6 OK`.
- Related v2 train, legacy OOS and v3 history regressions: `32 OK`.
- Python compile: passed.
- PowerShell parser: passed.
- Full offline suite: `1023 OK`, `5 skipped`, `0 failed`, runtime `279.206s`.

## Next gate

The OOS tooling is ready but cannot be used on synthetic evidence as a project result. The real route remains: visible v3 source metadata probe -> source ACCEPT -> separately approved archive history collect -> quality ACCEPT -> train PlanOnly/evaluation -> only train FEASIBLE may create a hash-bound real OOS PlanOnly. No stage auto-starts the next stage.