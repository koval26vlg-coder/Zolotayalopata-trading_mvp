# 2026-06-15 funding spot top liquidity gate

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and strengthen execution-quality filters before accepting any carry edge.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Final: `false`
- Completed cycles during latest check: `37 / 288`
- Rows: `864`
- Errors: `218`
- Line count matches manifest: `true`
- Last write age during latest check: about `104s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added spot top-of-book liquidity gating for funding/basis carry:

- `spot_bid_qty` and `spot_ask_qty` are persisted in opportunity rows;
- `spot_bid_notional_quote`, `spot_ask_notional_quote`, and `spot_top_min_notional_quote` are calculated from spot best bid/ask;
- `BasisScanConfig.min_spot_top_notional_quote` rejects scan/collect rows with `spot_top_liquidity_low`;
- `FundingBacktestConfig.min_spot_top_notional_quote` blocks entries when either current or rolling spot top liquidity is too low;
- backtest exits can now return `spot_top_liquidity_low` or `spot_top_liquidity_regime_low`;
- rolling regime metrics now include `regime_spot_top_min_notional_avg_quote` and `regime_spot_top_min_notional_min_quote`.

CLI/PowerShell exposure:

- Python CLI: `--min-spot-top-notional-quote` for `funding-scan`, `funding-collect`, `funding-backtest`, `funding-oos-backtest`, `funding-postprocess`, and `funding-finalize`;
- PowerShell wrapper: `-FundingMinSpotTopNotionalQuote`;
- strict research preset now sets `min_spot_top_notional_quote=500.0`.

Rationale:

- Existing `min_perp_volume_24h_quote` covers perp-side market quality, but carry execution also needs a tradable spot leg;
- top-of-book notional is not a full queue/fill model, but it prevents accepting carry setups where the spot best bid/ask is visibly too thin for the simulated notional.

## Verification

- Targeted funding suite with explicit venv Python:
  - `Ran 54 tests ... OK`
- Full trading_mvp test suite with explicit venv Python:
  - `Ran 126 tests ... OK`
- Live `funding-status -FundingStrictResearch` returned:
  - `status=running_or_waiting`;
  - `ready_for_postprocess=false`;
  - `line_count_matches_manifest=true`;
  - strict readiness rejected only because the dataset is still early: `status_not_final`, `data_quality:min_rows`, `data_quality:min_completed_cycles`, `data_quality:min_unique_cycles`.
