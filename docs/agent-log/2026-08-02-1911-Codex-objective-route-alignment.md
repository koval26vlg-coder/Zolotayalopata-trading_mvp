# trading_mvp objective-route alignment

- Проверена связь исходного One-Week Historical Edge Sprint с текущей Accelerated Evidence Factory.
- `cross_venue_perp_basis_convergence_history_v1` остаётся terminal `INSUFFICIENT_DATA`: публичной Gate 5m истории было около `34.722` дня вместо frozen `220` дней. Edge не оценивался, повтор или retune того же контракта запрещены.
- bounded v2 остаётся terminal `INSUFFICIENT_EXECUTABLE_UNIVERSE`: `5` surviving assets вместо frozen minimum `8`; OOS, returns и PnL не читались.
- `dense_ws_microstructure_regime_filter_v1` является отдельным materially distinct кандидатом: новые публичные MEXC/Gate WS данные, отдельная causal materialization и отдельный no-grid evaluator contract. Он не переоткрывает basis v1/v2.
- Exact 24-hour campaign является только конкретным позднейшим user-approved исключением из старого общего лимита трёх часов. Это не общий отказ от approval-bound runtime для других запусков.
- Dense evaluator сохраняет нужные цели: chronological `70/30` split, `300s` embargo, five chronological folds без refit, normal/stress costs, positive after-cost expectancy, PF, paired-fill, drawdown, concentration и capacity gates.
- Текущий пробел: evaluator semantics amendment ещё не frozen, runtime consumer отсутствует, real evaluator запрещён. Этот checkpoint не блокирует PIT, campaign collection, quality или causal materialization.
- Верхний active-route pointer в `docs/plans/2026-07-14-trading-mvp-current-goal.md` обновлён без изменения frozen trading contracts; новый SHA-256 `52c7435dbafa08cebe0a2a55e7516d345eacf8d98d7a4ffef00c1ea1c5097554`.
- Immutable audit: `docs/agent-log/readiness/trading-mvp-objective-route-alignment-audit-20260802T1911+0300.json`, SHA-256 `c200f9f14a79240fb20678ad1ee4e516e11b51f9e86f71affeae0d2ae99f9f26`.
- Итог: `OBJECTIVE_ALIGNED_MATERIALLY_DISTINCT_SUCCESSOR_NOT_YET_PROVEN`; цель остаётся ACTIVE и не завершена.
- Никакой collector, market-data read, returns/PnL/OOS, evaluator, grid/retune, paper/live или private API не запускались.
