# PIT extension tooling end-to-end verification

- Время: `2026-07-31 10:43 +03:00`
- Агент: Codex
- Цель: проверить, что обязательная регенерация PIT schedule extension в approval window создаёт новый immutable PlanOnly и не может перезаписать stale candidate.

## Guard

- Autopilot: `ACTIVE`.
- PIT: `WAITING`, `5/20`.
- Next run: `pit_universe_v2_forward_20260801_n04`.
- Extension freshness: `REFRESH_REQUIRED_AT_APPROVAL_WINDOW`.
- Approval request: `NOT_DUE`.

## Проверки

- PowerShell parse для
  `tools\build_pit_schedule_horizon_extension_planonly.ps1`: `PASS`.
- Targeted regression:
  - `test_pit_schedule_horizon.py`;
  - `test_autopilot_guard.py`;
  - `test_pit_postrun_policy.py`;
  - итог: `46/46 PASS`.
- Попытка вызвать wrapper с существующими default `v1` outputs завершилась fail-closed:
  `Refusing to overwrite immutable horizon audit`.
- Existing immutable SHA-256 остались без изменений:
  - horizon audit:
    `81531a36caba9f30f1d8aacb76d35ba0bdd32699a7556dbe9d3eb16073382fac`;
  - extension PlanOnly:
    `58f84c63d83da30ada0491d7bdd7c51e7202b7d090ab666a0fcb3cc2664b6297`.

## Disposable end-to-end build

В уникальном временном namespace построены новый horizon audit и extension
PlanOnly, после чего generated plan прошёл штатный hash validation.

- Decision: `PLANONLY_EXTENSION_REQUIRED`.
- Accepted dates: `5`.
- Maximum reachable before extension: `16`.
- Target: `20`.
- Shortfall: `4`.
- Recommended extension nights: `5`.
- Combined maximum: `21`.
- Extension activated: `false`.
- Explicit approval required: `true`.
- Generated plan hash:
  `e708a66eee814a3bdd7a7ef1f85227e1c32072e7e242a6ceee6dab663e6ed4d3`.
- Validator returned the same plan hash.
- Safety:
  - network: `false`;
  - returns/PnL/OOS/signals read: `false`;
  - hypothesis/venue/universe/cost/risk changes: `false`;
  - grid/retune/paper/live/private API/leverage/margin: `false`.

Временный namespace удалён после проверки. Постоянный schedule state, policy,
pointer, approval records и immutable `v1` outputs не менялись.

## Handoff

At or after `2026-08-10 19:00 +03:00`:

1. Перечитать authoritative guard.
2. Вызвать builder только с новыми versioned `AuditOutputPath` и
   `ExtensionOutputPath`.
3. Обновить candidate binding в policy на новые file/hash/plan values.
4. Повторно перечитать guard.
5. Только затем запросить exact hash-bound schedule approval.
