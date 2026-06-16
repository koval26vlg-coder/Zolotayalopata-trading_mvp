# 2026-06-15 Event Quality Report

## Request
Continue the `trading_mvp` goal after the rejected clean 6h perp grid. Add a stronger event-definition layer before adding another trading signal.

## Implementation
- Added `trading_mvp/src/event_labeler.py`.
- Added CLI action `event-quality-report`.
- Added PowerShell action `-Action event-quality-report`.
- Added unit coverage in `trading_mvp/tests/test_event_labeler.py`.
- Documented the workflow in `trading_mvp/README.md`.

The module is research-only. It labels observable sweep/reclaim events and does not open paper or live trades.

## Artifact
- Input: `exports/trading-mvp/normalized/perp_normalized_6h_duration_20260614_181422.jsonl`.
- Output: `exports/trading-mvp/backtests/event_quality_6h_duration_20260614_181422.json`.

Command:

```powershell
.\trading_mvp\run_mvp.ps1 -Action event-quality-report `
  -InputPath "exports\trading-mvp\normalized\perp_normalized_6h_duration_20260614_181422.jsonl" `
  -OutputPath "exports\trading-mvp\backtests\event_quality_6h_duration_20260614_181422.json" `
  -EventLookbackSec 120 `
  -EventHorizonSec 300 `
  -EventMinSweepNotionalQuote 1000 `
  -EventReclaimBps 0 `
  -EventTargetBps 6 `
  -EventStopBps 3 `
  -EventMaxPreSpreadBps 6 `
  -EventCooldownSec 10 `
  -EventMaxEvents 10000
```

## 6h Results
- Rows: `82414`.
- Markets: `10`.
- Total sweep candidates: `1018`.
- Reclaimed: `719`.
- Reclaim rate: `70.63%`.
- Target before stop: `264`.
- Stop before target: `399`.
- Target-before-stop rate among reclaimed events: `36.72%`.
- False-sweep rate: `74.07%`.
- Average sweep intensity: `12.3791` bps.
- Average time to reclaim: `82.2581` seconds.
- Average favorable excursion: `18.1522` bps.
- Average adverse excursion: `-20.0416` bps.

## Market Notes
- `mexc:HYPE_USDT` dominates the sample with `718` events, but target-before-stop among reclaimed events is only `33.85%`. This is too toxic for a naive reversal strategy.
- `gateio:HYPE_USDT` has `126` events and target-before-stop among reclaimed events of `43.18%`, still below the acceptance bar.
- `mexc:H_USDT` shows large favorable and adverse excursions, but the adverse side is larger and symbol risk is high.
- Tiny samples like `gateio:CC_USDT` are not usable for acceptance even when the local rate looks good.

## Verification
- Targeted tests: `C:\Windows\py.exe -3 -m unittest trading_mvp.tests.test_event_labeler`.
- Full suite: `C:\Windows\py.exe -3 -m unittest discover -s trading_mvp\tests`.

Both commands were run after the code changes and returned exit code `0`.

## Decision
Do not turn the current raw sweep/reclaim label directly into live or paper execution. The event family has enough observations to analyze, but the raw definition is not selective enough: reclaimed sweeps are common, yet `target_before_stop` is materially below a high-winrate acceptance threshold.

## Next
Build an event-slice optimizer before changing the replay strategy:
- slice by market, side, sweep intensity, time-to-reclaim, pre-spread, basis and notional;
- require minimum sample size per slice;
- look for slices with target-before-stop rate above `60%` and acceptable adverse excursion;
- only then add a `liquidity_sweep_reversal_v2` entry filter to replay.

Research-only. No live orders, no API keys, no Binance testnet, no investment advice.
