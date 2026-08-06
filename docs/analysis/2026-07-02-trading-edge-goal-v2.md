# trading_mvp: edge goal v2

Дата: 2026-07-02
Статус: research-only, no live orders, no API keys, no leverage/margin

## Цель v2

Найти, доказать или честно отбросить торговый edge для non-Binance markets, оптимизируя не win rate, а net expectancy after all costs:

```text
net_expectancy = average(gross_pnl - fees - spread_cost - slippage - adverse_selection - estimated_fill_cost)
```

Стратегия считается кандидатом на продолжение только если она проходит data-quality, cost, OOS, walk-forward, stress, economics и paper-forward gates. Высокий win rate сам по себе не является edge.

## Приоритет веток

1. Funding/basis carry и другие более медленные структурные edge.
2. Maker/post-only thin-market inefficiencies только при доказанной fill probability и положительной expectancy после издержек.
3. Listing/event effects только с OOS и event-window controls.
4. Public-API HFT/scalping низкоприоритетен: комиссии, latency и adverse selection обычно убивают 3-6 bps targets до сигнала.

## Kill Rules

- `taker_round_trip_cost_bps >= expected_target_bps`: kill by construction.
- `net_expectancy <= 0` после fees/slippage/fill assumptions: kill.
- OOS или walk-forward не подтверждают in-sample edge: kill или research-only downgrade.
- sample size ниже минимального порога для заявленного edge: inconclusive, не continue.
- dataset не проходит duration/coverage/gap/schema gates: не replay/grid как доказательство.
- positive win rate при отрицательном tail-risk/expectancy: kill.
- strategy требует API keys/live orders/leverage до paper-forward: blocked.

## Gate Matrix

| Gate | Что проверяет | Минимальный результат |
| --- | --- | --- |
| Data quality | duration, coverage, gaps, schema, per-market density, reconnect errors | accepted=true до replay/grid |
| Cost gate | maker/taker fees, spread, slippage, fill/adverse-selection cost | target > round-trip cost + safety margin |
| Execution gate | post-only fill probability, queue model, cancellation/TTL, partial fills | conservative model still profitable |
| OOS | train/test split by time and markets | OOS net expectancy > 0 |
| Walk-forward | rolling train/test windows | no single-window dependency |
| Stress | worse fees, wider spreads, lower fills, latency, outage windows | no fragile profit-only-on-optimistic-assumptions |
| Economics | capital, venue risk, operational cost, turnover, capacity | realistic ROI after costs |
| Paper-forward | live public data, paper orders, no API keys/order placement | stable forward metrics before live discussion |
| Risk/security | venue exposure, kill-switch, no withdraw rights, secrets handling | no existential venue/API/custody risk |

## Current Dataset Decision

Current run:

- `run_id`: `ws_collect_72h_sweep_visible_20260702_012710`
- Manifest: `C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\raw\ws_collect_20260702_054555.json`
- Requested: `259200 sec` / `72h`
- Actual: `26274.98 sec` / `7.3h`
- Events: `7,716,396`
- Errors: `9`
- Stop reason: reconnect failures before requested duration
- Gate: `STOPPED_INCOMPLETE`

Decision: this dataset is not accepted as a 72h proof dataset. It may be used only for tooling QA or schema/data-density diagnostics unless explicitly accepted as an incomplete research sample. It must not be used to claim edge, OOS robustness or paper-forward readiness.

## Next Engineering Step

Do not run replay/grid/postprocess on the incomplete dataset as proof. The next valid step is one of:

1. Fix collector resilience and visible monitor behavior, then run a clean visible 72h collect.
2. Resume/segment collection with explicit manifest stitching and gap accounting, then require data-quality gate before replay.
3. If refusing more WS collection now, pivot to slower structural branch: funding/basis carry multi-week collection with conservative economics and no live orders.

Default recommendation: fix collector resilience first, because current WS branch failed operationally before the proof pipeline.

## Non-Goals

- No new channel/video/P2P/off-ramp/custody/legal analysis.
- No marketing-style "high winrate" optimization.
- No live trading, API keys, leverage, margin, or investment advice.
