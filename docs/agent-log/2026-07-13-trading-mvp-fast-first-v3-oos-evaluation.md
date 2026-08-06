# trading_mvp Fast-First v3 OOS evaluation

Date: 2026-07-13 23:34-23:43 +03:00
Agent: Codex, manual mode; swarm disabled

## Request

Run the explicitly approved visible owned OOS evaluation, with user deadline no later than 2026-07-14 07:00 +03:00.

## Execution

- Added `tools/run_fast_first_v3_evaluation_visible.ps1` with visible PowerShell, owned gate, ISO approval deadline, 30-minute hard runtime, deterministic repeat and fail-closed `STOPPED_INCOMPLETE` handling.
- Run: `fast_first_v3_lottery_max_oos_20260713_233437`.
- Frozen plan hash: `3f086ac9c0f59c9690a63870f03ba44543559e08271333e73ae7957e86e240f7`.
- Seal: 195/195 files and Merkle `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1` matched.
- Two evaluations completed in 9.724 seconds total and produced the same deterministic result hash `e826f5437f9a36dcdbd5af9faedfcf5391e8d8a767ac0cb31e0b4ad6f197fbf1`.
- No grid, collect, execution probe, paper-forward, API keys, live orders, leverage or margin.

## Result

- Verdict: `INSUFFICIENT_DATA`.
- Main OOS: 2 events versus required 20; Gate 0/10, MEXC 2/10; only 2 unique rebalance dates versus required 10.
- Main OOS net PnL `-497.39577292`, expectancy `-248.69788646`, PF `0.14234766`, positive-event rate `0.50`, stress PnL `-506.25102292`.
- Robustness OOS: 8 events, net PnL `-1029.90211106`, expectancy `-128.73776388`, PF `0.48964082`, stress PnL `-1073.55511106`.
- Walk-forward: 1/5 positive combined folds.
- Capacity proxy passed, but it cannot compensate for insufficient observations and negative economics.

## Artifacts

- Evaluation: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v3\evaluations\fast_first_v3_lottery_max_oos_20260713_233437.json`.
- Repeat: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v3\evaluations\fast_first_v3_lottery_max_oos_20260713_233437.repeat.json`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v3\manifests\fast_first_v3_lottery_max_oos_20260713_233437.manifest.json`.
- Canonical ledger correction: `exp_20260713_204307_198661329ca8`; source is `internal://trading_mvp`, not channel content.

## Verification

- Visible worker PID 7156 exited; no live process remains.
- Gate is final `READY_FOR_POSTPROCESS`, errors 0, expected outputs complete.
- PowerShell parse and PlanOnly launcher smoke passed.
- Targeted experiments/tooling tests: 16 passed.
- Real experiment-record integration succeeded with explicit fee revision, evaluation scope and OOS status.

## Decision

Do not retune `venue_local_lottery_max_factor_v1` on this dataset and do not launch an execution probe. The next allowed project action is a genuinely new Fast-First hypothesis in PlanOnly, using existing data and no grid/live/API keys.
