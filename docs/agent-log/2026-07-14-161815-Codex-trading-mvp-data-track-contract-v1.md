# trading_mvp data-track contract v1

- Date: 2026-07-14 16:18:15 +03:00
- Agent: Codex
- Request: continue the canonical Fast-First goal after the current daily-data track closed with no accepted edge.

## Context

- Active gate: `READY_FOR_POSTPROCESS`.
- Closed run: `fast_first_v6_weekend_liquidity_window_20260714_145633`.
- Authoritative decision: `NO_FAST_EDGE_FOUND`; `replay_allowed=false`.
- No collector, OOS, replay, grid, probe, paper-forward, live order, API-key, leverage, or margin action was started.

## Completed

- Implemented a fail-closed PlanOnly data-track contract generator in `trading_mvp/src/data_track_contract.py`.
- Wired `fast-edge-data-track-plan` into `trading_mvp/run_mvp.ps1`.
- Bound the contract to a hypothesis-bank entry, declared data type, input Merkle SHA-256, frozen event counts, venue coverage, capacity proxy, and canonical goal hash.
- Added strict hexadecimal Merkle validation and a `MaxRuntimeSec<=1200` runner guard.
- Added unit and PowerShell tooling coverage.
- Documented the contract and synchronized the current goal/new-track plan.

## Verification

- Targeted tests: 29 passed.
- Full regression: 608 passed, 5 skipped.
- Python compile and PowerShell parse: passed.
- Synthetic PlanOnly smoke artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\plans\data_track_contract_smoke_20260714_155800.json`.
- Synthetic feasibility artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\feasibility\data_track_contract_smoke_20260714_155800.feasibility.json`.
- Deterministic repeat hash matched; evaluator confirmed `oos_metrics_read=false` and `pnl_or_returns_read=false`.

## Decision

- The smoke run proves tooling behavior only. It is not market evidence and does not open a real data track.
- The next permitted engineering step is a concrete new-track proposal and feasibility inputs, with `PIT_UNIVERSE_V2_FORWARD` as the current priority candidate.
- Any real collector, public probe, night run, or OOS remains subject to the canonical consent and visible-run gates.

## Risks

- Synthetic counts can produce `FEASIBLE_FOR_OOS`; this must never be interpreted as feasibility of a real market dataset.
- Current v4-v6 daily-data evidence remains closed and must not be retuned.

## Next Agent

Prepare a concrete data-source/universe/runtime proposal for one banked hypothesis, then run the feasibility gate on real metadata before requesting any collection or OOS authority.
