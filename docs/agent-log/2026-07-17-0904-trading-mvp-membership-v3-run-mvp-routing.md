# trading_mvp membership-v3 run_mvp routing

- Added `fast-edge-membership-v3-source-plan` to `trading_mvp/run_mvp.ps1` for bounded offline PlanOnly generation.
- Added `fast-edge-membership-v3-source-probe` as a fail-closed route: direct network execution is rejected and the error returns the exact visible wrapper command.
- Added `CoinRegistryPath` to declared offline gate reads.
- Frozen module `gate_historical_membership_v3.py` was not changed. Its SHA256 still matches the immutable plan.
- Offline route smoke reproduced plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- Direct probe smoke exited nonzero before network and created no output.
- Tests: 56 related membership/history tests passed; 26 PowerShell/v3 tests passed; PowerShell parse passed.
- Full `unittest discover` exceeded the bounded 300-second check and was terminated. It is not recorded as a pass.
- No v3 public network probe was launched. Exact hash-bound approval remains required.

