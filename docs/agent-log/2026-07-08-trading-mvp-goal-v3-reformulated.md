# trading_mvp goal v3 reformulated

Agent: Codex
Time: 2026-07-08 18:15 +03:00

User request:
- Возобновить или заново сформулировать цель проекта.

Current gate:
- status: READY_FOR_POSTPROCESS
- next_goal_decision: CROSS_VENUE_DISLOCATION_SMOKE_DONE_NEEDS_VISIBLE_FULL_SCAN
- current branch: cross-venue MEXC/Gate spot dislocation

New active Codex goal:
- trading_mvp: найти, доказать или честно отбросить рабочий non-Binance trading edge с положительным net expectancy после базовых издержек через существующие данные, full-scan, OOS/walk-forward/stress/economics gates и paper-forward readiness; текущая ветка — cross-venue MEXC/Gate spot dislocation, следующий шаг — видимый full scan clean slice без collect/grid/live/API keys.

Plan document:
- docs/plans/2026-07-08-trading-mvp-edge-goal-v3.md

Next step:
- Run visible full cross-venue-dislocation scan on the existing clean normalized MEXC/Gate WS slice with progress output every 1M rows.

Constraints:
- no live orders
- no API keys
- no leverage/margin
- no grid before full scan result
- no channel/P2P/off-ramp/custody/legal work under this goal
