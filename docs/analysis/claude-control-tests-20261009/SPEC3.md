# SPEC3 — three control tests (frozen 2026-10-09)

Goal: decide whether ANY timing/carry result from SPEC (weekly BTC/ETH) and SPEC2 (channel strategies) survives
the three checks that could change the conclusion. Test strategies; do not collect new datasets except FRED DTB3 (T3).
Strategy rules are exactly those in data/SPEC.md and data/SPEC2.md (prior code in prior_code/ may be read and reused;
it was independently verified to 0.01). Do not retune any strategy parameter. Costs as in the original specs.
Data: data/ (BTCUSDT_1d.csv, ETHUSDT_1d.csv, SOLUSDT_1d.csv, BTC_blockchaininfo_daily.csv, and per-strategy folders
data/C1, C2, C5, C9, C11, C13, C16). Last usable bar closes 2026-10-06 23:59 UTC.

## T1 Random-timing (permutation) test — does timing beat same-exposure random timing?
Strategies: S2 (BTC 40W SMA), S6 (BTC/ETH 50/50 40W), C9 (4h 55/20 breakout, BTC/ETH/SOL sleeves),
C2 (funding overheat filter), C5 (Fear&Greed), C13 (gold MACD+EMA220).
Method (frozen):
- Reproduce the strategy's position series (in/out per bar) and its net return with original costs.
- Null: keep the multiset of in-position spell lengths and out-of-position gap lengths per asset sleeve; build 5000
  random schedules by randomly permuting the ORDER of spells and gaps independently (keep starting state = original
  starting state, keep total length). Apply the same costs per entry/exit. Same sleeve weights.
- Statistic: net log return of the period. p = (1 + #{null >= actual}) / (1 + 5000), one-sided.
- Report separately for IS and OOS as defined in the original spec of that strategy (SPEC: IS ≤2021-12-31, OOS 2022+;
  SPEC2: IS ≤2022-12-31, OOS 2023+). Also report FULL.
- Also report the null's median return and the actual exposure-matched B&H (return of holding the asset only for the
  same fraction of time, i.e. exposure × B&H log return) for context.
- Multiple testing: Holm–Bonferroni at alpha 0.05 across a family of 25 hypotheses (state this; use the OOS p-values
  of these 6 strategies as part of that family, treating the other 19 as untested-for-timing with p=1). Report which
  (if any) survive Holm. Also report raw p < 0.05 for information.

## T2 OOS-start sensitivity — are verdicts artefacts of the 2023+ bull window?
Strategies: S2, S6, S1 (DCA, only vs B&H), C2, C5, C9; benchmark B&H of the same asset(s) as in the original specs.
Method (frozen): rolling 3-year (156-week, or 1095-day) windows starting on the first day of each calendar quarter from
2018-07-01 to 2023-07-01 (21 starts; fewer if data/warm-up do not allow — state). Each window starts with $100 and
indicators warmed up on prior data. For each window report: strategy net %, max DD %, return/|maxDD|; same for B&H.
Summaries per strategy: share of windows where strategy beats B&H on (a) net return, (b) max DD, (c) return/|maxDD|,
(d) CAGR/|maxDD|; worst window net %; and the SPEC2 verdict rule applied per window (FAIL / INCONCLUSIVE /
PASS_CANDIDATE, trade-count rule only for C9). Say plainly whether conclusions flip with the start date.

## T3 Carry/yield vs risk-free and real $100 frictions
Strategies: C1 (funding carry), C11 (cash-secured put, DVOL proxy), C16 (Aave v3 USDC).
- Risk-free: FRED DTB3 (3-month T-bill, daily, annualised %) via
  https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3 (one download; if unavailable, use 1 alternative public
  source or a stated fixed path of annual averages: 2019 2.1, 2020 0.4, 2021 0.05, 2022 2.0, 2023 5.0, 2024 5.0,
  2025 4.2, 2026 3.8 — label as fallback).
- For each strategy and period (as in SPEC2: IS / OOS / FULL; C16 FULL only): excess CAGR = strategy CAGR − T-bill CAGR
  over the same dates; Sharpe-like ratio of daily excess returns (annualised, state method); verdict re-applied with
  the benchmark replaced by T-bill (carry/yield rule: PASS needs annualised EXCESS net > 0 with max DD < 10%,
  positive at 2x costs; FAIL if excess ≤ 0).
- $100 retail frictions scenario (separate rows): add RUB→USDT→RUB round-trip cost 3.5% (also report 2% and 5%),
  plus one USDT withdrawal/deposit network fee of $1 each way where the strategy needs moving funds (C16: plus $5 gas
  per round trip as in SPEC2; C1: no on-chain moves; C11: Deribit transfer $1 each way). Holding period = the whole
  OOS (or FULL for C16). Report final $ for $100 and annualised net after frictions, vs T-bill.
- Also report feasibility at $100 (min contract/notional) as already established — do not re-derive unless trivial.

## Output
Per test: a table of results, the frozen method actually used (any deviation stated), and a one-paragraph conclusion.
Respond in Russian in text fields. Save code and outputs under ctrl/T1, ctrl/T2, ctrl/T3.
