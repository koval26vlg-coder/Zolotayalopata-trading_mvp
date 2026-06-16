# Funding collect partial diagnostics at 100 cycles

## Context
- Active objective remains research-only: no live orders, no API keys, no leverage/margin execution.
- The 24h funding collector is still running, so final-review/postprocess was not run.
- This diagnostic is not an acceptance decision and must not be used as final strategy validation.

## Collector audit
- Audit artifact: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_goal_audit_partial_20260616_055301.json`
- Stage: `collecting_funding`
- Ready for postprocess: `false`
- Collector status: `running_or_waiting`
- Completed cycles: `100 / 288`
- Remaining cycles: `188`
- Progress: `34.72%`
- Rows: `2400`
- Errors: `600`
- Last write: `2026-06-16T05:51:47+03:00`
- Blockers: `collector_not_ready`, `readiness:status_not_final`, `readiness:data_quality:min_completed_cycles`, `readiness:data_quality:min_unique_cycles`

## Diagnostic artifact
- Output: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_partial_diagnostics_20260616_0553.json`
- JSON parse check: passed
- Rows match manifest: `true`
- Unique cycles: `100`
- Eligible rows: `1575 / 2400` (`65.62%`)
- Positive expected net carry rows: `0`
- Best partial `expected_net_carry_bps`: `-22.41`
- Manifest error breakdown:
  - `mexc:match_contract:no_perp_contract`: `400`
  - `gateio:match_contract:no_perp_contract`: `200`

## Interpretation
- The current partial data is structurally stable: 24 rows and 6 known match-contract errors per cycle.
- Early economics are weak under current cost assumptions: every collected row has negative `expected_net_carry_bps` so far.
- This is not a final verdict because the dataset is only 100/288 cycles and strict readiness still rejects it.

## Decision
- Final-review was not run because strict readiness still rejects the dataset.
- Continue condition-based readiness checks. Run strict final-review only after the collector is final and quality gates pass.
