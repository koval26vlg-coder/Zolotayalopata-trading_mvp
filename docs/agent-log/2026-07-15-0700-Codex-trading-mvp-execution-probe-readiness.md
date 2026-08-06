# trading_mvp execution-probe readiness

Дата: 2026-07-15 07:00 Europe/Volgograd  
Агент: Codex  
Режим: research-only, no-grid, no-retune, no-live, no-API-keys

## Реальное состояние

- Active gate: `READY_FOR_POSTPROCESS` для завершённого `pit_universe_v2_forward_20260715_n01`.
- Manifest: `final=true`, `36/36` cycles, `61,092` rows, `0` errors.
- Quality ledger: `2` accepted records и `2/20` distinct accepted train dates: `2026-07-14`, `2026-07-15`.
- Сертификаты подтверждают `returns_read=false` и `pnl_read=false`.
- Реальный train feasibility, OOS, execution probe и paper-forward не запускались.
- Следующий полезный segment: `pit_universe_v2_forward_20260716_n03`, `2026-07-16 23:00-23:20 +03:00`.

## Реализованный переход после будущего OOS

- `trading_mvp/src/pit_membership_drift_execution_probe.py`: immutable PlanOnly и offline evaluator.
- `trading_mvp/src/pit_membership_drift_execution_probe_collector.py`: bounded public collector с append-only resume.
- `tools/start_pit_membership_drift_execution_probe_visible.ps1`: visible owned wrapper, exact plan-hash confirmation, progress/ETA и fail-closed gate.
- `trading_mvp/run_mvp.ps1`: actions `fast-edge-pit-execution-probe-plan` и `fast-edge-pit-execution-probe-evaluate`.
- `tools/run_pit_full_evaluation_visible.ps1`: после реального historical ACCEPT создаёт только probe PlanOnly/approval packet, но не запускает probe.

Frozen execution gate: 20 минут, 5-секундный cadence, 240 attempts, минимум 180 valid snapshots, global coverage >= 0.80, `$500` на каждую ногу, worst-leg p95 impact <= 10 bps. Для каждой candidate base отдельно также требуются coverage >= 0.80 и worst `base x venue x side` p95 <= 10 bps; pooled metrics не могут скрыть плохую отдельную монету.

## Проверки

- Execution-probe unit: `10 OK`, включая два RED/GREEN сценария per-base masking.
- Visible wrapper/full-evaluation targeted: `7 OK`.
- Full regression: `699 OK`, `5 skipped`, `309.444s`.
- Python compile: OK.
- PowerShell AST parse: 0 errors.
- `git diff --check`: exit 0; только существующее LF/CRLF warning.
- Regression log: `docs/agent-log/2026-07-15-full-regression-pit-execution-probe-per-base.log`.
- Canonical goal SHA-256: `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.

## Граница интерпретации

Synthetic `ACCEPT_FOR_SHORT_EXECUTION_PROBE` доказывает только orchestration и fail-closed contract. Он не является доказательством edge. До реального `20/20 -> FEASIBLE_FOR_OOS -> 100 untouched OOS -> ACCEPT_FOR_SHORT_EXECUTION_PROBE` execution probe запускать нельзя. Повторный collector в ту же принятую календарную дату proof count не увеличивает.

Старый generic `fast_edge.py::record_paper_segment` не используется для PIT-маршрута: он не моделирует позиции, живущие до трёх последовательных quality dates, и не реализует canonical PF/stress gates. Strategy-specific paper-forward остаётся отдельным будущим контрактом после реального `PAPER_READY`, с явным подтверждением пользователя.
