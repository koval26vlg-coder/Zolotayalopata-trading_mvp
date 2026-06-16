# Funding Persistence Score

Date: 2026-06-15

## Goal

Усилить `funding/basis carry` ветку перед длинным сбором данных: `funding-rank` больше не должен сортировать рынки только по последнему snapshot и `total_score`. Нужны метрики устойчивости funding по истории рынка.

## Changes

- Added `FundingRankConfig`.
- Added funding history enrichment in `rank_funding_rows`.
- Added metrics:
  - `funding_observations`
  - `funding_positive_observations`
  - `funding_negative_observations`
  - `funding_positive_ratio`
  - `funding_avg_rate`
  - `funding_min_rate`
  - `funding_max_rate`
  - `funding_rate_std`
  - `funding_avg_bps`
  - `funding_min_bps`
  - `funding_max_bps`
  - `funding_std_bps`
  - `funding_persistence_score`
  - `persistence_eligible`
  - `persistence_reasons`
  - `persistence_adjusted_total_score`
- Added CLI flags for `funding-rank`:
  - `--min-funding-observations`
  - `--min-funding-positive-ratio`
  - `--min-funding-persistence-score`
  - `--funding-persistence-weight`
- Added equivalent PowerShell parameters:
  - `-FundingMinObservations`
  - `-FundingMinPositiveRatio`
  - `-FundingMinPersistenceScore`
  - `-FundingPersistenceWeight`

## Verification

Command:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Result:

```text
Ran 9 tests in 0.020s
OK
```

Command:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result:

```text
Ran 79 tests in 0.105s
OK
```

## Smoke Artifact

Command:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-rank -InputPath "exports\trading-mvp\funding\funding_collect_6h_reliable_20260605_195336.jsonl" -OutputPath "exports\trading-mvp\funding\funding_rank_persistence_6h_reliable_20260605_195336.json" -TopN 20 -FundingMinObservations 2 -FundingMinPositiveRatio 0.6 -FundingMinPersistenceScore 0
```

Result summary:

```json
{
  "input_rows": 23,
  "markets_analyzed": 2,
  "ranked_rows": 2,
  "persistence_eligible": 2
}
```

Top markets:

```text
1. gateio HYPE_USDT/HYPE_USDT funding=0.5 bps, observations=12, positive_ratio=1.0, persistence_score=2.5, adjusted_score=11.1167
2. mexc HYPEUSDT/HYPE_USDT funding=0.5 bps, observations=11, positive_ratio=1.0, persistence_score=2.5, adjusted_score=8.5288
```

## Baseline Backtest

Command:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-backtest -InputPath "exports\trading-mvp\funding\funding_collect_6h_reliable_20260605_195336.jsonl" -OutputPath "exports\trading-mvp\backtests\funding_backtest_6h_reliable_20260605_195336_baseline.json" -NotionalQuote 100 -FundingMinRate 0 -FundingMinTotalScore 0 -FundingMaxSpotSpreadBps 30 -FundingMaxPerpSpreadBps 30 -FundingMaxAbsBasisBps 500
```

Result summary:

```json
{
  "rows": 23,
  "markets": 2,
  "total_trades": 2,
  "wins": 0,
  "win_rate": 0.0,
  "funding_pnl_quote": 0.01840876349144512,
  "basis_pnl_quote": -0.2515218530784,
  "fees_quote": 0.7,
  "slippage_quote": 0.08,
  "net_pnl_quote": -1.013113089586955,
  "expectancy_quote": -0.5065565447934774,
  "profit_factor": 0.0
}
```

## Verdict

`funding_persistence_score` is implemented and verified. The 6h baseline remains economically negative because fees and basis movement dominate small funding income. This is not a rejection of the carry direction yet; the dataset is too small and has only two markets. The next valid research step is a wider 24h-7d funding collect with rolling persistence gates and no live orders.

## Next Step

Implement rolling persistence inside `funding-backtest` to avoid lookahead, then run a wider 24h collection on MEXC/Gate with enough pairs to produce a meaningful sample.
