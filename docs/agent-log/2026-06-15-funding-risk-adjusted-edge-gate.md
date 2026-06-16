# Funding risk-adjusted edge gate

Date: 2026-06-15

Goal context: research-only trading_mvp validation for non-Binance spot universe. No live orders, no API keys, no leverage, no margin execution.

## Objective

Add a stricter funding/basis quality filter so positive funding is not treated as edge unless it covers basis volatility and spread-regime risk. This moves the project toward higher-quality paper trades instead of inflating trade count or winrate with weak carry.

## Code changes

- `trading_mvp/src/basis.py`
  - Added `min_risk_adjusted_edge_bps`, `basis_risk_multiplier`, and `spread_risk_multiplier` to `BasisScanConfig`, `FundingRankConfig`, and `FundingBacktestConfig`.
  - Added risk-adjusted edge calculation:
    - `basis_risk_penalty_bps = basis_risk_multiplier * regime_basis_std_bps`
    - `spread_risk_penalty_bps = spread_risk_multiplier * regime_spread_avg_bps`
    - `risk_adjusted_edge_bps = expected_net_carry_bps - basis_risk_penalty_bps - spread_risk_penalty_bps`
  - Added `risk_adjusted_edge_below_min` as rank/backtest/scan rejection reason.
  - Recomputed risk-adjusted edge after `reprice_funding_rows_for_costs(...)`, so funding sensitivity scenarios use their scenario-specific fee/slippage assumptions.
  - Applied the gate in `rank_funding_rows(...)`, `_entry_allowed(...)`, and `_exit_reason(...)`.
- `trading_mvp/src/cli.py`
  - Added CLI args: `--min-risk-adjusted-edge-bps`, `--basis-risk-multiplier`, `--spread-risk-multiplier`.
  - Wired args through `funding-rank`, `funding-backtest`, `funding-sensitivity`, `funding-oos-backtest`, `funding-walk-forward`, `funding-postprocess`, and `funding-finalize`.
  - Strict research preset now sets:
    - `min_risk_adjusted_edge_bps = 0.0`
    - `basis_risk_multiplier = 1.0`
    - `spread_risk_multiplier = 0.5`
- `trading_mvp/run_mvp.ps1`
  - Added wrapper params:
    - `FundingMinRiskAdjustedEdgeBps`
    - `FundingBasisRiskMultiplier`
    - `FundingSpreadRiskMultiplier`
  - Passed them through evaluation actions. Raw `funding-scan` / `funding-collect` remain broad to preserve source data.
- `trading_mvp/tests/test_basis.py`
  - Added opportunity-level risk-adjusted edge test.
  - Added rank/backtest test proving weak risk-adjusted carry is filtered and produces no trades.
  - Extended parser and strict preset assertions.

## Current collector status

Dataset:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.jsonl
```

Manifest:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_collect_24h_spotliq_20260615_202709.manifest.json
```

Status:

- `final`: `false`
- `completed_cycles`: `15 / 288`
- `rows`: `360`
- `line_count`: `360`
- `line_count_matches_manifest`: `true`
- `errors`: `90`
- last write: `2026-06-15T21:53:19+03:00`

Decision: do not run strict `funding-finalize` yet. Collector is alive but partial.

## Verification

Compile:

```powershell
& 'C:\Program Files\Python313\python.exe' -m py_compile trading_mvp/src/basis.py trading_mvp/src/cli.py
```

Result: exit code `0`.

Targeted tests:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest trading_mvp.tests.test_basis.BasisTests.test_opportunity_can_filter_negative_risk_adjusted_edge trading_mvp.tests.test_basis.BasisTests.test_rank_and_backtest_can_filter_risk_adjusted_edge_below_min trading_mvp.tests.test_basis.BasisTests.test_cli_parser_accepts_funding_commands
```

Result:

```text
Ran 3 tests in 0.019s
OK
```

Full suite:

```powershell
& 'C:\Program Files\Python313\python.exe' -m unittest discover -s trading_mvp/tests
```

Result:

```text
Ran 146 tests in 0.590s
OK
```

## CLI smoke

### Strict rank smoke

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\funding\funding_rank_risk_adjusted_strict_smoke_20260615.json
```

Summary:

- `input_rows`: `360`
- `markets_analyzed`: `24`
- `ranked_rows`: `10`
- `rank_eligible`: `0`
- top market: `XMR`
- top `risk_adjusted_edge_bps`: `-45.22945332009169`
- top rejection reasons: `expected_edge_below_min`, `risk_adjusted_edge_below_min`, `break_even_horizon_too_long`, `spot_top_liquidity_low`, `spot_top_liquidity_regime_low`

### Strict sensitivity smoke

Artifact:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\funding_sensitivity_risk_adjusted_strict_smoke_20260615.json
```

Summary:

- `input_rows`: `360`
- `scenarios`: `1`
- `accepted_scenarios`: `0`
- `rank_eligible`: `0`
- `total_trades`: `0`
- `walk_forward.windows`: `13`
- `walk_forward.accepted_windows`: `0`

Interpretation: the new gate is active and currently blocks weak funding carry before trade generation. This is expected on a partial dataset and is safer than manufacturing a high winrate from weak edge.

## Next step

Continue monitoring the 24h collect until `final=true`; then run strict `funding-finalize` with quality, rank, backtest, OOS, walk-forward, stress, and paper-plan gates. If strict risk-adjusted edge yields zero eligible markets on the full sample, the next engineering step should be to widen universe/exchanges or redesign the carry signal, not relax the gate for live trading.
