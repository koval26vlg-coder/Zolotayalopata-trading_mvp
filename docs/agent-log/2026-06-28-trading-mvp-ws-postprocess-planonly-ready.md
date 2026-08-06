# trading_mvp WS postprocess and replay PlanOnly ready

Date: 2026-06-28
Agent: Codex
Request: пользователь сказал "продолжи цель" after 6h WS collect was READY_FOR_POSTPROCESS.

## Inputs
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\raw\ws_collect_20260628_000346.json`
- Run id: `ws_collect_6h_sweep_visible_20260627_210337`

## Actions
- Ran guarded `tools\run_ws_postprocess_visible.ps1 -NoPause`.
- Ran `tools\run_ws_replay_validation_visible.ps1 -PlanOnly -NoPause` with the same manifest.
- Did not run live orders, API keys, leverage/margin, paper-forward, or actual replay/grid.

## Postprocess Artifacts
- Postprocess: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_postprocess_ws_collect_20260628_000346_postprocess_20260628_100805.json`
- Normalized: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_normalized_ws_collect_20260628_000346_postprocess_20260628_100805.jsonl`
- Quality: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_data_quality_ws_collect_20260628_000346_postprocess_20260628_100805.json`
- Console log: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\run\ws_postprocess_ws_collect_20260628_000346_postprocess_20260628_100805.console.log`

## Quality Metrics
- raw_rows: 2745067
- normalized_rows: 2744439
- event kinds: bbo=1940704, depth=753940, trade=49795
- exchanges: 2
- markets: 16
- span_hours: 5.999973273608419
- duration_ratio: 0.9999955456014032
- parse_error_rate: 0
- markets_with_required_kinds: 16
- max_market_event_share: 0.095112334433376
- max_gap_sec: 55.525633096694946
- manifest_error_count: 0
- replay_allowed: true

## PlanOnly Result
- PlanOnly OK: `would_run=false`, `postprocess_replay_allowed=true`.
- Planned validation run label: `ws_postprocess_ws_collect_20260628_000346_postprocess_20260628_100805_replay_validation_20260628_101225`.
- Planned outputs include event-quality, event-slice optimizer, event-validation, ws-grid-search, sweep gate, and validation summary.
- `ws_replay` is skipped by default; `ws_grid` is included.

## Next Required Confirmation
The next step is a visible `ConfirmedResearchRun` because it runs replay/grid research work. It should only be started after explicit confirmation from the user.
