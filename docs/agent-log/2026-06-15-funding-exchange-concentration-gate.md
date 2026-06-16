# 2026-06-15 funding exchange concentration gate

Goal context: continue the research-only `trading_mvp` funding/basis carry pipeline and avoid accepting a carry edge that only works on one exchange.

## Collector status

- Candidate dataset: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.manifest.json`
- Status during latest check: `running_or_waiting`
- Final: `false`
- Completed cycles: `2 / 288`
- Rows: `48`
- Errors: `12`
- Line count matches manifest: `true`
- Required spot-liquidity field presence:
  - `spot_bid_qty`: `1.0`
  - `spot_ask_qty`: `1.0`
  - `spot_top_min_notional_quote`: `1.0`

No postprocess/finalize was started because the manifest is not final.

## Change

Added exchange concentration metrics to funding backtests:

- `traded_exchanges`;
- `exchange_trade_counts`;
- `max_exchange_trade_share`.

Added acceptance gates:

- `FundingAcceptanceConfig.min_exchanges`;
- `FundingAcceptanceConfig.max_exchange_trade_share`.

Acceptance now rejects:

- `min_exchanges` when accepted trades are not diversified across enough exchanges;
- `max_exchange_trade_share` when one exchange dominates the trade sample.

CLI/PowerShell exposure:

- Python CLI: `--accept-min-exchanges`;
- Python CLI: `--accept-max-exchange-trade-share`;
- PowerShell: `-FundingAcceptMinExchanges`;
- PowerShell: `-FundingAcceptMaxExchangeTradeShare`.

Strict research preset now requires:

- `accept_min_exchanges=2`;
- `accept_max_exchange_trade_share=0.75`.

Rationale:

- The project is intended to work across selected non-Binance venues, not depend on a single exchange-specific artifact;
- this gate prevents a false robust result where total PnL is positive but all trades come from one venue.

## Verification

- Targeted funding suite with explicit venv Python:
  - `Ran 56 tests ... OK`
- Full trading_mvp test suite with explicit venv Python:
  - `Ran 128 tests ... OK`
- Live `funding-status -FundingStrictResearch` on the new spotliq dataset returned:
  - `status=running_or_waiting`;
  - `ready_for_postprocess=false`;
  - `line_count_matches_manifest=true`;
  - required field presence `1.0` for all required spot-liquidity fields.
