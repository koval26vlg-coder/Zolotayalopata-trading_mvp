# 2026-06-15 funding time-window robustness gate

Goal context: continue building the research-only `trading_mvp` funding/basis carry pipeline and reduce the chance of accepting a high win-rate result that is concentrated in one short time period.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status: `running_or_waiting`
- Ready for postprocess: `false`
- Final: `false`
- Completed cycles: `30 / 288`
- Rows: `696`
- Manifest rows: `696`
- Line count matches manifest: `true`
- Errors: `176`
- Last write age during check: about `308s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added hourly time-window robustness metrics to funding backtests:

- `window_sec`;
- `active_windows`;
- `profitable_windows`;
- `window_pnl_quote`;
- `window_trade_counts`;
- `max_window_pnl_quote`;
- `max_window_pnl_share`.

Added acceptance gates:

- `FundingAcceptanceConfig.min_profitable_windows`, default `0`;
- `FundingAcceptanceConfig.max_window_pnl_share`, default `1.0`.

These gates reject research results when:

- profitable windows are below the configured minimum;
- the largest profitable hourly window accounts for too much of positive window PnL.

The new parameters are exposed through:

- Python CLI: `funding-oos-backtest`, `funding-postprocess`, `funding-finalize`;
- PowerShell wrapper: `-FundingAcceptMinProfitableWindows`, `-FundingAcceptMaxWindowPnlShare`.

Defaults preserve previous behavior.

## Verification

- Red check before implementation:
  - `FundingAcceptanceConfig.__init__()` rejected `min_profitable_windows`;
  - funding metrics lacked `active_windows`;
  - CLI rejected `--accept-min-profitable-windows` and `--accept-max-window-pnl-share`.
- Targeted tests after implementation:
  - `Ran 3 tests ... OK`
- Funding basis suite:
  - `Ran 45 tests ... OK`
- Full trading_mvp test suite:
  - `Ran 117 tests ... OK`
- PowerShell parse/status smoke with new params:
  - `funding-status` returned `status=running_or_waiting`, `line_count_matches_manifest=true`, `final=false`.

## Intended use after collector finalizes

For the 24h finalize step, start with strict-but-not-impossible window gates:

- `FundingAcceptMinProfitableWindows=3`;
- `FundingAcceptMaxWindowPnlShare=0.60`.

These should be used alongside market concentration gates:

- `FundingAcceptMinMarkets=2` or `3`;
- `FundingAcceptMaxMarketTradeShare=0.60` to `0.70`.
