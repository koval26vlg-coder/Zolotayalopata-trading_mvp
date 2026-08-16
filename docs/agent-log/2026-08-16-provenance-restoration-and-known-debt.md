# 2026-08-16 — восстановление provenance: 157 файлов закоммичено, known-debt зафиксирован

Обнаружено и устранено: несколько предыдущих сессий оставляли готовую
работу незакоммиченной. Мои коммиты listing-momentum цепочки (fd7a3aa,
6c7755a, b831f0b, eb9925b) неявно зависели от untracked-файлов
(spot_v2_official_page_discovery и далее вся цепочка calendar-first /
listing-announcement / scope / official_date / first_days_close).

Сделано:

- `52a52c3` — 157 файлов: 27 untracked src-модулей предыдущих сессий
  (spot-v2 r1-r4, calendar-first, listing-announcement, listing-first,
  orderbook/orderflow/vwap), их тесты, agent-logs, approvals, claim
  архивы, readiness-снапшоты
- merge `wip/spot-v2-identity-refreeze` (b0e08a8) в master: 780 строк
  spot-v2 identity pivot (perp→spot инструменты, COLLISION_FAIL_CLOSED
  для EDGE/RAIN, FROZEN_V3 fast-path) — без них momentum-цепочка не
  импортируется; ветка удалена после merge
- run_mvp.ps1 рефакторинг + 3 helpers, AGENTS.md (действующая редакция
  autopilot policy), live state файлы — закоммичены
- рабочее дерево чистое (`git status` 0 dirty, кроме env-каталогов
  .codex/.postman)

## Known-debt: 2 красных теста — ЗАКРЫТО 2026-08-17

Тесты переделаны на честную семантику (см. agent-log
2026-08-17-known-red-tests-resolved.md): замороженные артефакты
проверяются на внутреннюю консистентность, world-state зависимости
(terminal launch record, execution manifest/receipt, gate decision)
мокаются. 195 passed по всем затронутым семействам. Историческая
запись о причине долга сохранена ниже.


1. `test_checked_in_spot_v2_freeze_matches_generator` — spot-v2 runtime
   manifest замораживал sha256 `one_week_edge_sprint_readiness.py`
   (543ae85d…, эпоха 440195b) и `autopilot_guard.py` (32341e5a…); модули
   дрейфовали дальше (текущие 0b21c34a… / 584c5f3d…). Re-freeze =
   treadmill: эти модули нужны живому v4-line и меняются независимо.
2. `test_offline_refreeze_readiness_resolves_without_execution_artifacts`
   — `one_week_edge_sprint_readiness` требует отсутствия terminal launch
   record v3, который существует (ран фактически был).

Оба относятся к терминально-закрытой identity-ветке (v3/v4 discovery
TERMINAL_REJECT, two-venue official identity CLOSED_AS_INCOMPLETE);
141 остальных теста линии зелёные. Чинить только вместе с решением по
v6 identity (см. ниже) — иначе это бесконечный re-freeze без новых
доказательств.

## Открытый контрактный вопрос (checkpoint для пользователя)

Датасет v6 (30 021 строка, 9 баз, качество принято) заблокирован для
replay требованием официальной identity. WIP-код уже реализует
практичную альтернативу: identity = одинаковое имя спот-тикера на обоих
venue + fail-closed на неоднозначных (EDGE, RAIN). Принятие этого
правила (аналогично proxy-датам) разблокирует fixed-signal → replay
исходной slow-liquidity гипотезы. Без него v6 остаётся заморожен.
