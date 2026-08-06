# trading_mvp: Terminal Evidence Audit For The One-Week Sprint

Дата: `2026-07-19`.

## Назначение

Этот документ фиксирует доказательный итог fast-track на уже имеющихся MEXC/Gate caches. Он не объявляет, что edge на этих рынках не существует вообще. Он запрещает выдавать за новый edge очередную вариацию уже проверенных и закрытых сигналов на тех же данных.

## Итоговый Статус

`NO_WEEKLY_EDGE_FOUND_MEXC_GATE_ON_CURRENT_CACHED_EVIDENCE`

Канонический результат недельного спринта для `cross_venue_perp_basis_convergence_history_v1` остаётся `INSUFFICIENT_DATA` / `INSUFFICIENT_EXECUTABLE_UNIVERSE`. Ни одна ветка на имеющихся caches не имеет права перейти в execution probe, paper-forward или live.

## Проверенные Ветки

| Ветка | Авторитетный артефакт | Вердикт | Причина закрытия |
|---|---|---|---|
| `cross_venue_perp_basis_convergence_history_v1` | `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis\reports\basis_sprint_retention_closure_20260715_115819.json` | `INSUFFICIENT_DATA` | Публичная Gate 5m history не покрывает замороженный 220-дневный контракт. |
| `cross_venue_perp_basis_convergence_1h_v2` | `E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\reports\basis_v2_terminal_report_quality_reject_primary_20260716_1916.json` | `INSUFFICIENT_EXECUTABLE_UNIVERSE` | Из 20 quality survivors только 5 прошли frozen `$1m` worse-leg train median quote-volume gate; требуется минимум 8. OOS/PnL не читались. |
| `gate_spot_perp_basis_mean_reversion_v2` | `E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2\reports\gate_spot_perp_train_closure_20260717_fast_faa446e2e44d.closure.json` | `INFEASIBLE_ON_CURRENT_DATA` | Экономически рассчитанный entry threshold `132 bps` не наблюдался: максимум train basis `122.022080 bps`. |
| `funding_regime_persistence_carry_v2` | `docs/agent-log/2026-07-17-funding-regime-persistence-v2-terminal-oos.md` | `INSUFFICIENT_DATA` | Всего 11 независимых OOS episodes при минимуме 20; price-only PnL отрицателен, stress PnL отрицателен, bootstrap lower bound отрицателен, положительный normal PnL концентрирован. |
| Daily Fast-First v4-v6 | `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\reports\fast_first_track_closure_no_fast_edge_found_20260714_1500.json` | `NO_FAST_EDGE_FOUND` | Все три fixed no-grid candidate не прошли acceptance gates; v6 имела только 7 OOS events, поэтому высокий номинальный PnL/Win rate не принят как evidence. |
| Gate historical membership v2/v3 | `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\closures\gate_membership_v3_archive_source_closure_0bb761acc9ef.closure.json` | `INSUFFICIENT_SOURCE_QUALITY` | Archive metadata дала `0/10` для missing delisted lifecycle-end cohort при frozen minimum `80%`; payload/history/returns/OOS не разрешены. |
| Legacy HFT, same-venue funding, listing-event, slow-liquidity, cross-venue spot | `docs/research/trading_mvp_hypothesis_bank_reconciliation_2026-07-19.md` | closed earlier | Economics, OOS или source-quality gates уже закрыли их для fast-track. |

## Что Это Значит

- Положительный nominal win rate или отдельный положительный normal PnL не заменяют sample, stress, concentration и execution gates.
- Создавать очередную signal family на том же daily/5m cache запрещено: это увеличит multiple-testing и data-mining risk, а не доказательность.
- Нельзя ретюнить entry threshold, hold time, TP/SL, universe или fees в закрытых ветках.
- Поле `errors=1` в active-run gate относится к старому control-state; v3 source artifact имеет `0` transport/data-quality errors и остаётся авторитетным для source verdict.

## Разрешенный Контур

Единственный открытый контур на текущий момент: `pit_universe_membership_drift_reversion_v1` как независимый shadow track с новыми календарными датами. Он не является доказательством edge до накопления и certification новых observations.

Создан новый immutable PlanOnly:

- путь: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260720_1809.json`;
- hash: `32aa73fe5af72c18eda78f6010165debd8be8b8a19d38101da97a484cf95bd61`;
- 14 видимых сегментов по 20 минут, с `2026-07-20T23:00:00+03:00` до `2026-08-02T23:20:00+03:00`;
- stage: `train_accrual`;
- network collection: ещё не начат;
- перед каждым сегментом обязательны active-run gate, hash-bound authorization, disk guard и technical-quality certification.

Schedule tests: `14/14` passed. Approval gate по умолчанию закрыт; запуск какого-либо сегмента требует именно approval phrase, сохранённую в PlanOnly artifact. Нет auto-resume, grid, OOS, replay, probe, paper-forward, private API keys, live orders, leverage или margin.

## Следующее Разрешенное Действие

Только одно из двух:

1. Пользователь подтверждает текущий PIT schedule по exact plan hash, после чего запускается первый видимый 20-минутный segment в его календарное окно.
2. Создаётся новый materially distinct `PlanOnly` source/data contract, не использующий закрытые caches и не меняющий закрытые thresholds. Сам сетевой сбор по нему требует отдельного явного согласования.

До одного из этих действий проект не должен запускать повторный OOS, новый grid, execution probe, paper-forward или live mode.
