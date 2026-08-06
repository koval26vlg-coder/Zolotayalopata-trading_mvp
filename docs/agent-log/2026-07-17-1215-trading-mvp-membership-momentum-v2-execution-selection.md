# trading_mvp membership momentum-v2 causal execution selection

## Request

The user repeated the exact approval for `gate_historical_membership_v2_20260717_055756`.

## Verified run state

- Active-run gate: `READY_FOR_POSTPROCESS`.
- The approved v2 run was already final: `1/1` cycle, `1387` rows, `0` errors.
- The frozen source-quality verdict is terminal: `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Delisted-end coverage was `0.3830`, below the frozen `0.90` gate.
- No duplicate v2 network run was launched.
- The separately frozen membership-v3 archive-source probe was not launched because it has a different plan hash and approval boundary.

## Implementation

- Added `trading_mvp/src/gate_membership_momentum_v2_execution_selection.py`.
- Added `trading_mvp/tests/test_gate_membership_momentum_v2_execution_selection.py`.
- Added `run_mvp.ps1` actions:
  - `fast-edge-membership-momentum-v2-execution-selection`
  - `fast-edge-membership-momentum-v2-execution-selection-validate`
- Changed the execution-probe PlanOnly transition from the nonexistent combined select/collect action to the implemented causal selection action.

The selection artifact is fail-closed and hash-bound to:

- a valid historical momentum-v2 OOS ACCEPT;
- the execution-probe PlanOnly hash and file hash;
- a public Gate USDT-linear daily-market manifest hash and file hash;
- current module hashes and an input Merkle hash.

Selection is allowed only after the target signal daily close and before the first execution window. It uses exactly the frozen 30-day momentum, seven-day median quote-volume threshold, minimum 20 scored markets, and deterministic long/short bucket rule. Future/open bars, duplicate canonical identities, manual shortlists, threshold weakening, OOS event names/frequency, grid and retune are rejected.

## Verification

- TDD RED observed: module missing.
- New selection tests: `7/7 OK` after PowerShell routing test was added.
- Execution-probe plus selection targeted tests: `15/15 OK` before the routing test; affected shard later passed.
- Membership/history/PowerShell regression: `75/75 OK`.
- Canonical full suite: `1038 OK`, `5 skipped`, `0 failed`, runtime `298.254s`.
- Python compile: OK.
- PowerShell parser: OK.
- Deterministic PowerShell validation smoke: `valid=true`, decision `GATE_MEMBERSHIP_MOMENTUM_V2_EXECUTION_SELECTION_READY`, `10` fixture positions, artifact hash `6104976043a483599824791dbc1a4b1bfe6624b3c429d784fb157256db33d625`.

## Boundaries

- No public network collector was launched.
- No real selection artifact was produced.
- No returns, PnL, train/OOS result, execution probe, paper-forward or live action was run.
- No edge or profitability is proven by this tooling work.

## Next external gate

The only new network action remains the separately frozen visible membership-v3 archive-source probe. It requires its own exact approval for plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3` and run id `gate_membership_v3_archive_source_20260717_0845`.
