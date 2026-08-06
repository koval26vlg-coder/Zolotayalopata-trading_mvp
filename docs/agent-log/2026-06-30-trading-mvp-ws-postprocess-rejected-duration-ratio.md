# trading_mvp WS postprocess rejected by duration ratio

- Time: 2026-06-30 12:14:13 +03:00
- Agent: Codex
- User request: Continue active trading_mvp goal after visible WS postprocess.
- Gate before decision: READY_FOR_POSTPROCESS after completed ws-postprocess.
- Manifest: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\raw\ws_collect_20260630_024437.json
- Normalized: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\normalized\ws_normalized_ws_collect_20260630_024437_retry_20260630_1123.jsonl
- Quality: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_data_quality_ws_collect_20260630_024437_retry_20260630_1123.json
- Postprocess: C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\backtests\ws_postprocess_ws_collect_20260630_024437_retry_20260630_1123.json

## Result

- eplay_allowed: false
- data_quality.accepted: false
- reason: min_duration_ratio
- rows: 9,289,727
- span_hours: 20.6711
- manifest_duration_sec: 212400
- duration_ratio: 0.35036
- exchanges: 2
- markets: 20
- required event kinds present: bbo/depth/trade across 20 markets
- parse_error_rate: 0.0
- max_gap_sec: 58.20
- manifest_error_count: 6

## Decision

Do not run replay/grid on this artifact as proof input. The strict gate rejected it because actual coverage is only about 35% of the requested 59h resumed collection window.

## Next

Use Рой checkpoint for independent decision: either resume/recollect visible WS data to satisfy strict duration coverage, or run only a clearly labelled partial diagnostic with no proof/edge claims.
