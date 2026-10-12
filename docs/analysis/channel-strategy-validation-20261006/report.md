# Historical Strategy Validation

Research only. No live permission and no claim of a profitable strategy.

A blocked model is not a rejected strategy. Readiness is not a backtest.

Plan: `8815ad9770e0cf0980a54c0295b4b6f734f2557bcdad058c7ef8259ad41842fb`
Result: `4fe92f28919e2a3b251dee37c9adcf2d24c7e521cfff31936381206d23278c65`

| # | Model | Data / checks | Result | Limitations / next step |
|---|---|---|---|---|
| 1 | Relative strength | bars_1h, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 2 | Trend pullback | bars_4h, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 3 | Causal structure continuation | bars_4h, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 4 | ATR-normalized trend line | bars_4h, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 5 | Orderbook continuation | books, tape, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 6 | Orderbook reclaim | books, bars_1m, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 7 | Spot-perpetual funding carry | paired_quotes, funding | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 8 | Cross-venue funding carry | paired_quotes, funding | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 9 | Prefunded spot dislocation | paired_quotes, inventory | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 10 | Positive spot-perpetual basis convergence | paired_quotes, funding | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 11 | Long ATM put | option_chain, underlying_quotes, contract_specs | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 12 | Cash-reserved short put | option_chain, underlying_quotes, contract_specs | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 13 | Bear put spread | option_chain, underlying_quotes, contract_specs | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 14 | Spot-only weekly fixed grid | bars_1d, books, pit_universe | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 15 | Gold MACD trend proxy | bars_4h, contract_specs, calendar | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 16 | DAX opening-range breakout | bars_5m, contract_specs, calendar | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 17 | US equity gap continuation | bars_5m, pit_equity_universe, calendar, corporate_actions | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 18 | US equity gap fade | bars_5m, pit_equity_universe, calendar, corporate_actions | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 19 | Aave v3 Ethereum USDC lending | lending_index, gas, token_quotes, withdrawal_liquidity | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |
| 20 | Ethereum causal wallet following | dex_swaps, token_universe, gas, execution_quotes | BLOCKED_DATA | No eligible inputs in this environment; not a negative strategy verdict. Provide verified free historical files and an input manifest; no forward collector. |

## Implementation Boundary

Models 1-4 have exploratory candle replay. Models 5-20 use instrument-specific adapters
and cash-reserved portfolio replay with mandatory observed marks. Missing daily valuation,
funding/contract provenance, or historical universe evidence cannot be filled with assumptions.

## Excluded

Listing Momentum: separate project. Premarket-depth: unchanged.
Old rejected runs: not reopened. AI: no reproducible specification. Prop: risk overlay only.

## Source Availability

A local missing archive does not prove public history is unavailable.
See source-availability.md. No schedule, permanent collector or paid data purchase was created.
