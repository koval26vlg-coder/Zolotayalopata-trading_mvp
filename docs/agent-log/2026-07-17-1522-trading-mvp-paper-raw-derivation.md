# trading_mvp paper raw derivation

- Дата/время: 2026-07-17 15:22 +03:00
- Агент: Codex
- Режим: bounded offline code work; public network, OOS, grid, paper-forward и live не запускались.

## Runtime status

- Gate: `READY_FOR_POSTPROCESS`; активных PID нет.
- Membership-v2 остается terminal reject: `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Delisted-end coverage: `0.3830 < 0.90`; `replay_allowed=false`.
- Membership-v2 повторно не запускался.

## Исправленный proof gap

- Предыдущий source artifact только хэшировал raw-файл, но не доказывал, что строки с ценами, execution metrics и funding детерминированно получены из этого файла.
- Добавлен нормализованный raw-input schema без self-declared evidence hash.
- Добавлен immutable raw-source manifest, который проверяет raw file SHA-256, safety flags, plan/selection/signal metadata и детерминированно привязывает execution evidence hash к raw-файлу.
- Source artifact теперь создается только командой `build-source` из exact hash-bound raw manifest.
- Source validation транзитивно повторяет цепочку `normalized raw input -> raw manifest -> source` и отвергает rehashed строки, не совпадающие с derivation.
- В `run_mvp.ps1` добавлен offline action `fast-edge-membership-momentum-v2-paper-source` с обязательным `ExpectedRawManifestHash` и `MaxRuntimeSec<=1800`.

## Измененные файлы

- `trading_mvp/src/gate_membership_momentum_v2_paper_state.py`
- `trading_mvp/tests/test_gate_membership_momentum_v2_paper_state.py`
- `trading_mvp/run_mvp.ps1`

## Проверки

- Python compile: OK.
- PowerShell AST: OK.
- Targeted provenance/paper tests: `9/9 OK`.
- Membership-momentum-v2 suite: `54/54 OK`.
- Full regression: `1067 OK`, `5 skipped`, `0 failures`, `513.377s`.
- CLI `build-source --help`: OK.
- `git diff --check` для tracked wrapper и trailing-whitespace audit: OK.

## Ограничения

- Реальный public-data raw collector для paper entry, exit и funding пока не реализован; новый contract гарантирует derivation integrity, но не создает рыночные данные сам.
- Реальные paper approval/state/event не создавались.
- Кодовая готовность не доказывает edge и не разрешает live.

## Следующий checkpoint

- Единственный следующий network action остается отдельным exact-approved visible membership-v3 archive-source probe, frozen plan hash `e2aaa0d0212cef9e9aa104140cc71d3fe07bd6fd26900e5d59d0218a7ed88fe3`.
- До real historical ACCEPT paper-контур остается dormant.
