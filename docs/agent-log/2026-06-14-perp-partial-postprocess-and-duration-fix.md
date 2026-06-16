# 2026-06-14 Perp Partial Postprocess And Duration Fix

## Request
Continue the active Anufriev/trading_mvp goal: move from failed spot maker signals toward research-only perp long/short replay with real perp public data.

## Current Evidence
- The old perp collection `exports/trading-mvp/normalized/perp_normalized_6h_20260609_175941.jsonl` is not a final 6h dataset.
- Its manifest is `final=false`, `completed_cycles=218`, `rows=44009`, `errors=193`, `duration_sec=15794.65`.
- No matching running process was found, so it is treated as an interrupted partial dataset.

## Partial Perp QA
- Report artifact: `exports/trading-mvp/backtests/perp_report_partial_20260609_175941_20260614.json`.
- Rows: `44205`.
- Markets: `10`.
- Cycles seen: `219`.
- Events: `bbo=1991`, `depth=1991`, `trade=40223`.
- Mark/index/funding/open-interest/volume coverage: `100%`.
- Warnings: none.

## Exploratory Partial Perp Replay
- Command: `perp-postprocess -AllowPartial`.
- Report artifact: `exports/trading-mvp/backtests/perp_report_partial_postprocess_20260609_175941_20260614.json`.
- Grid artifact: `exports/trading-mvp/backtests/perp_grid_search_partial_20260609_175941_20260614.json`.
- Strict eligible configs: `0`.

### Best-By-Signal On Partial Dataset
| Signal | Trades | Win rate | Net PnL quote | Funding PnL quote | Profit factor | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `liquidity_sweep_reversal` | 1 | 0.00% | -0.040034 | 0.000002 | 0.0000 | ineligible |
| `flow_continue` | 31 | 16.13% | -2.660988 | -0.001477 | 0.0236 | ineligible |
| `fade_exhaustion` | 41 | 19.51% | -5.182580 | -0.000453 | 0.0367 | ineligible |

Decision: exploratory partial data does not support a live edge. It is not final evidence because the manifest is `final=false`.

## Duration Bug
While starting a clean 6h duration-bound collect, the first run `20260614_181134` stopped after `3` cycles despite `duration_sec=21600`. Root cause: `_should_continue_collect` still checked `cycle >= cfg.cycles` before wall-clock duration.

Fix:
- File: `trading_mvp/src/perp_collector.py`.
- For `duration_sec > 0`, collection now stops by wall-clock duration, not by `cycles`.
- Manifest now writes `stop_condition = "duration_sec"` and `cycles = null` for duration-bound runs.
- Tests added/updated in `trading_mvp/tests/test_perp_collector.py`.

Verification:
- `C:\Windows\py.exe -3 -m unittest discover -s trading_mvp\tests` -> `Ran 68 tests`, `OK`.

## New Clean 6h Collect
- Metadata: `docs/agent-log/2026-06-14-perp-collect-6h-duration-20260614_181422.json`.
- Output: `exports/trading-mvp/normalized/perp_normalized_6h_duration_20260614_181422.jsonl`.
- Manifest: `exports/trading-mvp/normalized/perp_normalized_6h_duration_20260614_181422.manifest.json`.
- PID: parent PowerShell `5032`, child Python `35580`.
- Initial verified manifest: `final=false`, `stop_condition=duration_sec`, `cycles=null`, `completed_cycles=1`, `rows=520`, `errors=0`.
- Heartbeat automation updated: `trading-mvp-perp-duration-6h-postprocess`.

## Next
After manifest `final=true`, run guarded `perp-postprocess` without `AllowPartial`:
- Report: `exports/trading-mvp/backtests/perp_report_6h_duration_20260614_181422.json`.
- Grid: `exports/trading-mvp/backtests/perp_grid_search_6h_duration_20260614_181422.json`.

Keep results research-only. No live orders, no API keys, no Binance testnet, no investment advice.
