# 2026-06-16 Funding Paper Decision Gate

## Goal
Add a research-only decision layer after funding paper-forward runs. The gate must not escalate to live trading; it can only accept a completed paper-forward summary for continued paper-forward collection or require research rework.

## Collector Status Before Work
- `funding-status --strict-research`: `ready_for_postprocess=false`
- status: `running_or_waiting`
- cycles: `79 / 288`
- rows: `1896`
- errors: `474`
- error_rate: `0.20`
- readiness blockers: `status_not_final`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Final funding postprocess was not run.

## Code Changes
- Added `funding_paper_decision_report` in `trading_mvp/src/basis.py`.
- Added `default_funding_paper_decision_report_path`.
- Added CLI command `funding-paper-decision-report`.
- Added PowerShell action `funding-paper-decision-report`.
- Added tests for accepted paper-forward summary, missing required metrics, and CLI parser coverage.

## Gate Behavior
The report requires:
- summary mode `funding_paper_forward`;
- status `completed` and `ok=true`;
- research-only safety flags: no live orders, no API keys, no leverage, no margin execution;
- `paper_acceptance.accepted=true`;
- forward coverage accepted for duration, rows, and markets;
- frozen backtest and acceptance configs present;
- required metrics present: `total_trades`, `win_rate`, `expectancy_quote`, `net_pnl_quote`, `max_drawdown_quote`.

Possible outcomes:
- `continue_paper_forward`: extend the paper-forward dataset.
- `paper_rework_required`: fix the plan, collect more forward data, or rework the strategy.

No live trading outcome is emitted.

## Verification
- `python -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py`: OK.
- Targeted tests:
  - `test_paper_decision_report_accepts_completed_paper_forward_summary`
  - `test_paper_decision_report_rejects_missing_required_metrics`
  - `test_cli_parser_accepts_funding_commands`
  - result: OK.
- Full suite: `python -m unittest discover -s trading_mvp/tests`
  - result: `158 tests OK`.
- PowerShell smoke:
  - action: `funding-paper-decision-report`
  - output: `exports/trading-mvp/funding/paper_decision_smoke_report_20260616.json`
  - verdict: `continue_paper_forward`
  - `live_orders=false`

## Artifacts
- `exports/trading-mvp/funding/paper_decision_smoke_summary_20260616.json`
- `exports/trading-mvp/funding/paper_decision_smoke_report_20260616.json`

## Next Gate
When the 24h funding collector becomes final and strict-ready, run `funding-final-review`. If that creates an accepted `funding_paper_forward_plan`, collect a separate forward dataset and run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 `
  -Action funding-paper-forward `
  -FundingPlanPath <funding_paper_forward_plan.json> `
  -InputPath <new_forward_funding_dataset.jsonl> `
  -OutputPath <paper_forward.jsonl> `
  -PaperSummaryOutputPath <paper_forward.summary.json>

pwsh -NoProfile -ExecutionPolicy Bypass -File .\trading_mvp\run_mvp.ps1 `
  -Action funding-paper-decision-report `
  -InputPath <paper_forward.summary.json> `
  -FundingPlanPath <funding_paper_forward_plan.json> `
  -OutputPath <funding_paper_decision_report.json>
```
