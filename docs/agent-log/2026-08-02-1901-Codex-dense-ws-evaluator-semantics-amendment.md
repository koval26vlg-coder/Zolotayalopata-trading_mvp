# Dense WS evaluator semantics amendment

- Разрешение пользователя на `runtime-refreeze` postrun сохранено отдельно и не расширено: quality `1800` секунд, causal materialization `1800` секунд, общий максимум `3600` секунд, окно `04.08.2026 01:30-02:30 +03:00`.
- Collector, postrun, evaluator и чтение returns/PnL/OOS не запускались.
- Аудит frozen evaluator contract нашёл недостающие точные правила. Без них одинаковые данные могли дать разные результаты в двух реализациях.
- Fail-closed audit: `docs/agent-log/readiness/dense-ws-evaluator-semantics-gap-audit-20260802T1854+0300.json`, SHA-256 `bc5b607df71e13fef64904f4197fdafec066882ee89919e9e9402744078595f9`.
- Подготовлен только неисполняемый amendment proposal: `docs/plans/drafts/dense-ws-evaluator-implementation-semantics-amendment-20260802-v1.json`, proposal hash `2c17be85d008d57b008136d0bb0bdcbef3f7bc7168620ba0aacd4e5f08645724`, file SHA-256 `3663a2109670ff67cb20a69ae8862c9374504700eac76000f0ea9a2393261bbd`.
- Proposal не является frozen contract, не разрешает реализацию evaluator и не разрешает оценку стратегии.
- Независимая swarm-проверка не завершила ответ; состояние зафиксировано как `swarm_limited`. Fail-closed решение сохранено.
- Heartbeat `trading-continuous-production` обновлён: старый недостаточно точный запрос implementation-only удалён; новый checkpoint привязан к amendment proposal и не блокирует уже одобренные PIT, dense campaign и postrun.
- Automation SHA-256 после обновления: `7f0f990e6b259ed690a2bc25abcf75e5156a0fc348bff6bd659261eeaa0a94bb`; status `ACTIVE`.
- Следующее отдельное разрешение может позволить только заморозить точные правила и построить калькулятор на synthetic fixtures. Использовать реальные рыночные данные и считать результаты стратегии оно всё равно не позволит.
