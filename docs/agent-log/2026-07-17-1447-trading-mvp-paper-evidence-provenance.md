# trading_mvp paper evidence provenance

- Дата/время: 2026-07-17 14:47 +03:00
- Агент: Codex
- Режим: bounded offline code work; public network, OOS, grid, paper-forward и live не запускались.

## Runtime status

- Gate: `READY_FOR_POSTPROCESS`; активных PID нет.
- Завершенный `gate_historical_membership_v2_20260717_055756` не перезапускался.
- Terminal verdict остается `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Delisted-end coverage `0.3830 < 0.90`; `replay_allowed=false`.
- Единственный следующий network action остается отдельным exact-approved visible membership-v3 archive-source probe.

## Исправленный proof gap

- Старый `build_paper_event` принимал свободный JSON/dict с entry/exit prices, funding и execution metrics. Такой вход позволял вручную сформировать 15 положительных paper events без неизменяемого public-data provenance.
- Добавлены immutable source artifacts для `entry_execution`, `exit_execution` и `funding_settlements`.
- Каждый source artifact проверяет raw file path/SHA-256, schema, safety flags, canonical selection identity и запрещает ручные PnL-поля.
- Добавлен immutable evidence artifact, hash-bound к plan, approval, causal selection, probe plan и всем трем source artifacts.
- `paper-event` теперь принимает только evidence path плюс ожидаемый evidence hash. Свободный mapping больше не является публичным интерфейсом.
- Event validation и ledger reconciliation транзитивно повторяют цепочку `raw -> source -> evidence -> event`; изменение raw-файла после применения события приводит к fail-closed ошибке.
- В `run_mvp.ps1` добавлен action `fast-edge-membership-momentum-v2-paper-evidence` и обязательный `ExpectedEvidenceHash` для paper-event.

## Проверки

- TDD RED подтвержден отсутствием source/evidence contract.
- Новый paper-state suite: `8/8 OK`.
- Полный membership-momentum-v2 suite: `53/53 OK`.
- Full regression: `1066 OK`, `5 skipped`, `0 failures`, `518.031s`.
- Python compile: OK.
- PowerShell AST parse: OK.
- `git diff --check` и trailing-whitespace audit: OK.

## Границы

- Реальные paper approval/state/event не создавались.
- Public network probe, archive payload, returns, train, OOS, execution probe, grid, live orders и private API keys не запускались.
- Кодовая готовность не является доказательством edge.

## Следующий checkpoint

- Для продолжения источника данных требуется отдельное exact-approved visible membership-v3 archive-source probe по frozen plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- До реального historical/execution ACCEPT paper-контур остается dormant.
