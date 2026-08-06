# Accelerated Evidence Factory v1: causal materializer handoff

## Authority and runtime state

- User authorized terminating `Antigravity.exe` and `language_server.exe`, accepting loss of unsaved work, then restoring guard/gate and continuing Accelerated Evidence Factory v1.
- Both target processes remain absent after termination; no automatic respawn was observed.
- Authoritative guard observed at `2026-08-01T21:04:46.794475Z`:
  - status: `ACTIVE`
  - decision: `USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT`
  - gate: `READY_FOR_POSTPROCESS`
  - weekly remaining: `89%`
  - PIT run: `pit_universe_v2_forward_20260802_n05`, `WAITING`, start `2026-08-02T01:00:00+03:00`
  - AEF campaign: `dense_ws_microstructure_regime_filter_v1_20260802_aef`
  - AEF contract/PlanOnly: not built; actual collection remains forbidden

## Implemented fail-closed evidence stages

- Added deterministic streaming causal regime and execution-snapshot materialization over accepted, hash-bound dense-WS segment data.
- Enforced full 3600-second causal warmup before any executable `DENSE_BOTH` label.
- Consumed causal BBO events between the final 5-second sample boundary and the segment's actual end without creating a future snapshot.
- Bound `dense_ws_causal_materializer.py` by exact path and SHA-256 in the AEF immutable PlanOnly tool set.
- Changed accepted campaign-quality progression to causal materialization, not directly to train/evaluation.
- Kept automatic progression disabled beyond materialization because the exact signal and evaluator contract is not frozen.
- Added the materializer suite to the bounded fast regression lane.
- Restored complete fixture-only `paper_observer_runtime.py` routing in `run_mvp.ps1`; these routes do not expose live/private functionality.

## Verification

- Targeted AEF suites: `34/34` passed before the tail regression addition.
- Causal materializer suite after tail regression: `4/4` passed.
- Python `py_compile`: passed for changed AEF source/tests.
- Ruff `0.14.0`: passed with no findings for changed Python files.
- PowerShell parser: `run_mvp.ps1` parsed with zero errors.
- Full bounded fast regression: `211/211` passed in `33.286s`.
- Fast regression deterministic result hash: `a6a028911204bf394908ef40fd91ca877fa69588a88df45e46e5fefeeb02977c`.
- No collector, replay, OOS, returns/PnL, grid, retune, paper-forward, live orders, private API, leverage, or margin action was run.

## Source provenance

- `trading_mvp/src/dense_ws_causal_materializer.py`: `bc2bc3333d9c9e54dc8c16225722765c35ed52a44ac3b33fcea399212589c1f4`
- `trading_mvp/src/dense_ws_campaign_contract.py`: `a6da427993cf24fa9207945ad114c8a7ace6a52a08414721f39ba59904b16a5c`
- `trading_mvp/src/dense_ws_campaign_quality.py`: `6796f534ab5018ad54ea3f453c7cf522fe21e8f1d70844cd552ed2cc7c8059b3`
- `trading_mvp/src/fast_regression_lane.py`: `94753b552fa3f07c1d03c895d02ea5d30b890205491d0bc618675aeb724508f9`
- `trading_mvp/run_mvp.ps1`: `16bef6566b3deda42a6765d32da2ad019b2d3cedd37ece9d577e5bfc14f61ef3`

## Bound next actions

1. Keep the goal active; a future PIT window is not a blocked state.
2. Launch PIT n05 only when the approved segment is due or within five minutes, through the top-level visible countdown script and without a duplicate owner.
3. Do not freeze or launch AEF from the generic continuation authorization. The pending candidate remains hash-bound to `905f5f18a2028733894aef112ac857d7c1cecc005fc39ed8c55ac418beafcf5e` and requires an exact contract-freeze decision before immutable Contract/PlanOnly creation.
4. A separate exact campaign launch approval remains required after the immutable plan hash exists.
5. Even after successful collection/materialization, stop at `USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT`; do not infer a trade signal, read returns/PnL/OOS, or begin train/evaluation automatically.
