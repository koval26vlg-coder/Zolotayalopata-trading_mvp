# Rolling Funding Backtest And 24h Collect

Date: 2026-06-15

## Goal

Move the active `trading_mvp` objective forward by removing lookahead from funding/basis backtests and starting a wider 24h public-data collect for MEXC/Gate. This remains research-only: no API keys, no live orders, no leverage.

## Implementation

- Added rolling persistence gates to `FundingBacktestConfig`:
  - `min_funding_observations`
  - `min_funding_positive_ratio`
  - `min_funding_persistence_score`
- `run_funding_backtest` now enriches every row with funding persistence metrics from only the current market history available up to that timestamp.
- Entry gates now require rolling observations, positive ratio and persistence score to pass configured thresholds.
- Exit logic can close positions when rolling persistence degrades.
- Added CLI and PowerShell wrapper support for the same backtest gates.
- Fixed public REST reliability by setting `requests.Session.trust_env = False` in spot and funding clients. This prevents Windows/system proxy settings from breaking public API collection with `Missing dependencies for SOCKS support`.

## Verification

Command:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Result:

```text
Ran 11 tests in 0.024s
OK
```

Command:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result before proxy regression tests:

```text
Ran 81 tests in 0.133s
OK
```

Command after proxy fix:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Result:

```text
Ran 83 tests in 0.195s
OK
```

## 6h Rolling Backtest Smoke

Command:

```powershell
.\trading_mvp\run_mvp.ps1 -Action funding-backtest -InputPath "exports\trading-mvp\funding\funding_collect_6h_reliable_20260605_195336.jsonl" -OutputPath "exports\trading-mvp\backtests\funding_backtest_6h_reliable_20260605_195336_rolling_persistence.json" -NotionalQuote 100 -FundingMinRate 0 -FundingMinTotalScore 0 -FundingMaxSpotSpreadBps 30 -FundingMaxPerpSpreadBps 30 -FundingMaxAbsBasisBps 500 -FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0
```

Metrics:

```json
{
  "rows": 23,
  "markets": 2,
  "total_trades": 2,
  "wins": 0,
  "losses": 2,
  "win_rate": 0.0,
  "funding_pnl_quote": 0.002753299162619644,
  "basis_pnl_quote": -0.12992329891051746,
  "fees_quote": 0.7,
  "slippage_quote": 0.08,
  "net_pnl_quote": -0.9071699997478977,
  "expectancy_quote": -0.45358499987394885,
  "profit_factor": 0.0
}
```

Verdict: the 6h sample remains negative after costs. Rolling persistence reduces exposure but does not create a viable result on this small dataset.

## 24h Collect Status

Failed attempts:

- PID `29588`: Windows PowerShell wrapper did not resolve Python.
- PID `9572`: started but produced `Missing dependencies for SOCKS support` due proxy env.

Active clean attempt:

```json
{
  "pid": 4356,
  "metadata": "docs/agent-log/2026-06-15-funding-collect-24h-rolling-20260615_162045.json",
  "output": "exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl",
  "manifest": "exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json",
  "stdout": "exports/trading-mvp/run/funding_collect_24h_rolling_20260615_162045.out.log",
  "stderr": "exports/trading-mvp/run/funding_collect_24h_rolling_20260615_162045.err.log",
  "cycles": 288,
  "poll_interval_sec": 300,
  "exchanges": "mexc,gateio",
  "max_pairs_per_exchange": 15,
  "max_symbols": 300
}
```

First manifest check:

```json
{
  "final": false,
  "completed_cycles": 1,
  "rows": 24,
  "errors": 6,
  "eligible": 15,
  "stderr_bytes": 0
}
```

Selected pairs:

```text
mexc: HYPEUSDT, WBTUSDT, XMRUSDT, CCUSDT, OKBUSDT, RAINUSDT, MUSDT, MNTUSDT, CROUSDT, PIUSDT, BGBUSDT, HUSDT, KCSUSDT, VVVUSDT, KASUSDT
gateio: HYPE_USDT, LEO_USDT, CC_USDT, OKB_USDT, M_USDT, MNT_USDT, CRO_USDT, PI_USDT, H_USDT, VVV_USDT, GT_USDT, KAS_USDT, FLR_USDT, BDX_USDT, LAB_USDT
```

The active collect must not be postprocessed until `manifest.final=true`.

## Next Step

After the 24h process finishes:

1. Verify PID status, stderr, line count and manifest `final=true`.
2. Run `funding-rank` with persistence gates, for example `-FundingMinObservations 6 -FundingMinPositiveRatio 0.75 -FundingMinPersistenceScore 0`.
3. Run `funding-backtest` with the same rolling gates.
4. Compare net PnL, fees, slippage, basis PnL, funding PnL, winrate, expectancy and sample size.
5. If still negative, do not move to live; add volume/regime/stress filters or reject the current carry configuration.
