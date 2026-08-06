# trading_mvp Current Goal

## Objective

Find, prove, or honestly reject a non-Binance trading edge with positive net expectancy after base/VIP0 fees, conservative execution, OOS, walk-forward, stress, economics, and paper-forward gates. Win rate is diagnostic, not the optimization target.

## Current Verdict

- No strategy is accepted.
- The prior MEXC/Gate spot cross-venue branch remains rejected: its full scan did not clear the fixed base-cost hurdle.
- The completed PIT source is not spot data. It contains MEXC/Gate `linear_perp` ticker BBO and must never be described as a spot scan.
- The 24.65h PIT dataset is rejected for edge validation because historical contract identity, executable depth, exact quote timestamps, and funding cannot be reconstructed.
- The active research branch is separately labelled `pit_linear_perp_cross_venue_forward_oos`.
- Live orders, API keys, leverage, margin, replay, backtest, grid tuning, and paper-forward remain blocked.

## Completed Evidence

### Immutable PIT full scan

- Source run: `pit_universe_snapshot_collect_20260710_154144`.
- Full source: 278 cycles and 464,192 rows.
- Predeclared two-venue clean slice: 271 retained cycles and 458,165 rows; 7 whole Gate timeout cycles were excluded without symbol-level repair or imputation.
- Full streaming screen: 206 matched bases and 2,384 raw cost-positive price-cross observations across 26 bases.
- Those observations are discovery-only. Eight persistent/extreme symbols exposed contract identity collisions, and the dataset has zero validated trade candidates.

### Forward public evidence probe

- Corrected probe artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\analysis\pit_linear_perp_forward_public_probe_20260711_204001.json`.
- Probe SHA-256: `f46d6442db6b48aa0363c99085d42be751e4d1e4e5c72937943b5920919efb73`.
- All 26 discovery bases were retained; no edge/PnL-based universe pruning was used.
- 18/26 bases passed the provisional cross-venue index-parity identity rule.
- 16/26 bases had complete contract, depth-at-$100, timestamp, and funding evidence in that observation.
- `B3` produced one stress-cost-positive observation: gross 89.62 bps, fixed conservative net +20.62 bps, quote timestamp skew 0.95 s, and index divergence 16.29 bps.
- A single positive observation is not an edge, trade sample, fill-probability estimate, or expectancy result. It only keeps the branch eligible for forward data acquisition.

## Sealed Forward-OOS Contract

Approval packet:

`E:\ZolotyayLopata-data\exports\trading-mvp\analysis\pit_linear_perp_forward_oos_planonly_20260711_204057.json`

SHA-256:

`290e97f5f98156df97fd75d45cea160050b8f065ac3f89fd97f692263e2ed6f4`

Collection rules:

- Collect all 26 discovery bases every attempt cycle; evaluate cycle validity only against the 18 pre-OOS identity bases.
- A valid cycle requires at least 14 fully valid pairs with both-venue contract/index parity, bid/ask depth for $100 on both sides, exact depth timestamps/skew, and funding fields.
- Target 800 valid cycles and at least 72 active collection hours.
- Continue after failed attempts up to 96 active hours, subject to a maximum 20% failed-cycle ratio.
- Failed attempts are immutable evidence segments and never increment `valid_cycle_count`.
- Never overwrite a failed segment. Interruption resumes with the same `run_id`, plan hash, universe hashes, and next contiguous segment number.
- Reaching the 96h limit without the quota finalizes the run as `COMPLETED_INSUFFICIENT_EVIDENCE`; it is not silently extended or repaired.

## Next Gate

The packet is ready and the long collect has not started. The next action requires explicit user approval because it is a 72-96h visible run.

After a quality-complete final manifest:

1. Run data-quality over immutable attempt segments.
2. Freeze event labels and evaluation protocol before any replay.
3. Require at least 100 independent OOS events, chronological holdout, walk-forward pass ratio >= 60%, base-fee/slippage/latency/gap/funding stress, and bounded venue/base concentration.
4. Optimize net expectancy after costs, not win rate.
5. Only a passing research result may enter paper-forward. Live remains out of scope until separate human approval after paper-forward acceptance.

## Commands

Status:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1 -Json
```

Non-starting preview:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_pit_cross_venue_forward_oos_visible.ps1 -PlanPath "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\pit_linear_perp_forward_oos_planonly_20260711_204057.json" -PlanOnly -Json
```

Command after explicit approval:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_pit_cross_venue_forward_oos_visible.ps1 -PlanPath "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\pit_linear_perp_forward_oos_planonly_20260711_204057.json" -ConfirmedForwardOosCollect
```

Tests:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\run_trading_tests.ps1 -Shard all -TimeoutSec 1800
```
