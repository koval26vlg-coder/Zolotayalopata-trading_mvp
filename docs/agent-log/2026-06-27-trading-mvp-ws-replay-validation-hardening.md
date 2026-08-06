# trading_mvp WS replay validation hardening

Дата: 2026-06-27
Агент: Codex
Запрос/контекст: продолжение активной цели trading_mvp после `Рой` review. Не запускать long-run без явного подтверждения.

## План
- Проверить active-run gate и Aion/SML контекст.
- Усилить guarded `run_ws_replay_validation_visible.ps1` против stale/wrong artifact.
- Проверить PlanOnly и negative guard ветки.
- Проверить preflight, next-step, acceptance gate и unit tests.

## Что сделано
- В `tools/run_ws_replay_validation_visible.ps1` добавлены:
  - `-ExpectedManifestPath` для явной привязки postprocess artifact к конкретному `ws_collect_*.json`;
  - fingerprint для `postprocess`, `normalized`, `quality`, `manifest`: SHA256, bytes, last_write;
  - schema guard для обязательных полей `ws_postprocess_guarded` artifact;
  - mismatch guards: `replay_allowed` vs `data_quality.accepted`, `quality_input_mismatch`, `quality_manifest_mismatch`, `quality_artifact_acceptance_mismatch`, `expected_manifest_mismatch`;
  - `quality_output`/`manifest` existence checks.
- В `tools/trading_edge_preflight.ps1` усилена проверка `ws_replay_validation_quality_gate`.
- В `tools/trading_next_goal_step.ps1` команды replay validation теперь включают `-ExpectedManifestPath`.

## Проверки
- `check_active_run_gate.ps1`: READY_FOR_POSTPROCESS, live process ids отсутствуют.
- `run_ws_replay_validation_visible.ps1 -PlanOnly -NoPause`: `reason=postprocess_required`.
- `run_ws_replay_validation_visible.ps1 -PostprocessPath <smoke> -ExpectedManifestPath <correct ws_collect> -PlanOnly`: `ok=true`, `would_run=false`, fingerprints present.
- Negative smoke with wrong ExpectedManifestPath: `reason=expected_manifest_mismatch`, no run.
- `trading_edge_preflight.ps1 -Json`: READY_FOR_EDGE_PROOF_STEP, 0 failures, 0 warnings.
- `trading_next_goal_step.ps1 -Json`: selected `SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT`; replay validation commands include ExpectedManifestPath.
- `trading_strategy_acceptance_gate.ps1`: research_only_no_accepted_strategy, live_orders=false.
- `python -m unittest discover -s trading_mvp/tests`: 198 tests OK.

## Риски и ограничения
- Реальный 6h WS collect/replay/grid не запускался.
- Smoke artifact короткий и relaxed; он доказывает guard mechanics, не edge.
- Edge, paper-forward и live остаются не приняты.

## Следующий шаг
Только после явного подтверждения пользователя: visible 6h WS collect -> guarded WS postprocess -> replay validation PlanOnly with explicit PostprocessPath and ExpectedManifestPath -> отдельное решение о ConfirmedResearchRun.
