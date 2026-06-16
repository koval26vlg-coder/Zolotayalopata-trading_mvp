# Funding sensitivity walk-forward selection gate

Date: 2026-06-15

Goal context: research-only trading_mvp validation for non-Binance spot universe. No live orders, no API keys, no leverage, no margin execution.

## Objective

Add rolling walk-forward validation into `funding-sensitivity` itself, not only into final postprocess/finalize, so execution-cost scenarios cannot be selected just because they pass full-sample or single OOS split.

## Code changes

- `trading_mvp/src/basis.py`
  - `run_funding_sensitivity(...)` and `run_funding_sensitivity_file(...)` now accept `walk_forward_cfg`.
  - Each sensitivity scenario can run `run_funding_walk_forward_backtest(...)` on repriced rows.
  - Per-scenario `research_acceptance` now includes `walk_forward_required_passed` and `walk_forward_accepted`.
  - Scenario rejection reasons now include `walk_forward_rejected` when rolling windows fail.
  - Scenario artifacts include compact walk-forward summary, not full windows.
  - Sensitivity summary includes `walk_forward_enabled`, `walk_forward_accepted_scenarios`, `best_walk_forward_avg_test_net_pnl_quote`, and `best_walk_forward_worst_test_net_pnl_quote`.
- `trading_mvp/src/cli.py`
  - Added strict preset key `sensitivity_walk_forward=True`.
  - Added `funding-sensitivity --sensitivity-walk-forward`.
  - Added `--walk-train-rows`, `--walk-test-rows`, `--walk-step-rows`, `--walk-min-windows`, `--walk-min-accepted-windows`, `--walk-min-accepted-ratio`, `--walk-min-train-span-hours`, `--walk-min-test-span-hours` to `funding-sensitivity`.
- `trading_mvp/run_mvp.ps1`
  - Added `-FundingSensitivityWalkForward` switch.
  - Passed walk-forward parameters through the `funding-sensitivity` action.
- `trading_mvp/tests/test_basis.py`
  - Added regression test where full-sample sensitivity passes but rolling walk-forward rejects a bad OOS window.
  - Extended parser and strict preset tests for sensitivity walk-forward.

## Current collector status

Dataset:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl
```

Manifest:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json
```

Status after smoke:

- `final`: `false`
- `completed_cycles`: `13`
- `rows`: `312`
- `line_count`: `312`
- `line_count_matches_manifest`: `true`
- `errors`: `78`
- last write: `2026-06-15T21:41:23+03:00`

Decision: do not run final `funding-finalize` yet. The 24h dataset is still partial.

## Verification

Compile:

```powershell
& 'C:\Program Files\Python313\python.exe' -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py
```

Result: exit code `0`.

Targeted tests:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_funding_sensitivity_sorts_more_viable_execution_scenarios_first trading_mvp.tests.test_basis.BasisTests.test_funding_sensitivity_oos_gate_rejects_bad_out_of_sample trading_mvp.tests.test_basis.BasisTests.test_funding_sensitivity_walk_forward_gate_rejects_bad_rolling_window trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands
```

Result:

```text
Ran 4 tests in 0.024s
OK
```

Full suite:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 144 tests in 0.384s
OK
```

## CLI smoke

Command used strict research and a single zero-cost scenario to keep smoke focused:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File 'C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1' -Action funding-sensitivity -InputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl' -OutputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_sensitivity_walk_strict_smoke_20260615.json' -FundingStrictResearch -FundingSensitivitySpotFeeBps '0' -FundingSensitivityPerpFeeBps '0' -FundingSensitivitySlippageBps '0' -FundingSensitivityTargetHoldIntervals '1' -FundingSensitivityMaxBreakEvenHours '24' -FundingWalkTrainRows 48 -FundingWalkTestRows 24 -FundingWalkStepRows 24 -TopN 10
```

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_sensitivity_walk_strict_smoke_20260615.json
```

Smoke summary:

- `input_rows`: `312`
- `markets`: `24`
- `scenarios`: `1`
- `accepted_scenarios`: `0`
- `oos_enabled`: `true`
- `oos_accepted_scenarios`: `0`
- `walk_forward_enabled`: `true`
- `walk_forward_accepted_scenarios`: `0`
- `best_net_pnl_quote`: `-0.27624791649693076`
- `best_oos_net_pnl_quote`: `-0.042467126271425785`
- `best_walk_forward_avg_test_net_pnl_quote`: `-0.023104361401731954`
- `best_walk_forward_worst_test_net_pnl_quote`: `-0.05588516157936953`
- scenario trades: `7`
- scenario win rate: `0.0`
- scenario reasons: `full_backtest_rejected`, `oos_rejected`, `walk_forward_rejected`

Interpretation: the new gate works. Current partial sample remains rejected and is not a live-trading candidate.

## Next step

Wait until the 24h spot-liquidity funding collect has `final=true`, then run strict `funding-finalize` with OOS, walk-forward, stress, and paper-plan gates. If it rejects, proceed to signal/universe redesign rather than live trading.
