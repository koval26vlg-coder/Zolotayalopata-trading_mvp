# Funding gate report diagnostics

Date: 2026-06-15

Goal context: research-only trading_mvp validation for non-Binance spot universe. No live orders, no API keys, no leverage, no margin execution.

## Objective

Add diagnostics for zero eligibility in the funding/basis carry pipeline. The previous strict risk-adjusted gate correctly blocked weak carry, but the project needed a structured report explaining whether blockers are fees, basis/spread risk, liquidity, persistence, exchange concentration, or sample readiness.

## Code changes

- `trading_mvp/src/basis.py`
  - Added `funding_gate_report(...)`.
  - Added `funding_gate_report_file(...)`.
  - Added `default_funding_gate_report_path(...)`.
  - Report includes:
    - reason counts across latest ranked markets;
    - source reason counts;
    - persistence reason counts;
    - gate pass counts;
    - exchange-level counts;
    - distributions for expected net carry, risk-adjusted edge, basis/spread penalties, liquidity, regime basis std, and volume;
    - compact top ranked / top risk-adjusted / top expected-carry candidates.
- `trading_mvp/src/cli.py`
  - Added `funding-gate-report` command.
  - Strict research preset applies to this command.
  - Reuses the same `FundingRankConfig` gates as `funding-rank`.
- `trading_mvp/run_mvp.ps1`
  - Added `funding-gate-report` to `-Action` ValidateSet.
  - Added wrapper action passing all rank/risk-adjusted parameters.
- `trading_mvp/tests/test_basis.py`
  - Added report unit test for rejection reasons and distributions.
  - Extended CLI parser and strict preset tests.

## Current collector status

Dataset:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl
```

Status when checked:

- `final`: `false`
- `completed_cycles`: `15 / 288`
- `rows`: `360` at status check; report smoke used `384` as the next cycle completed during this turn
- `line_count_matches_manifest`: `true`
- `errors`: `90`
- last write age at status check: about `156 sec`

Decision: strict `funding-finalize` still must wait for `final=true` and strict data quality acceptance.

## Verification

Compile:

```powershell
& 'C:\Program Files\Python313\python.exe' -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py
```

Result: exit code `0`.

Targeted tests:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_funding_gate_report_summarizes_rejection_reasons_and_distributions trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands
```

Result:

```text
Ran 2 tests in 0.050s
OK
```

Full suite:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 147 tests in 0.462s
OK
```

## CLI smoke

Command:

```powershell
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File 'C:\Users\koval\Documents\ZolotyayLopata\trading_mvp\run_mvp.ps1' -Action funding-gate-report -InputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl' -OutputPath 'C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_gate_report_strict_partial_20260615.json' -FundingStrictResearch -TopN 10
```

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_gate_report_strict_partial_20260615.json
```

Summary:

- `input_rows`: `384`
- `markets_analyzed`: `24`
- `ranked_markets`: `24`
- `rank_eligible`: `0`
- `persistence_eligible`: `24`
- `exchange_counts`: `mexc=11`, `gateio=13`

Top blockers:

- `expected_edge_below_min`: `24 / 24`
- `risk_adjusted_edge_below_min`: `24 / 24`
- `break_even_horizon_too_long`: `24 / 24`
- `spot_top_liquidity_low`: `22 / 24`
- `spot_top_liquidity_regime_low`: `22 / 24`
- `basis_below_min`: `18 / 24`

Pass counts:

- `persistence_eligible`: `24`
- `source_eligible`: `14`
- `spot_top_liquidity_pass`: `2`
- `basis_floor_pass`: `6`
- `expected_edge_pass`: `0`
- `risk_adjusted_edge_pass`: `0`
- `break_even_pass`: `0`
- `rank_eligible`: `0`

Interpretation: on the current partial dataset, persistence is not the blocker. The blockers are economics and execution quality: fees/carry break-even, risk-adjusted edge, and spot top-of-book liquidity. Relaxing acceptance to force trades would be curve-fitting, not progress toward a viable strategy.

## Next step

When the 24h collect reaches `final=true`, run strict `funding-finalize`. If the full report still shows `expected_edge_pass=0` and `risk_adjusted_edge_pass=0`, the next aligned engineering move is universe/exchange expansion or a different carry variant, not live trading and not weaker gates.
