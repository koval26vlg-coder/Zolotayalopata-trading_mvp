# AEF causal materialization runtime/integrity handoff

- Recorded local: `2026-08-02T00:27:17+03:00`
- Factory: `ACCELERATED_EVIDENCE_FACTORY_V1`
- Campaign candidate: `dense_ws_microstructure_regime_filter_v1_20260802_aef`
- Candidate contract hash: `905f5f18a2028733894aef112ac857d7c1cecc005fc39ed8c55ac418beafcf5e`
- Scope: bounded offline implementation and tests only.

## Implemented

- Added an internal monotonic deadline to raw hashing, JSONL normalization,
  stream merge, sample processing, and immutable publication.
- Enforced `1 <= max_runtime_sec <= 1800`; runtime expiry removes temporary
  files and returns `STOPPED_INCOMPLETE_RUNTIME_LIMIT` without final outputs.
- Replaced sequential overwrite-capable publication with atomic NTFS hard-link
  publication, no-overwrite semantics, manifest-last ordering, and rollback of
  already-published outputs after any later failure.
- Added campaign-root checks for the quality report, segment manifests, raw
  files, and all materialization outputs. A rehashed quality report cannot bind
  raw evidence outside the frozen campaign namespace.
- Added `tools/run_dense_ws_causal_materialization_visible.ps1`: a visible,
  synchronous, guard-aware, weekly-quota-aware, PIT-priority-aware wrapper. It
  does not write the active-run gate and cannot start a collector.
- Added file-level E2E coverage for raw MEXC protobuf and Gate JSONL through
  causal labels, execution snapshots, immutable hashes, and final manifest.
- Added failure tests for deadline expiry, namespace escape, and partial
  immutable publication rollback.

## Verification

- Python `py_compile`: pass.
- Ruff `0.14.0`: pass.
- PowerShell parser for the visible wrapper: pass.
- Linked contract/quality/materializer regression: `35/35` pass.
- Full fast regression: `215/215` pass, failures `0`, errors `0`.
- Fast regression deterministic result hash:
  `041e2329467f64dd5fe2acc04748b405425f2903dd014635dba613129a6b971a`.
- Target campaign drive `E:` verified as fixed NTFS with more than 825 GB free,
  so hard-link publication is supported on the intended output volume.

## File hashes

- `trading_mvp/src/dense_ws_causal_materializer.py`:
  `db9dfc04306ab9d4814ce2f5af6957267c34e497c87398a2ef7be00b7bd3065c`
- `trading_mvp/tests/test_dense_ws_causal_materializer.py`:
  `50eec3295b3fc1d76e06c1a54675139ca9649268a04b44fa270572a7aa856cc2`
- `tools/run_dense_ws_causal_materialization_visible.ps1`:
  `af2fe4a076d5fb0ff7a1b330e774828d01831ad6690bea04c1b393088ae1d62e`

## Authoritative state after verification

- Autopilot: `ACTIVE`.
- Decision: `USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT`.
- Weekly telemetry: `AVAILABLE`, remaining `88%`.
- Gate: `READY_FOR_POSTPROCESS`, run
  `resolved_incomplete_20260801_220204534`.
- Approved PIT schedule: `pit_universe_v2_forward_20260802_n05`, start
  `2026-08-02T01:00:00+03:00`, duration `1200` seconds.
- AEF contract and PlanOnly remain absent; `actual_collection_allowed=false`.

## Next exact actions

1. Give the preapproved PIT `n05` segment priority when it becomes due; launch
   only through the top-level visible countdown and never create a duplicate.
2. Freeze and build the AEF contract/immutable PlanOnly only after the exact
   current candidate hash-bound contract-freeze checkpoint is satisfied.
3. AEF collection remains a separate long-campaign approval after the PlanOnly
   exists. This handoff is not collection approval.

## Safety

- No collector, network writer, replay, OOS, returns, PnL, grid, retune,
  paper-forward, live order, private API, leverage, or margin action was run.
