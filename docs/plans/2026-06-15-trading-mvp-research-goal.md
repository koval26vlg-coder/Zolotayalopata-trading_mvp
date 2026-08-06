# Trading MVP Research Goal Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Построить research-only систему, которая проверяет стратегии на монетах вне Binance и допускает следующий этап только при положительном net PnL после fees/slippage, достаточной выборке, контролируемом drawdown и out-of-sample подтверждении.

**Architecture:** Проект идет двумя независимыми ветками: `funding/basis carry` как основной кандидат на устойчивый edge и `order-book/perp microstructure` как экспериментальная ветка, которая уже получила несколько rejected verdicts. Funding не смешивается с HFT-сигналом: сначала ранжирование рынков, затем rolling backtest, затем paper-forward без live orders.

**Tech Stack:** Python stdlib, `requests`, public REST/WebSocket data, JSON/JSONL artifacts, `unittest`, PowerShell wrapper `trading_mvp/run_mvp.ps1`.

## Progress Checkpoint 2026-06-17

**Gate status:** 24h visible funding collect completed, no live collector is running.

**Completed:**
- Task 1: funding persistence ranking and related CLI parameters are implemented.
- Task 2: 24h funding collection completed with `7659` rows, `288/288` cycles, `30` markets, and accepted relaxed data quality.
- 24h postprocess/rank/backtest/OOS/walk-forward artifacts were produced.

**Current verdict:** rejected for economics, not for collector mechanics.

**Reason:** `rank_eligible=0`, `total_trades=0`, `net_pnl_quote=0`; current opportunities do not clear expected net carry, risk-adjusted edge, break-even horizon, and strict acceptance gates after fees/slippage/spread/basis risk.

**Important correction:** future research collection must include negative funding observations too. The entry/rank/backtest stage should filter positive carry; the raw collector should not hide funding flips.

**Next valid batch:** do not tune breakout or order-book signals on the current thin intraday sample. Prepare and, only with explicit user approval, run a visible 7d funding/basis collect, then run postprocess/OOS/walk-forward/stress and cost-sensitivity.

**Blocked action:** live orders, API keys, leverage, margin execution, or trading claims remain blocked until research gates pass on longer out-of-sample data.

---

## Progress Checkpoint 2026-06-27

**Gate status:** 7d visible funding/basis collect completed and active-run gate is `READY_FOR_POSTPROCESS`.

**Dataset:**
- Run id: `funding_collect_7d_spotliq_visible_20260617_185732`
- Cycles: `2016/2016`
- Rows: `50583`
- Errors: `657`
- Span: about `225.5` hours
- Markets: `30`

**Strict final-review result:** blocked before postprocess because strict data-quality gate failed on `min_min_rows_per_cycle`.

**Data-quality details:**
- `avg_rows_per_cycle`: `28.92`
- `min_rows_per_cycle`: `9`
- strict threshold: `20`
- `error_rate`: `0.0128`
- `cycle_market_duplicates`: `0`
- required row fields present: `spot_bid_qty`, `spot_ask_qty`, `spot_top_min_notional_quote`

**Diagnostic relaxed rank:** a separate diagnostic rank with `min_rows_per_cycle=9` was started only to inspect economics, not to accept a strategy.

**Diagnostic result:** `rank_eligible=0`. Top ranked markets still fail on expected edge/risk-adjusted edge/break-even horizon and often spot-top liquidity. This means the current funding carry branch is still not accepted for paper-forward.

**Current verdict:** no accepted strategy. Funding carry remains useful as a research branch, but current public-data/cost assumptions do not produce a tradable edge.

**Swarm L1 review 2026-06-27:** `Рой` / `Antigravity CLI` completed L1 checkpoint review and submitted handoff in workflow `2026-06-27-095557-165108-trading-mvp-7d-funding-checkpoint-review`. Decision: `block`.

**Swarm conclusion:** funding carry must not move to paper-forward now. The strict `min_rows_per_cycle` failure is secondary; the primary blocker is economics because relaxed diagnostics still have `rank_eligible=0` and do not clear expected edge, risk-adjusted edge, break-even, and liquidity gates.

**Swarm L2 review 2026-06-27:** `Рой` / `Antigravity CLI` completed the L2 engineering review in the same workflow. Decision: `block`.

**Swarm L2 conclusion:** Funding carry remains blocked for paper-forward. Fixing collector coverage is not the first engineering step because the relaxed diagnostic still shows `rank_eligible=0`; the next branch must be either verified non-secret fee-tier economics that materially changes the cost model, or a different edge family.

**Next valid steps:**
- Do not spend the next cycle on collector coverage alone unless funding remains a candidate after real fee/maker assumptions are proven.
- Validate actual non-secret maker/taker fee-tier assumptions for MEXC/Gate and map them to the model; lower-cost assumptions are diagnostic only until evidence exists.
- If fee-tier evidence does not materially change expected net/risk-adjusted edge, deprioritize funding carry and return to a different edge family.
- Retry `Рой` at the next major branch decision or after fee/economics evidence changes.

**Blocked action:** paper-forward, live trading, API keys and leverage remain blocked.

---

## Swarm Usage Rule For This Goal

Use `Рой` as an auxiliary review instrument for major decision checkpoints: final-review interpretation, acceptance/rejection of a branch, OOS/walk-forward/stress interpretation, and architecture changes. `Рой` does not override the active-run gate, visible-run requirement, no-live-orders rule, or acceptance gates.

If swarm agents are unavailable or their limits are exhausted, mark the checkpoint as `swarm_limited`, continue under direct Codex control using the same gates, and reconnect `Рой` after limits recover.

### Task 1: Funding Persistence Ranking

**Files:**
- Modify: `trading_mvp/src/basis.py`
- Modify: `trading_mvp/src/cli.py`
- Modify: `trading_mvp/run_mvp.ps1`
- Test: `trading_mvp/tests/test_basis.py`

**Step 1: Write failing tests**

Add tests proving that `funding-rank` computes funding observations, positive ratio, average/min/max/std funding and rejects unstable markets when persistence filters are strict.

**Step 2: Run test to verify it fails**

Run: `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis`

Expected: FAIL before `FundingRankConfig` and persistence metrics exist.

**Step 3: Implement minimal code**

Add `FundingRankConfig`, group rows by `exchange:spot_symbol:perp_symbol`, enrich the latest row with history metrics, compute `funding_persistence_score`, add `persistence_adjusted_total_score`, and sort eligible persistent markets first.

**Step 4: Add CLI and PowerShell parameters**

Expose `--min-funding-observations`, `--min-funding-positive-ratio`, `--min-funding-persistence-score`, `--funding-persistence-weight` in `funding-rank` and equivalent PowerShell parameters.

**Step 5: Verify**

Run: `& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests`

Expected: PASS.

### Task 2: 24h Funding Collection

**Files:**
- Use: `trading_mvp/run_mvp.ps1`
- Output: `exports/trading-mvp/funding/funding_collect_24h_<stamp>.jsonl`
- Output: `exports/trading-mvp/funding/funding_collect_24h_<stamp>.manifest.json`

**Step 1: Start duration-equivalent collection**

Run funding collect for enough cycles to cover 24 hours across MEXC and Gate, keeping max pairs wide enough to avoid a one-market sample.

**Step 2: Postprocess only after final manifest**

Check manifest `final=true`, row count, cycle coverage, error breakdown, and last write time before running rank/backtest.

**Step 3: Rank with persistence gates**

Run `funding-rank` with at least `min_funding_observations=6`, `min_funding_positive_ratio=0.75`, and non-negative persistence score.

**Step 4: Backtest baseline**

Run `funding-backtest` on the same JSONL and record funding PnL, basis PnL, fees, slippage, net PnL, winrate and expectancy.

### Task 3: Rolling Funding Backtester

**Files:**
- Modify: `trading_mvp/src/basis.py`
- Modify: `trading_mvp/tests/test_basis.py`

**Step 1: Add rolling metrics**

Compute persistence metrics using only rows before or at the current timestamp to avoid lookahead.

**Step 2: Gate entries**

Allow entries only when rolling observations, positive ratio and persistence score pass configured thresholds.

**Step 3: Verify no lookahead**

Add a test where a future negative funding print cannot invalidate or improve a past entry decision.

### Task 4: Volume Profile And Regime Filters

**Files:**
- Create or modify: `trading_mvp/src/volume_profile.py`
- Modify: `trading_mvp/src/basis.py`
- Test: `trading_mvp/tests/test_volume_profile.py`

**Step 1: Add market structure metrics**

Compute POC, high-volume nodes, value area, average spread and quote update density from collected market data.

**Step 2: Use as filter, not alpha**

Filter carry entries during poor liquidity, wide spread, low trade-flow density or unstable basis regimes.

### Task 5: Stress And Cost Model

**Files:**
- Modify: `trading_mvp/src/basis.py`
- Test: `trading_mvp/tests/test_basis.py`

**Step 1: Add stress scenarios**

Model spread widening, no-fill, basis gap, funding flip, venue outage and forced close.

**Step 2: Add acceptance gates**

Reject configs that become net negative under reasonable stress assumptions.

### Task 6: Out-Of-Sample Paper Forward

**Files:**
- Output: `exports/trading-mvp/funding/paper_forward_<stamp>.jsonl`
- Output: `docs/agent-log/<date>-paper-forward.md`

**Step 1: Freeze config**

Choose config only from in-sample 24h-7d data and write it to artifact.

**Step 2: Run paper-forward**

Run without live orders, API keys, leverage or margin execution.

**Step 3: Accept or reject**

Accept only if net PnL after costs, expectancy, drawdown, sample size and stability pass predefined gates.

### Task 7: Live Readiness Gate

**Files:**
- Created: `docs/analysis/live-readiness-checklist.md`

**Step 1: Write checklist**

Include API key isolation, position limits, venue risk, kill switch, logging, reconciliation, tax/export, error handling and monitoring.

Status: completed on 2026-06-17 as a hard gate. Live remains blocked until research and paper-forward gates pass and the checklist is satisfied.

**Step 2: Do not enable live trading automatically**

Live trading requires explicit user approval after research gates pass.
