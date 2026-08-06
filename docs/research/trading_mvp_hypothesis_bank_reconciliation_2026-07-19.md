# trading_mvp: Reconciliation Of Fast-First Hypotheses

Дата: `2026-07-19`.

Этот документ не меняет frozen hypothesis bank. Он устраняет расхождение между его старыми статусами и последующими immutable closure artifacts.

| Ветка | Авторитетный статус | Последствие |
|---|---|---|
| `cross_venue_perp_basis_convergence_history_v1` | `INSUFFICIENT_DATA` / `INSUFFICIENT_EXECUTABLE_UNIVERSE` | Не собирать и не ретюнить повторно на прежнем контуре. |
| `funding_regime_persistence_carry_v2` | `INSUFFICIENT_DATA` после train/OOS boundary | Не открывать повторно без materially new contract/data source. |
| `gate historical membership v2` | `INSUFFICIENT_SOURCE_QUALITY` | Lifecycle end coverage не прошла frozen gate. |
| `gate archive-membership v3` | `INSUFFICIENT_SOURCE_QUALITY` | Archive metadata не восстановила missing-end cohort: `0/10` при `80%` minimum. |
| Daily fast candidates v4-v6 | `NO_FAST_EDGE_ON_CURRENT_DAILY_DATA` | Повторный подбор сигналов на текущих данных запрещен. |
| Legacy HFT, same-venue funding, listing-event, slow-liquidity, cross-venue spot | Ранее закрыты economics/OOS/source gates | Не являются fast-track кандидатами. |
| `pit_universe_membership_drift_reversion_v1` | `BANKED_NEEDS_NEW_DATA` | Отдельный shadow track; требует новую календарную дату и валидное schedule approval. |
| `dense_ws_microstructure_regime_filter_v1`, `listing_forward_liquidity_decay_v1` | `BANKED_NEEDS_NEW_DATA` | Не запускать без нового materially distinct PlanOnly и data contract. |

## Вывод

Для имеющихся fast-track caches нет открытой ветки, которую можно честно перевести в history/OOS или paper/live. Корректный промежуточный статус: `NO_FAST_EDGE_FOUND_IN_CURRENT_CACHED_MEXC_GATE_BRANCHES`.

Это не равнозначно общему `NO_EDGE`: PIT shadow track еще не накопил достаточное число независимых дат, но он не находится на критическом пути быстрого historical verdict. Следующий план обязан быть materially distinct, иметь отдельный source/data contract и не ослаблять закрытые thresholds.
