# trading_mvp Gate historical membership v2 PlanOnly

## Metadata

- Time: `2026-07-17 06:35 +03:00`
- Agent: `Codex`
- User request: start moving the One-Week Historical Edge Sprint without idle waiting.

## Plan

1. Verify the active-run gate and frozen v2 hashes.
2. Complete the bounded offline implementation and verification path.
3. Preserve the public network probe behind the exact hash-bound approval.

## Completed

- Active-run gate is `READY_FOR_POSTPROCESS`; no collector is running.
- The old Gate spot/perp branch remains closed as train-infeasible with `replay_allowed=false`.
- Confirmed frozen v2 plan hash `6dbd939b31327af6e09f01cf6773931f0fcf7d0dfc7ec52a4821d30f84d47aed` and module SHA-256 `e1aa13cae17d45c7b15a1d246a1d1508b7b18a2070b01a013aa7b79ca22b4bae`.
- Confirmed the v1 supersede record; v1 is not executable because it omitted the contract multiplier needed for quote-volume reconstruction.
- Added and verified the v2 public probe, history PlanOnly, resumable archive collector, history-quality stage, CLI actions, visible launchers, and unit tests.
- No public network probe or archive collector was launched in this checkpoint.

## Verification

- Python compile: passed.
- PowerShell parse: passed for three entrypoints.
- Targeted unit tests: `24/24 OK`.
- Previous full regression: `974 OK`, `5 skipped`.
- Frozen plan and module hashes remained unchanged.

## Files

- `trading_mvp/src/gate_historical_membership_v2.py`
- `trading_mvp/src/gate_historical_membership_history_plan.py`
- `trading_mvp/src/gate_historical_membership_history_collector.py`
- `trading_mvp/src/gate_historical_membership_history_quality.py`
- `trading_mvp/run_mvp.ps1`
- `tools/start_gate_historical_membership_v2_probe_visible.ps1`
- `tools/start_gate_historical_membership_history_collect_visible.ps1`
- `trading_mvp/tests/test_gate_historical_membership_v2.py`
- `trading_mvp/tests/test_gate_historical_membership_history_plan.py`
- `trading_mvp/tests/test_gate_historical_membership_history_collector.py`
- `trading_mvp/tests/test_gate_historical_membership_history_quality.py`
- `docs/analysis/2026-07-17-gate-membership-v2-repair.md`

## Risks and limits

- Public Gate archive availability is not assumed; the metadata probe must establish an eligible canonical universe first.
- Historical OHLCV/funding can support only a historical verdict, not fill or live readiness.
- Current network probe requires the exact frozen approval phrase; generic continuation is not treated as that approval.

## Next agent checkpoint

After exact approval, launch only `gate_historical_membership_v2_20260717_055756` through the visible wrapper with `MaxRuntimeSec=600`. On technical accept, freeze a new history PlanOnly; do not start history collection automatically.
