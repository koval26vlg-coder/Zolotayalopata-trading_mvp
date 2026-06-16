# 2026-06-15 funding market concentration gate

Goal context: improve research acceptance so high win rate is not accepted when it is concentrated in one market.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `24 / 288`
- Rows: `552`
- Manifest rows: `552`
- Line count matches manifest: `true`
- Errors: `140`
- Last write age: about `15s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added market-diversification acceptance gates:

- `FundingAcceptanceConfig.min_markets`, default `1`;
- `FundingAcceptanceConfig.max_market_trade_share`, default `1.0`;
- backtest metrics now include:
  - `market_trade_counts`;
  - `traded_markets`;
  - `max_market_trade_share`.

`evaluate_funding_backtest_metrics` now rejects research results when:

- traded market count is below `min_markets`;
- the largest market's trade share exceeds `max_market_trade_share`.

The new parameters are exposed through:

- Python CLI: `funding-oos-backtest`, `funding-postprocess`, `funding-finalize`;
- PowerShell wrapper: `-FundingAcceptMinMarkets`, `-FundingAcceptMaxMarketTradeShare`.

Defaults preserve previous behavior.

## Verification

- Red check before implementation:
  - `FundingAcceptanceConfig.__init__()` rejected `min_markets`;
  - CLI rejected `--accept-min-markets` and `--accept-max-market-trade-share`.
- Targeted tests after implementation:
  - `Ran 2 tests ... OK`
- Funding basis suite:
  - `Ran 43 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 115 tests ... OK`

## Intended use after collector finalizes

For the 24h finalize step, use non-default values to reject single-market overfit. Starting candidates:

- `FundingAcceptMinMarkets=2` or `3`;
- `FundingAcceptMaxMarketTradeShare=0.60` to `0.70`.
