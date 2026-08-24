# PlanOnly: slow-regime-gated spot/perp basis v1

Дата: 2026-08-19  
Статус: frozen research-only. Collect / evaluator / OOS / paper / live запрещены этим документом.  
Контракт: `docs/plans/slow-regime-gated-spot-perp-basis-planonly-v1.json`  
Live artifact: `exports/trading-mvp/analysis/slow_regime_gated_spot_perp_basis_planonly_20260819_current.json`  
Вердикт на текущих named artifacts: `INFEASIBLE_ON_CURRENT_NAMED_ARTIFACTS` (пересечение вселенных = 0, порог 10).

## Гипотеза

AND, не OR. Входить в long-spot / short-perp basis mean-reversion **только если** тот же non-Binance base уже находится в замороженном 1h compression или valid 1h retest против 4h-контекста.

Funding — блокирующий фильтр, не PnL. Отрицательный базис закрыт: нужен short спота.

Это **новая** запись реестра, не склейка двух родительских веток и не портфель «то одно, то другое».

Родители:

- `spot_perp_basis_mean_reversion_no_funding`
- `slow_liquidity_regime_breakout_retest`

## Замороженные параметры

Режим: 1h/4h, 15m выключен. Lookback 96×1h + 42×4h. Compression ≤ 1.2 ATR-scaled, минимум 24 бара. Breakout buffer 60 bps. Retest 12 баров / 0.35 ATR.

Базис: round-trip base/VIP0 fees + slippage + 20 bps adverse-basis buffer. Spot short запрещён.

Feasibility до OOS: ≥10 общих баз, ≥100 независимых AND-событий, 2 биржи, ни одна база >25% событий.

## Запрещённые evidence

- `spot_perp_basis_collect_20260819_083140` (REJECTED_INCOMPLETE)
- 14-event slow-liquidity sample как объект ретюна
- OR-объединение вселенных родителей
- grid / post-hoc пороги

## Исполнение

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\trading_slow_regime_gated_spot_perp_basis_planonly.ps1 -Json
```

Скрипт не обновляет active-run gate и не запускает сеть.
