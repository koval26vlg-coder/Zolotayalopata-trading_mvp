# PIT night schedule provenance blocker

Дата: 2026-07-16 05:15 +03:00

Статус: `FAIL_CLOSED_APPROVAL_INVALID_CURRENT_PROVENANCE`

## Запрос

Выполнить embargo-safe checkpoint для утвержденного расписания
`pit_universe_v2_train_schedule_planonly_20260714_220219.json`, не читать returns/PnL/signals, не запускать дубликаты и восстанавливать pointer только через утвержденный immutable approval.

## Проверено

- Active-run gate открыт: `READY_FOR_POSTPROCESS`; активных market-data writers нет.
- Plan hash: `34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362`.
- Plan file SHA совпадает с immutable approval: `b1d4264fc577dd84464389b151361bcdfd42a13d56bb67390fc75b516b0071f2`.
- Immutable approval активен до `2026-07-28T07:00:00+03:00` и не изменялся.
- Canonical goal hash совпадает.
- Все 12 sealed runtime-tool hashes совпадают.
- В ledger находятся 2 technical-quality accepted distinct dates: `2026-07-14` и `2026-07-15`.
- Целевой `pit_universe_membership_drift_reversion_v1.3.0` contract полностью совпадает с sealed contract.
- Contract hash совпадает во всех местах: `b5e3abd4942fc117b92c324e931d8d91671df3de99b403875bcf38983c26d857`.

## Блокировка

Strict schedule validator отклонил расписание до authorization:

```text
hypothesis bank provenance hash mismatch:
expected=bff3952026ae2d9056cb9d0e5a480ce2caf7d4f8c5e4e6760ab46492901bec19
observed=85ee37afc7e2ba3855084ab9f961cd71677df35894d95263cccd5652a7c317a9
```

Текущий bank изменен после approval, хотя утвержденный target contract остался неизменным. Однако sealed visible wrapper и `night_schedule_plan.py` требуют hash всего bank. Изменение validator/wrapper или semantic bypass изменит approved runtime code и нарушит immutable approval. Временный откат bank также запрещен, поскольку затронет актуальные пользовательские изменения.

## Решение

- Pointer не восстановлен.
- `authorize-segment` не принят.
- Collector, feasibility и OOS не запускались.
- Returns, PnL и сигналы не читались.
- В рамках текущего запрета на новое approval безопасного пути продолжения нет.

Для продолжения потребуется новый hash-bound PlanOnly/approval, который запечатает текущий bank и тот же неизменный target contract. Это отдельное пользовательское решение; текущий immutable approval не перезаписывается.
