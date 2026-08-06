# 2026-07-14 - Codex - trading_mvp Fast-First v5 OOS insufficient

## Исходный запрос
Продолжить активную цель trading_mvp Fast-First proof pipeline после корректировки политики подтверждений.

## План
- Проверить Aion context и active-run gate.
- Создать visible owned no-grid OOS wrapper для v5.
- Проверить wrapper тестами и PowerShell parser.
- Запустить короткий visible owned v5 OOS без grid/live/API.
- Зафиксировать verdict и следующий разрешенный шаг.

## Сделано
- Создан `tools/run_fast_first_v5_evaluation_visible.ps1`.
- Обновлен `trading_mvp/tests/test_powershell_tooling.py` под v5 wrapper и v5 run_mvp wiring.
- Запущен visible owned no-grid OOS:
  - run id: `fast_first_v5_wick_rejection_oos_20260714_142908`;
  - `MaxRuntimeSec=1800`;
  - actual duration: about 8 sec;
  - no collector, no grid, no retune, no probe, no paper-forward, no live/API/leverage/margin.

## Результат
- Verdict: `INSUFFICIENT_DATA`.
- Deterministic result hash: `e5558024c9daeccfa9414e9eaa13b72f050558bf8d47407d10c236a94492a3a2`.
- Deterministic repeat equal: `true`.
- OOS events: `0`.
- Main net PnL: `0`.
- Rejection/insufficiency reasons:
  - `oos_portfolio_events_total_below_minimum`;
  - `oos_portfolio_events_below_minimum:mexc`;
  - `oos_portfolio_events_below_minimum:gateio`;
  - `unique_oos_signal_dates_below_minimum`;
  - `capacity_proxy_unavailable`.

## Артефакты
- Evaluation: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\evaluations\fast_first_v5_wick_rejection_oos_20260714_142908.json`.
- Repeat: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\evaluations\fast_first_v5_wick_rejection_oos_20260714_142908.repeat.json`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v5\manifests\fast_first_v5_wick_rejection_oos_20260714_142908.manifest.json`.
- Launch record: `docs/agent-log/fast_first_v5_wick_rejection_oos_20260714_142908.launch.json`.

## Проверки
- `python -m unittest trading_mvp.tests.test_powershell_tooling trading_mvp.tests.test_wick_rejection_reversal` through `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe`: `25 OK`.
- `py_compile` for `trading_mvp/src/wick_rejection_reversal.py` and `trading_mvp/src/cli.py`: OK.
- PowerShell parser: `tools/run_fast_first_v5_evaluation_visible.ps1` and `trading_mvp/run_mvp.ps1`: OK.
- Wrapper `-PlanOnly`: OK.
- Active-run gate after OOS: `READY_FOR_POSTPROCESS`, `FAST_FIRST_V5_INSUFFICIENT_DATA`.

## Риски и ограничения
- Python from PATH is not available in this shell; tests and wrapper were run with `TRADING_MVP_PYTHON=C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe`.
- Worktree contains many pre-existing unrelated dirty/untracked files; they were not cleaned or reverted.
- V5 produced zero OOS events, so it is closed as insufficient rather than optimized further.

## Следующий шаг
Freeze a genuinely new independent Fast-First hypothesis in PlanOnly, without retuning v5. Do not start collectors/grid/probe/paper/live without the applicable explicit approval.
