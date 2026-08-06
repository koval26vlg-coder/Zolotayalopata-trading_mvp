# Funding Economic Thresholds

Дата: 2026-06-17
Статус: расчет порогов безубыточности для funding/basis carry. Это не backtest и не торговая рекомендация.

## Formula

Формула из `trading_mvp/src/basis.py`:

```text
round_trip_cost_bps = 2 * spot_fee_bps + 2 * perp_fee_bps + 4 * slippage_bps
expected_net_carry_bps = funding_bps_per_interval * target_hold_intervals - round_trip_cost_bps
break_even_hours = round_trip_cost_bps / funding_bps_per_interval * funding_interval_hours
```

Risk-adjusted edge is stricter because `basis_risk_penalty_bps` and `spread_risk_penalty_bps` are subtracted after expected net carry.

## Current 24h Observed Funding Distribution

| Metric | Value |
|---|---:|
| rows | 7659 |
| markets | 30 |
| positive_rows | 5646 |
| positive_ratio | 0.737172 |
| min_bps | -41.83 |
| p50_bps | 0.5 |
| p90_bps | 1 |
| p95_bps | 2.121 |
| p99_bps | 10.1526 |
| max_bps | 28.72 |
| median_interval_hours | 4 |

Source: `exports/trading-mvp/funding/funding_collect_24h_spotliq_20260615_202709.jsonl`.

## Threshold Table

CSV artifact: `exports\trading-mvp\analysis\funding_economic_thresholds_20260617.csv`

| Scenario | Cost bps | Hold intervals | Required funding bps/interval | p95 clears | p99 clears | max clears |
|---|---:|---:|---:|---|---|---|
| current_taker_like | 39 | 1 | 39 | False | False | False |
| current_taker_like | 39 | 3 | 13 | False | False | True |
| current_taker_like | 39 | 6 | 6.5 | False | True | True |
| current_taker_like | 39 | 12 | 3.25 | False | True | True |
| reduced_fee | 17 | 1 | 17 | False | False | True |
| reduced_fee | 17 | 3 | 5.6667 | False | True | True |
| reduced_fee | 17 | 6 | 2.8333 | False | True | True |
| reduced_fee | 17 | 12 | 1.4167 | True | True | True |
| maker_vip_low_slip | 3 | 1 | 3 | False | True | True |
| maker_vip_low_slip | 3 | 3 | 1 | True | True | True |
| maker_vip_low_slip | 3 | 6 | 0.5 | True | True | True |
| maker_vip_low_slip | 3 | 12 | 0.25 | True | True | True |
| maker_zero_fee_low_slip | 1 | 1 | 1 | True | True | True |
| maker_zero_fee_low_slip | 1 | 3 | 0.3333 | True | True | True |
| maker_zero_fee_low_slip | 1 | 6 | 0.1667 | True | True | True |
| maker_zero_fee_low_slip | 1 | 12 | 0.0833 | True | True | True |
| zero_cost_theoretical | 0 | 1 | 0 | True | True | True |
| zero_cost_theoretical | 0 | 3 | 0 | True | True | True |
| zero_cost_theoretical | 0 | 6 | 0 | True | True | True |
| zero_cost_theoretical | 0 | 12 | 0 | True | True | True |

## Interpretation

- Current cost model has round-trip cost `39 bps`.
- At one funding interval it requires `39 bps` per interval just to reach zero net before basis/spread risk.
- Observed p95 funding was `2.121 bps`, p99 was `10.1526 bps`, max was `28.72 bps` in the 24h dataset.
- Therefore the current one-interval taker-like model is economically blocked by construction on this dataset.
- Longer holds and maker/VIP-like fees can reduce required funding, but that increases basis, venue and custody exposure; it must be validated by 7d/multi-week final-review, not assumed.

## Project Decision

- Funding/basis remains the cleanest research branch, but only as a longer-horizon carry strategy.
- Current `taker-like + one interval` model should stay failed.
- The next evidence step remains the visible 7d collect and guarded final-review.
- Live/paper trading is still blocked until research gates pass.
