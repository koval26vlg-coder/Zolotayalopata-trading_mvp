# trading_mvp Current Goal

## Objective

Find, prove, or honestly reject a non-Binance trading edge with positive net expectancy after base/VIP0 costs, conservative execution, OOS, walk-forward, stress, economics, and paper-forward gates. Win rate is diagnostic and is never optimized independently from net expectancy.

## Current Verdict

- No strategy is accepted.
- The MEXC/Gate spot cross-venue dislocation branch is closed as rejected under the fixed base-cost model.
- The requested visible full scan was already completed on the clean two-exchange spot slice. Repeating the same 51-million-row scan cannot create new evidence.
- The fixed cross-venue lead/lag full scan is also closed: 51,278,447 rows, 12 matched bases, and zero fixed signals.
- The distinct 4h cross-sectional capitulation branch is closed: 307,593 rows, 40.67 analysis days, and zero fixed signals.
- The interrupted `linear_perp` forward run remains a separate diagnostic-only artifact. It is not OOS evidence and is no longer the active route.
- The current branch is a future point-in-time `spot_pit_idiosyncratic_crash_reclaim_1m` evidence collect. Its signal and costs were sealed before future data; no collector is running yet.
- The user cancelled `Рой`; manual Codex control remains active and the swarm must not restart without a new explicit request.
- Live orders, API keys, leverage, margin, grid search, replay tuning, and paper-forward remain blocked.

## Authoritative Spot Evidence

Full-scan report:

`E:\ZolotyayLopata-data\exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json`

Full-scan manifest:

`E:\ZolotyayLopata-data\exports\trading-mvp\run\cross_venue_dislocation_full_20260708_181741.manifest.json`

Fail-closed closure audit:

`E:\ZolotyayLopata-data\exports\trading-mvp\analysis\cross_venue_spot_full_scan_audit_20260712_200342.json`

Audit SHA-256:

`51c2a3739340bda4a81362e6f44d50455dc944f69a0ef4d53937ae98130ccb68`

## Verified Result

- `51,278,447` rows and `36,039,132` BBO rows scanned with zero parse errors.
- `12` matched MEXC/Gate spot bases.
- `2,266` fresh gross-positive observations, but `0` eligible observations after liquidity and cost gates.
- Fixed total cost: `69 bps` = `39 bps` fees + `10 bps` slippage + `20 bps` inventory/rebalance buffer.
- Best fresh gross observation overall: `66.34 bps`, but its executable top-of-book capacity was below the `$25` floor.
- Best observation that cleared the `$25` top-of-book floor: gross `46.72 bps`, fixed-cost net `-22.28 bps`.
- Even with the entire `20 bps` inventory/rebalance buffer removed, the best liquidity-qualified result remains `-2.28 bps` after fees and slippage.
- The migrated E: source and the original C: source have equal size and matching first/middle/last sample fingerprints. The audit labels this as a sampled copy check, not a full-file hash.

## Proof Gates

- Economics: failed.
- OOS: not reached because the pre-OOS economics screen failed.
- Walk-forward: not reached for the same reason.
- Stress: failed even under the optimistic no-inventory-buffer sensitivity.
- Paper-forward: blocked.

OOS or walk-forward cannot rescue a signal whose best liquidity-qualified gross edge is below base fees plus slippage. This branch must not be grid-tuned or rerun unless the source dataset or actual non-secret fee/execution assumptions materially change.

## Current Forward Gate

Sealed forward plan:

`E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_planonly_20260712_2145.json`

Accepted public preflight:

`E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_public_preflight_20260712_214801.json`

Sealed approval packet:

`E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_approval_packet_20260712_223112.json`

The approval packet passed all readiness checks. Targeted readiness tests passed `22/22`; the project fast shard passed `165/165`.

Fixed contract:

- Public MEXC/Gate spot snapshots only; Binance is reference-only for spot exclusion.
- Maximum duration `14d`, interval `60s`, immutable `6h` segments on `E:`.
- Base/VIP0 normal round-trip cost `120 bps`; stress cost `245 bps`.
- Same-venue price lookback, entry, and exit. Cross-venue price splicing is prohibited.
- A failed 2h data-quality gate stops incomplete and remains resumable with the same `run_id`.
- At 48h, fewer than 10 fixed signals across fewer than 5 bases stops cleanly as futile; the run does not wait 14 days.
- If the 48h gate passes, the run may continue to 14 days for OOS, walk-forward, stress, economics, and independent artifact audit.
- Replay, grid, paper-forward, live orders, API keys, leverage, and margin remain blocked.

The next action requires explicit user confirmation. It must launch only through the visible wrapper:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\start_spot_pit_event_forward_visible.ps1" -ApprovalPacketPath "E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_approval_packet_20260712_223112.json" -ConfirmedSpotPitEventForwardCollect
```

If interrupted, resume in a visible terminal with the same `run_id` and `-ResumeIncomplete`. Do not start a new run over an incomplete one.

Status command:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\check_active_run_gate.ps1 -Json
```

Next-step preview:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_next_goal_step.ps1 -Json
```
