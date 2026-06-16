# Funding final walk-forward gate integration

Date: 2026-06-15

Goal context: research-only validation for non-Binance spot universe. No live orders, no API keys, no leverage, no margin execution.

## Why this step

`funding-walk-forward` existed as a standalone diagnostic, but final research acceptance still depended on full-sample backtest, single OOS, and stress. This step makes walk-forward part of final research evidence so paper-forward cannot be created unless rolling train/test validation also passes.

## Code changes

- `trading_mvp/src/basis.py`
  - `run_funding_postprocess_file(...)` now accepts optional `walk_forward_output_path` and `FundingWalkForwardConfig`.
  - `research_acceptance` now includes `walk_forward_required_passed` and `walk_forward_accepted`.
  - `research_acceptance.reasons` can include `walk_forward_required` and `walk_forward_rejected`.
  - `run_funding_research_finalize_file(...)` now requires `walk_forward_output_path`.
  - Paper-forward plan evidence now records `walk_forward_output`, `walk_forward`, and `walk_forward_config`.
  - Paper-forward gate now requires `walk_forward_required_passed=True` and `walk_forward_accepted=True`.
- `trading_mvp/src/cli.py`
  - Added `--walk-forward-output` to `funding-postprocess` and `funding-finalize`.
  - Added walk-forward window parameters to `funding-postprocess` and `funding-finalize`.
  - Strict postprocess now auto-populates walk-forward output like OOS output.
- `trading_mvp/run_mvp.ps1`
  - Added `-WalkForwardOutputPath`.
  - Passed `FundingWalk*` parameters through `funding-postprocess` and `funding-finalize`.
- `trading_mvp/tests/test_basis.py`
  - Updated postprocess/finalize/paper-plan tests to require walk-forward evidence.
  - Added strict preset assertions for auto walk-forward output.

## Current collector status

Command:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File 'C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1' -Action funding-status -FundingStrictResearch -InputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl' -ManifestPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json'
```

Result:

- `status`: `running_or_waiting`
- `ready_for_postprocess`: `false`
- `final`: `false`
- `completed_cycles`: `11 / 288`
- `manifest_rows`: `264`
- `line_count`: `264`
- `line_count_matches_manifest`: `true`
- `errors`: `66`
- `error_rate`: `0.2`
- readiness blockers: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`

Decision: final `funding-finalize` still must wait for `final=true`.

## CLI smoke

Strict + partial smoke:

- Command used `-FundingStrictResearch -AllowPartial`.
- Result: `status=not_final`.
- Interpretation: strict preset correctly prevents partial postprocess from bypassing `final=false`.

Allow-partial integration smoke:

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_postprocess_walk_allowpartial_20260615.json
```

Related artifacts:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_oos_walk_allowpartial_20260615.json
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_walk_forward_postprocess_allowpartial_20260615.json
```

Summary:

- `ok`: `true`
- `status`: `completed`
- `input_rows`: `264`
- `rank_eligible`: `14`
- `total_trades`: `23`
- `win_rate`: `0.0`
- `net_pnl_quote`: `-3.0867012347819105`
- `expectancy_quote`: `-0.134204401512257`
- `max_drawdown_quote`: `3.086701234781911`
- `oos_accepted`: `false`
- `walk_forward_accepted`: `false`
- `walk_forward.windows`: `9`
- `walk_forward.accepted_windows`: `0`
- `walk_forward.avg_test_net_pnl_quote`: `-1.348555272315479`
- `research_acceptance.accepted`: `false`
- reasons: `full_backtest_rejected`, `oos_rejected`, `walk_forward_rejected`, `stress_rejected`

Interpretation: integration works and the current partial dataset remains rejected. This is expected and is not a live-trading candidate.

## Verification

Compile:

```powershell
& 'C:\Program Files\Python313\python.exe' -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py
```

Result: exit code `0`.

Targeted tests:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_funding_postprocess_can_accept_oos_and_stress_for_final_manifest trading_mvp.tests.test_basis.BasisTests.test_funding_finalize_creates_postprocess_and_paper_plan_when_research_accepted trading_mvp.tests.test_basis.BasisTests.test_paper_forward_plan_requires_accepted_research trading_mvp.tests.test_basis.BasisTests.test_paper_forward_plan_rejects_incomplete_research_gate_evidence trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands
```

Result:

```text
Ran 5 tests in 0.069s
OK
```

Strict preset test:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests -p 'test_basis.py' -k strict
```

Result:

```text
Ran 1 test in 0.013s
OK
```

Full test suite:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 143 tests in 0.430s
OK
```
