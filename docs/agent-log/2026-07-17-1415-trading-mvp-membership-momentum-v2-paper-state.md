# trading_mvp membership-momentum-v2 paper state

- Дата/время: 2026-07-17 14:15 +03:00
- Агент: Codex
- Запрос: подтвержденный visible Gate historical-membership v2 public probe и продолжение текущей цели без повторного запуска уже завершенного `run_id`.

## Проверенный runtime status

- `gate_historical_membership_v2_20260717_055756` уже завершен: `1/1`, `1387` строк, `0` ошибок.
- Решение: `GATE_HISTORICAL_MEMBERSHIP_V2_SOURCE_REJECTED`.
- Причина: delisted-end coverage `0.3830` ниже frozen gate `0.90`.
- Returns/OOS/PnL не читались; history/train/OOS/retune для membership-v2 не запускались.
- Gate: `READY_FOR_POSTPROCESS`, `replay_allowed=false`, активных PID нет.
- Единственный следующий network action остается отдельным exact-approved visible membership-v3 archive-source probe; v2 повторно не запускать.

## Выполнено offline

- Добавлен `trading_mvp/src/gate_membership_momentum_v2_paper_state.py`.
- Добавлены hash-bound explicit paper approval, immutable paper event, append-only JSONL ledger, deterministic state projection и reconciliation.
- PnL вычисляется из prices/funding/frozen costs; ручные PnL-поля запрещены.
- Сохраняются weekly cadence, causal selection provenance, execution-quality/capacity gates и funding coverage.
- Добавлены kill-switch incidents и terminal statuses `PAPER_FORWARD_HALTED`/`PAPER_REJECTED`.
- `LIVE_REVIEW_ELIGIBLE` требует 15 независимых событий, positive net/expectancy, PF gate, non-negative stress, concentration <=25% и отсутствие violations; он не разрешает live.
- В `run_mvp.ps1` добавлены approve/init/event/apply/status/incident routes. Approval требует `-ConfirmedPaperForward`.
- Ни approval, ни paper-forward, ни network collector, ни live/API keys были запущены.

## Проверки

- TDD RED: отсутствующий state module.
- Новый state suite: `7/7 OK`.
- Соседняя membership-momentum цепочка: `20/20 OK`.
- Full regression: `1065 OK`, `5 skipped`, `0 failures`, `395.300s`.
- Python compile: OK.
- PowerShell AST parse: OK.
- `git diff --check`: OK; только предупреждение Git о будущем LF -> CRLF для `run_mvp.ps1`.

## Измененные файлы

- `trading_mvp/src/gate_membership_momentum_v2_paper_state.py`
- `trading_mvp/tests/test_gate_membership_momentum_v2_paper_state.py`
- `trading_mvp/run_mvp.ps1`

## Следующий checkpoint

- Не повторять membership-v2.
- Для network-пути требуется отдельное точное подтверждение frozen membership-v3 archive-source PlanOnly.
- Paper state можно активировать только после появления реального `PAPER_FORWARD_READY` execution report, immutable paper PlanOnly и отдельного exact hash-bound approval.
