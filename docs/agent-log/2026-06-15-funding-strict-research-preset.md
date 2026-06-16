# 2026-06-15 funding strict research preset

Goal context: continue the research-only `trading_mvp` pipeline toward a funding/basis carry strategy that is accepted only after final collection, data-quality gates, OOS validation, stress validation, and paper-forward separation.

## Collector status

- Dataset: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.jsonl`
- Manifest: `exports/trading-mvp/funding/funding_collect_24h_rolling_20260615_162045.manifest.json`
- Status during latest check: still running
- Final: `false`
- Completed cycles: `35 / 288`
- Rows: `816`
- Errors: `206`
- Line count matches manifest: `true`
- Last write age during latest check: about `35s`

No postprocess/finalize was started because the manifest is not final.

## Change

Added CLI strict preset:

- `funding-postprocess --strict-research`
- `funding-finalize --strict-research`

Added PowerShell wrapper switch:

- `-FundingStrictResearch`

The preset applies the current 24h research gates:

- `allow_partial=false`;
- stress enabled with nonzero adverse basis, spread widening, and funding flip assumptions;
- OOS minimum train span `6h` and OOS span `6h`;
- data-quality minimums: `1000` rows, `5` markets, `250` completed cycles, `250` unique cycles;
- max data-quality error rate `0.30`;
- max duplicate cycle-market row rate `0.01`;
- acceptance concentration gates: at least `2` markets, max market trade share `0.65`, at least `3` profitable windows, max window PnL share `0.60`;
- paper-forward defaults for finalize: `24h`, `100` rows, `2` markets.

For `funding-postprocess`, strict mode auto-creates the OOS artifact path if `--oos-output` is not supplied. This prevents a strict run from accidentally skipping the OOS gate.

## Verification

- Targeted funding suite with explicit venv Python:
  - `Ran 51 tests ... OK`
- Full trading_mvp test suite with explicit venv Python:
  - `Ran 123 tests ... OK`
- PowerShell wrapper smoke:
  - `funding-status -FundingStrictResearch` accepted the switch and returned `status=running_or_waiting`, `ready_for_postprocess=false`, `final=false`.

## Next guarded step

When the collector reaches `final=true`, run `funding-finalize` with `-FundingStrictResearch`. If it rejects, keep the rejection as evidence and do not move to paper-forward until the failed gate is addressed by data or logic, not by weakening thresholds.
