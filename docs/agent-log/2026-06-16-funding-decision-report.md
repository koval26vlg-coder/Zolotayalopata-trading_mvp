# Funding Decision Report - 2026-06-16 03:39 local

## Objective
Continue the research-only `trading_mvp` goal for non-Binance markets by formalizing stage acceptance. The goal is to prevent manual promotion to paper-forward unless status, gate, frontier, sensitivity, OOS, and walk-forward metrics all pass.

No live orders, no API keys, no investment advice.

## Collector Status
- Input: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Status: `running_or_waiting`
- Final: `false`
- Ready for postprocess: `false`
- Completed cycles: `76 / 288`
- Rows: `1824`
- Errors: `456`
- Progress: `26.39%`
- Last write age at final check: `134s`

Readiness blockers:
- `status_not_final`
- `data_quality:min_completed_cycles`
- `data_quality:min_unique_cycles`

## Implementation
Added `funding-decision-report`:
- reads `funding-status` readiness directly from the collect JSONL/manifest;
- combines gate report, frontier report, and sensitivity/stress/OOS/walk-forward report;
- emits a single `verdict`, `accepted` flag, `next_action`, and machine-readable rejection reasons;
- requires final collector readiness before allowing any paper-forward candidate verdict;
- exposes the command through CLI and `run_mvp.ps1`.

Changed files:
- `trading_mvp/src/basis.py`
- `trading_mvp/src/cli.py`
- `trading_mvp/run_mvp.ps1`
- `trading_mvp/tests/test_basis.py`

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK
- Targeted tests: 3 tests OK
- Full tests: 155 tests OK

## Artifact
- Decision report: `exports/trading-mvp/funding/funding_decision_report_partial_20260616.json`
- Artifact size: `7454` bytes

Decision summary:
- Accepted: `false`
- Verdict: `wait_for_final_dataset`
- Next action: `wait_and_recheck`
- Ready for postprocess: `false`
- Gate rank eligible: `0`
- Frontier strict rank eligible: `0`
- Frontier funding gap pass: `0`
- Sensitivity accepted scenarios: `0`
- OOS accepted scenarios: `0`
- Walk-forward accepted scenarios: `0`
- Best net PnL: `0.0`
- Best OOS net PnL: `0.0`
- Best walk-forward average test net PnL: `0.0`

Decision reasons:
- `collector_not_ready`
- `readiness:status_not_final`
- `readiness:data_quality:min_completed_cycles`
- `readiness:data_quality:min_unique_cycles`

## Interpretation
The current branch cannot be accepted or rejected as final yet because the 24h collector is still running. However, the partial decision report already captures the main research state: the carry branch has no eligible rank candidates, no funding-gap pass, and no accepted stress/OOS/walk-forward scenarios.

This report is designed to be rerun after `ready_for_postprocess=true`. Only then can the funding/carry stage be promoted, rejected, or redirected based on verified metrics.

## Next Gate
Continue monitoring until `funding-status --strict-research` returns `ready_for_postprocess=true`, then run:
- `funding-finalize`
- `funding-decision-report` against final artifacts

If the final decision report remains non-accepted, do not move to paper-forward for funding/carry. Shift to a narrower high-liquidity universe or prioritize event-driven perp signals.
