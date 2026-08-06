# trading_mvp OOS transition readiness

Дата: 2026-07-15 06:17 Europe/Volgograd  
Автор: Codex

## Запрос

Продолжить каноническую цель до 09:00 без бесполезного повторного market collect на уже принятой календарной дате.

## Выполнено

- `tools/run_pit_train_feasibility_visible.ps1` расширен fail-closed созданием `oos_accrual` PlanOnly только после двух совпадающих `FEASIBLE_FOR_OOS` результатов.
- OOS schedule получает первую дату после последней train date, максимум 14 ночей и сохраняет immutable hash/approval phrase; approval и collection остаются отдельной пользовательской границей.
- Реализован `tools/run_pit_full_evaluation_visible.ps1` для будущего owned visible `20+100` OOS verdict с двумя внешними deterministic запусками одного canonical output path.
- `trading_mvp/run_mvp.ps1` получил два узких owned gate маршрута: train feasibility плюс OOS PlanOnly и full evaluation. Grid, retune, probe, paper/live и API keys ими не открываются.
- Heartbeat `pit-visible-night-segments` обновлён для нового manifest contract; он уведомляет approval phrase, но не утверждает и не запускает OOS.

## Проверка

- Train transition tests: `7 OK`.
- Full-evaluation wrapper tests: `5 OK`.
- Combined PIT proof shard: `47 OK`.
- Full regression: `687 OK`, `5 skipped`, `261.175s`.
- PowerShell AST parse: `0` errors.
- `git diff --check`: OK.
- Canonical goal SHA-256: `aeba1732e66eb990ac44e88381a826fc464b6e5454e22eea11b2b63069371f1c`.
- Real project gate remained `READY_FOR_POSTPROCESS`; no PIT runtime process exists.

## Ограничения и следующий шаг

- Synthetic `ACCEPT_FOR_SHORT_EXECUTION_PROBE` proves tooling only. Real evidence remains `2/20`; no real OOS/PnL was read.
- Next useful market segment: `pit_universe_v2_forward_20260716_n03`, currently `AUTHORIZED`.
- Do not launch another segment for `2026-07-15`; it cannot add a distinct accepted date.
