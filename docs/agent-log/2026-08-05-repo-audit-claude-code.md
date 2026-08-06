# Аудит репозитория ZolotyayLopata — 2026-08-05

Автор: Claude Code. Режим: **только чтение**, ни один файл проекта не изменён и не удалён.
Гейт на момент аудита: `READY_FOR_POSTPROCESS`, `final=true`, `data_embargo=true` — исполнительная
активность запрещена, поэтому аудит ограничен офлайн-разбором.

## 1. Критично: полная версия `run_mvp.ps1` существует только как недостижимый git-blob

Рабочая копия `trading_mvp/run_mvp.ps1` — 95 706 байт, **45** action-веток, mtime 2026-08-02 00:03.
HEAD-версия — 88 772 байта, 42 ветки. То есть рабочая копия почти равна коммиту от 2026-06-16.

При этом в `.git/objects` лежит недостижимый blob `57e0602cacbbff82998ca706c54f74cffe5f2f1c`:
241 742 байта, 4256 строк, **147** action-веток, создан 2026-07-17 15:22. Он был проиндексирован
(`git add`), но никогда не закоммичен.

Покрытие 118 различных action-строк, которых требуют тесты:

| источник | байт | покрывает |
|---|---|---|
| `57e0602c…` (недостижимый blob) | 241 742 | **99 / 118** |
| `a959d76e…` | 226 513 | 90 |
| `c467be3a…` | 203 701 | 75 |
| рабочая копия | 95 706 | **4 / 118** |

Копий `run_mvp*.ps1` вне репозитория нет: поиск по дереву проекта и по `E:\ZolotyayLopata-data`
не дал ничего. Reflog содержит 2 записи, stash пуст.

Следствие: **`git gc` / `git prune` / `git repack -d` уничтожат единственную копию ~146 КБ
wiring-логики.** Сборку мусора выполнять нельзя до извлечения blob'а.

## 2. Тесты красные: 1549 тестов, 57 failures, 19 errors, 5 skipped

Прогон: `python -m unittest discover -s trading_mvp/tests`, 940 с.

Около 50 падений — прямое следствие п.1. Тесты читают `run_mvp.ps1` и ищут в нём строки
`"<action>" {`, которых там нет:

- `ValueError: substring not found` в `_case()` — 11 ERROR в `RunMvpVenueCostsWiringTests`
  (`fast-edge-v2…v6`, hash-binding, membership-drift, pit-paper-forward);
- `AssertionError: '"fast-edge-membership-momentum-train-plan"' not found` — семейства
  `test_gate_historical_membership_*`, `test_gate_membership_momentum*`;
- `test_historical_basis_run_mvp` (5), `test_historical_basis_v2_run_mvp` (6),
  PIT-визивные наборы, `night_schedule_quality/status`, `dense_ws_postrun_orchestration`,
  `funding_regime_persistence_v2(+_oos)`, `test_visible_ws_collect_wrapper` (7).

Подтверждение, что это откат оркестратора, а не удаление функциональности: Python-модули
для «пропавших» маршрутов на месте — `historical_basis_edge.py`, `historical_basis_collector.py`,
`historical_basis_probe.py`, `pit_membership_drift_evaluator.py`,
`gate_membership_momentum_v2_paper_state.py`, `dense_ws_campaign_runner.py`,
`night_schedule_quality.py`. Текущий `run_mvp.ps1` ссылается лишь на 2 `.py` из 183.

Отдельная причина, не связанная с п.1 — рассинхронизация campaign_id. Все 7 тестов
`DenseWsAcceptanceProposalTests` падают с
`ProposalIntegrityError: campaign_id mismatch: expected '…20260804_aef_24h', observed '…20260803_aef_24h'`:
`src/dense_ws_campaign_contract.py:96` объявляет `AEF_CAMPAIGN_ID = …20260804…`, а фикстуры
в `test_dense_ws_acceptance_proposal.py:35`, `test_dense_ws_campaign_feasibility.py:262`,
`test_dense_ws_materialization_bound_plan.py:60` остались на `…20260803…`. Это задевает и тесты
на отклонение подделки (`test_rejects_semantic_tampering_even_with_recomputed_hash`), то есть
защитный контур сейчас не проверяется.

## 3. Репозиторий фактически без резервной копии

1 коммит, единственная ветка `master`, **ремотов нет**. Отслеживается 182 файла против 767
записей в `git status`. По каталогам: 20/183 `src/*.py`, 17/201 `tests/*.py`, **0/152** `tools/*.ps1`.
Порядка 90% примерно 198 тыс. строк кода не под версионным контролем и не забэкаплено.

## 4. ~1 ГБ мусора в паке

Достижимый набор — 232 объекта / 2 358 851 байт (2,36 МБ). Единственный пак содержит
3994 объекта / 1 038 249 415 байт (`size-pack` 576 МиБ, `.git/objects` 863 МБ, loose 264,84 МиБ).
Крупнейшие недостижимые blob'ы опознаны по magic-числам: `6761b14…` 202 630 779 Б и
`96613c7…` 77 197 536 Б начинаются с `Cr24` — это упакованные **расширения Chrome (CRX)**;
`be47057…` 50 310 464 Б начинается с `TFL3` — **модель TensorFlow Lite**. Далее 41 МБ ×2,
36 МБ, 30 МБ, 27 МБ ×2, 19 МБ. Ни один не достижим ни из одной ссылки. Также 3 мусорных
`tmp_obj_*` в `.git/objects/{1d,a8,df}`.

Чистка вернула бы ~1 ГБ, но выполнять её нельзя до извлечения blob'а из п.1.

## 5. Гигиена и дрейф документации

- `.gitignore` сам **не отслеживается**; не покрывает `tmp*/`, `.serena/`, `.test-tmp/`, `.tmp-tests/`;
- 6 каталогов `tmp*` в корне, 1 в `trading_mvp/`, 7 в `trading_mvp/tests/`;
- локальный `exports/` 170 МБ при том, что авторитетные данные на `E:`;
- `trading_mvp/README.md` в разделе «Структура» описывает `src/{cli,config,collector,trading}.py`
  и `tests/{test_backtester,test_risk}.py` — против фактических 183 src и 201 test;
- `D:\AionUi-Paperclip\tools\status-memory-auto.ps1` не парсится из-за порчи кодировки
  (мохибаке `вЂ”`, `РІРµСЂ…`; ошибки на строках 38/42/46/47) — проверка статуса памяти нерабочая.

## Рекомендации (не выполнены, требуют подтверждения)

Порядок важен: п.1 строго до любой сборки мусора.

1. `git cat-file -p 57e0602cacbbff82998ca706c54f74cffe5f2f1c > trading_mvp/run_mvp.ps1.recovered`,
   сличить с рабочей копией (в ней могут быть правки от 2026-08-02, которых нет в blob'е),
   собрать объединённую версию, прогнать тесты.
2. Закоммитить untracked-код (`src`, `tests`, `tools`) и добавить remote — до этого любая правка
   необратима.
3. Синхронизировать campaign_id в трёх тестах на `…20260804_aef_24h`.
4. Только после 1–3: `git gc --prune=now` для возврата ~1 ГБ.
5. Дополнить `.gitignore`, поставить его под версионный контроль, убрать `tmp*`.
6. Перегенерировать раздел «Структура» в README.
7. Починить кодировку `status-memory-auto.ps1`.
