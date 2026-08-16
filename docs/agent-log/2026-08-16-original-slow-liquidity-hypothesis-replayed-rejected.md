# 2026-08-16 — исходная slow-liquidity гипотеза: фактический replay выполнен, robust edge нет

Checkpoint-решение (вариант 1 из предложенных): довести гипотезу до
фактического replay. Выполнено без изменения параметров сигнала —
вырожденный v0-нормализатор обходится штатным путём репо:
**event census v1** (4 семьи детекторов) → fixed_v1 → replay executor.

## Chain (все артефакты в exports/trading-mvp/analysis/)

1. **Census на v6-датасете с identity-универсумом** (7 баз, 14 рынков):
   scope-адаптер `slow_liquidity_identity_census_scope_20260816.json`
   (clean_bases = 7 identity-принятых баз, EDGE/RAIN исключены) →
   `slow_liquidity_event_census_v1_v6_identity_20260816.json`
   - raw candidates 169, **independent events 101**, 6 баз, 2 venue
   - top family `volatility_expansion_continuation_v1`: 68 событий,
     6 баз, концентрация BDX 29.4%
   - семьи не проходят замороженную приёмку (68<100 событий, 6<7 баз,
     29%>25% концентрация) → census decision REJECTED_INSUFFICIENT —
     accept невозможен fail-closed
2. **Exploratory fixed-v1 packet**
   (`slow_liquidity_exploratory_fixed_v1_packet_20260816.json`,
   `packet_hash=d07705e9…`): тот же контракт/издержки (120/245 bps),
   family = top, явно помечен `exploratory_underpowered=true`,
   `acceptance_eligible=false`, перечислены проваленные критерии —
   acceptance-вердикты из него запрещены by construction
3. **Фактический replay** `slow_liquidity_replay_v1.py` →
   `slow_liquidity_exploratory_replay_v1_20260816.json`

## Результаты replay (68 сделок, long-only, после издержек)

| метрика | full | train 70% | OOS 30% | stress 245bps |
|---|---|---|---|---|
| win rate | **10.3%** | 8.5% | 14.3% | 10.3% |
| expectancy/сделку | **−463 bps** | −484 bps | −417 bps | −588 bps |
| profit factor | **0.054** | 0.043 | 0.083 | 0.023 |
| net PnL (notional) | −315 | −227 | −88 | −400 |

walk-forward: **0 из окон принято**. Executor decision:
`SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE`.

## Вердикт

Исходная slow-liquidity гипотеза (continuation/breakout long-only на
медленных низколиквидных базах) на точном v6-датасете **решительно
отрицательна**: после издержек теряется ~4.6% notional на сделку при
winrate 10%; продолжения движений нет. Это фактический replay исходной
гипотезы на готовых данных — цель достигнута, содержательный ответ:
**robust edge отсутствует**. Терминальное REJECT-решение по ветке — за
пользователем; по экономике данных оснований для продолжения ветки нет.

Дополнено (23:40): семья `liquidity_shock_reclaim_long_v1` (33 события)
тоже зареплеена: winrate 24.2%, expectancy −571 bps/сделку, PF 0.16,
OOS −635 bps, walk-forward 0/4. Обе семьи census-ветки отрицательны —
ретроспектива v6 исчерпана полностью
(`slow_liquidity_exploratory_replay_v1_liquidity_shock_20260816.json`).

## Статус веток

- v0 normalizer: compression-гейт вырожден (evidence `682b7c76…`) —
  закрыт доказательно
- v1 census/replay: executed, edge нет
- forward-ветка новых листингов: продолжает накапливать выборку
  (тики каждые 6ч, расписание авторизовано)
