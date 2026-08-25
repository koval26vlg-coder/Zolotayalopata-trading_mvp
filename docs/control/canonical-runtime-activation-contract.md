# Canonical runtime activation contract

Этот control-plane допускает только public-data research. Он не разрешает
authenticated API, реальные ордера, капитал, переводы, margin или leverage
execution. Успешная проверка или публикация registry не является доказательством
прибыльности стратегии и не разрешает live trading.

## Раздельные стадии

| Стадия | Артефакт/команда | Что разрешено |
|---|---|---|
| Committed source | `canonical_strategy_runtime.staging.json` | Описать канонические репозитории, планы и namespaces; запуск запрещён. |
| Immutable staging publication | `external_registry_materializer.py` | Выпустить внешнюю атомарную пару registry + materialization receipt из точных Git blobs; `STAGED_FAIL_CLOSED`. |
| Explicit promotion | `external_registry_promoter.py --promote` | Выпустить новую внешнюю пару registry + activation receipt для ровно одного готового public-research runtime; worker не запускается. |
| Read-only coordinator preflight | `invoke_listing_strategy_due_coordinator.ps1 -PreflightOnly` | Проверить publication, bindings, runtime и policy; без claim, state/ledger writes и launcher. |
| Installer dry-run | `install_listing_strategy_due_coordinator_task.ps1 -DryRun` | Проверить будущую Task Scheduler action через read-only preflight; без регистрации и worker. |
| Explicit installation | Installer без `-DryRun` | Зарегистрировать hash-bound scheduled action после всех проверок. Это отдельное операционное действие. |
| Scheduled wake | Coordinator `-ScheduledTick` | Повторно проверить bindings/topology/due-state; запускать только выбранный runtime, только когда due. |

Внутреннее поле registry `activation_status=ACTIVE_INSTALLED` обозначает ACTIVE
ветку контракта, но само по себе **не доказывает установку Windows task**. Факт
установки подтверждается отдельным результатом installer и readback Task
Scheduler. Promoter всегда сообщает `execution_performed=false`.

## Что связывает activation receipt

- Неизменяемые raw SHA parent registry/receipt и их историческую Git lineage.
- Ровно один `active_strategy_id`; остальные runtime остаются INACTIVE/RETIRED.
- Canonical repository, commit, PlanOnly identity/hash, launcher и implementation
  bindings выбранного runtime.
- Пять control-plane ролей: promoter, publication primitive, validator,
  coordinator и installer, с точными committed bytes.
- Public-only policy и разрешённые режимы `DISCOVERY`/`PAPER_RESEARCH`.

`active_runtime_binding.state_raw_sha256` — снимок **на момент promotion**, а не
постоянный запрет на изменение state. Следующие wake проверяют актуальный
automation-state; успешное продвижение state не требует переписывать immutable
receipt.

## Обязательный интерфейс runtime

Runtime должен иметь собственный automation wrapper, а не только data collector:

- `-ScheduledTick -Json -PlanPath <bound plan>` и канонический working directory;
- read-only `NOT_DUE` до любого writer claim или сетевой работы;
- `VISIBLE_TERMINAL_LAUNCHED` с `visible_terminal_pid`, либо корректный duplicate
  результат; произвольный PID не означает успешный запуск;
- отдельный automation-state с `status`, `next_interval_at_utc`,
  `last_attempt_id`, `last_finished_at_utc` и `worker_pid`;
- подтверждённый terminal result и append-only attempt evidence;
- retry-next-interval без tight-loop, сохранение pending retry и claims до
  фактического выхода worker.

Descriptive market-data snapshot нельзя дополнять фиктивными scheduling-полями
ради прохождения promotion. Для нового wrapper/state нужен новый immutable
PlanOnly successor с его SHA bindings.

## Операционная граница текущего checkpoint

- Pre-market v28 имеет статус `OFFICIAL_ATTESTATION_LINEAGE_HARDENED_NO_CAPTURE`.
  Старый production registry с receipt v24 требует отдельно разрешённого
  recovery/quarantine/bootstrap; capture этим checkpoint не разрешён.
- Expansion v10 ещё не имеет совместимого automation wrapper/state. Его
  descriptive state и `COMPLETED` collector result не заменяют scheduler
  `COMPLETE/RETRY_NEXT_INTERVAL` contract.
- Spot MEXC/Gate launcher также требует canonical scheduler-interface migration.
- Pre-IPO остаётся отдельным namespace с собственными data/official-event
  blockers; его нельзя активировать через готовность соседнего трека.
- Ни ACTIVE publication, ни установка scheduler, ни production capture не
  являются частью offline code/tests checkpoint.

Точные CLI параметры promoter доступны через `--help`. Все expected hashes,
Git commit, parent pair и publication root обязательны; не подставлять текущие
непроверенные bytes вместо заранее выбранных committed bindings.
