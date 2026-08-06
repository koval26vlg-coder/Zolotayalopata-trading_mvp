# trading_mvp START72H approval packet hardening

- Время: 2026-06-30 16:49:54 +03:00
- Агент: Codex
- Исходный запрос пользователя: продолжить активную цель trading_mvp, не запуская long-run без явного START72H.
- Цель шага: усилить доказательность будущего 72h dense WS collect за счет pre-run approval/evidence packet с fingerprint конфигурации, universe и guard-скриптов.

## Что сделано
- Добавлен 	ools/trading_ws_collect_approval_packet.ps1.
- Packet non-starting: would_start=false, esearch_only=true, live_orders=false, pi_keys=false, leverage_or_margin=false.
- Packet проверяет active gate, edge preflight, next-goal, goal status, WS readiness, approval contract, swarm status, test runner plan и PlanOnly preview.
- Packet пишет xports/trading-mvp/analysis/trading_ws_collect_approval_packet_current.json.
- Packet фиксирует SHA256 fingerprints 15 критичных файлов: universe CSV, collect wrapper, run_mvp, ws_collector, readiness, approval contract, preflight, next-goal, goal status, swarm status, test runner, postprocess, replay validation, confirmed/preview shortcuts.
- TRADING_START_DENSE_WS_CONFIRMED.cmd теперь запускает approval packet после readiness + approval contract и до запроса START72H; при ошибке старт отменяется.
- 	ools/trading_edge_preflight.ps1 теперь статически проверяет approval packet script и exposes ws_collect_approval_packet_command.
- 	ools/trading_goal_status.ps1 и 	ools/trading_next_goal_step.ps1 показывают packet command.
- 	rading_mvp/tests/test_visible_ws_collect_wrapper.py расширен regression tests для packet, shortcut order, preflight/status/next-step outputs.

## Артефакты
- xports/trading-mvp/analysis/trading_ws_collect_approval_packet_current.json
- Размер packet artifact: 11273 bytes на момент проверки.
- Packet status: READY_FOR_START72H_APPROVAL_PACKET, fail_count=0, warn_count=0, fingerprints=15.

## Проверки
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_edge_preflight.ps1 -Json: PASS; READY_FOR_EDGE_PROOF_STEP, fail_count=0, warn_count=0.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_next_goal_step.ps1 -Json: PASS; decision=SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT, packet command present, actual collect still requires approval.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\trading_ws_collect_approval_packet.ps1 -Json: PASS; READY_FOR_START72H_APPROVAL_PACKET, fingerprints=15.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1 -TestPath trading_mvp/tests -Pattern test_visible_ws_collect_wrapper.py: PASS; 17 tests OK, skipped=1.
- pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run_trading_tests.ps1: PASS; 223 tests OK, skipped=1.

## Gate / ограничения
- Active run gate after checks: READY_FOR_POSTPROCESS.
- eplay_allowed=false; replay/grid/postprocess на старом artifact запрещены.
- Новый market long-run не запускался.
- Следующий рыночный шаг требует явного START72H и видимого запуска.
- Live orders/API keys/leverage/margin не используются.
- Swarm status remains SWARM_LIMITED; manual Codex fallback is active until swarm runtime recovers.

## Git / рабочая область
- Проверенные файлы показываются git как untracked (??), это текущее состояние рабочей области; ничего не откатывал.

## Следующий агент
- Перед любым шагом снова запустить 	ools/check_active_run_gate.ps1.
- Если пользователь не дал точный START72H, не запускать long WS collect.
- Если пользователь дал START72H, использовать только видимый shortcut/visible wrapper: TRADING_START_DENSE_WS_CONFIRMED.cmd или command_after_explicit_approval после readiness/approval packet.
- После завершения будущего collect: guarded ws-postprocess -> replay validation PlanOnly with same ExpectedManifestPath -> отдельный review/Рой checkpoint before ConfirmedResearchRun.
