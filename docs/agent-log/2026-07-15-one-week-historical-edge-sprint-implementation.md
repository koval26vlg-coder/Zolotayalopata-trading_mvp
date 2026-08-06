# Отчёт агента: One-Week Historical Edge Sprint

## Метаданные

- Дата и время: 2026-07-15, Europe/Volgograd
- Агент: Codex
- Проект: `trading_mvp`
- Запрос: реализовать недельный historical edge sprint для MEXC/Gate perp-perp basis convergence.

## План

1. Реализовать immutable PlanOnly/universe/history/quality/train/OOS/probe/report pipeline.
2. Ввести content-addressed code snapshot и resource-scoped run gate.
3. Реализовать paper-only two-leg OMS.
4. Покрыть no-lookahead, costs, OOS embargo, resume/cache и fail-closed тестами.
5. После локальной верификации выполнить только bounded visible universe preflight.

## Выполнено

- Добавлены `historical_basis_edge`, `historical_basis_universe`, `historical_basis_collector`, `historical_basis_quality`, `historical_basis_evaluator`, `historical_basis_probe`.
- Добавлены `historical_basis_code_snapshot`, `owned_run_gate` и `basis_paper_oms`.
- `run_mvp.ps1` расширен basis-actions и stage-specific runtime caps.
- Plan, universe, collect, quality, evaluate, probe и report привязаны к одному проверяемому content-addressed code snapshot.
- Collector пишет atomic RUNNING manifest до сети, поддерживает cache и fail-closed resume с исходным immutable range.
- OOS evaluator не читает OOS shard до hash-valid train-feasibility.
- Probe/report отделяют historical ACCEPT от execution/paper readiness.
- Resource-scoped gate блокирует overlapping writer/consumer, но разрешает явно объявленную offline-работу по независимым ресурсам.
- Paper OMS использует append-only hash-chain WAL, восстановление state, internally computed PnL, reconciliation и kill-switch.
- В hypothesis bank добавлен новый контракт без изменения старого execution-gate v2.
- Исправлен старый WS fail-closed wrapper: отсутствие `ExpectedManifestPath` теперь проверяется до тяжёлого fingerprint normalized artifact.

## Проверки

- Basis/OMS/gate affected shard после retention-классификатора: `67/67 OK`.
- Целевые retention-тесты: `2/2 OK`.
- Full discovery: `762` теста, `5` skipped; единственная ошибка была timeout старого WS wrapper guard после 120 секунд.
- После локализации исправленный тест: `1/1 OK` за 3.7 секунды.
- Полный wrapper-модуль после исправления: `31/31 OK`, `5` skipped.
- Python compileall: OK.
- PowerShell parse: `run_mvp.ps1`, `check_active_run_gate.ps1`, `run_ws_replay_validation_visible.ps1` — OK.
- Hypothesis bank JSON parse: OK.

Полный discovery после точечного исправления целиком повторно не запускался: все остальные 761 проверки уже прошли в предыдущем discovery, а весь изменённый wrapper-модуль проверен отдельно.

## Изменённые файлы

- `trading_mvp/run_mvp.ps1`
- `tools/check_active_run_gate.ps1`
- `tools/run_ws_replay_validation_visible.ps1`
- `trading_mvp/src/historical_basis_*.py`
- `trading_mvp/src/historical_basis_code_snapshot.py`
- `trading_mvp/src/owned_run_gate.py`
- `trading_mvp/src/basis_paper_oms.py`
- соответствующие `trading_mvp/tests/test_historical_basis_*.py`, `test_basis_paper_oms.py`, `test_active_run_gate.py`
- `docs/research/trading_mvp_hypothesis_bank_v1.json`
- `docs/plans/2026-07-15-trading-mvp-one-week-historical-edge-sprint.md`

## Риски и ограничения

- Edge/PnL не доказан: ветка закрыта до evaluation.
- Gate public 5m candles ограничены последними `10000` точками, около `34.722` дня. Замороженные `220` дней через этот endpoint недоступны.
- OHLCV не доказывает fill/capacity; historical ACCEPT не даёт paper/live разрешение.
- Worktree содержит большое количество прежних user/agent изменений; они не откатывались и не включались в отдельный commit.

## Видимый preflight и закрытие

- Run: `historical_basis_universe_20260715_114700`.
- Runtime: `92.276` секунды.
- Candidates: `12`; eligible: `0`.
- Первичный immutable artifact: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis\universe\basis_universe_20260715_114700.json`.
- Первичный SHA-256: `43d21425aa38406b6ddae03243d49c77baab0871bef8be02d8c404a673667363`.
- Прямая диагностика Gate для старой HYPE 5m boundary: HTTP `400`, `INVALID_PARAM_VALUE`, `Candlestick too long ago. Maximum 10000 points recently are allowed`; тот же endpoint на свежем часовом диапазоне вернул HTTP `200` и `13` строк.
- Исправлена классификация: retention error теперь не маскируется под отсутствие истории инструмента.
- Closure report: `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis\reports\basis_sprint_retention_closure_20260715_115819.json`.
- Closure file SHA-256: `55fe4c4e07d54e5ffd48aac04f49b4087cb0d6539bc387171dc19a7e02d6d19c`.
- Итог: `INSUFFICIENT_DATA`, reason `GATE_5M_PUBLIC_HISTORY_RETENTION_LT_FROZEN_220D`.

Следующей команды для ветки нет. Collector, train/OOS, probe, paper-forward и live не запускаются; frozen contract не ослабляется.
