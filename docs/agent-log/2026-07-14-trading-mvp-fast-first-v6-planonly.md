# 2026-07-14 - Codex - trading_mvp Fast-First v6 PlanOnly

## Исходный запрос
Продолжить активную цель Fast-First после закрытия v5 как `INSUFFICIENT_DATA`.

## План
- Проверить Aion context и active-run gate.
- Не ретюнить v4/v5 и закрытые ветки.
- Выбрать последнюю независимую Fast-First гипотезу v6.
- Реализовать PlanOnly/data seal без чтения OOS PnL.
- Запустить bounded PlanOnly freeze и обновить gate.

## Сделано
- Создан модуль `trading_mvp/src/weekend_liquidity_window.py`.
- Создан wrapper `tools/build_fast_first_v6_planonly.ps1`.
- Созданы тесты `trading_mvp/tests/test_weekend_liquidity_window.py`.
- Заморожена v6 гипотеза `venue_local_weekend_liquidity_window_v1`.

## Гипотеза
Fixed UTC weekend-liquidity calendar window на same-venue USDT linear perpetual markets. Отличается от закрытых веток: не funding/carry, не wick-rejection, не momentum/breakout, не cross-venue, не HFT/orderbook, не listing-event, не slow-liquidity, не residual/lottery/MAX.

## Артефакты
- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\plans\fast_first_weekend_liquidity_window_planonly_20260714_143640.json`.
- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v6\manifests\fast_first_v6_weekend_liquidity_planonly_20260714_143640.manifest.json`.
- Launch record: `docs/agent-log/fast_first_v6_weekend_liquidity_planonly_20260714_143640.launch.json`.

## Результат PlanOnly
- plan hash: `18af65fc211d31a8a0f38bc6d9161b4adf7a92404aba788dfb66c45d2af850a9`.
- input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`.
- markets total: `97`.
- candidate weekend entry days: `29`.
- evaluation_allowed: `false`.
- oos_metrics: `{}`.
- gate: `READY_FOR_POSTPROCESS`, `FAST_FIRST_V6_PLAN_FROZEN`.

## Проверки
- `python -m unittest trading_mvp.tests.test_weekend_liquidity_window`: `5 OK` using `C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe`.
- `py_compile trading_mvp/src/weekend_liquidity_window.py`: OK.
- PowerShell parser for `tools/build_fast_first_v6_planonly.ps1`: OK.
- PlanOnly build + independent validation: OK.

## Ограничения
- OOS/evaluation не запускался.
- До evaluator readiness нельзя читать OOS метрики.
- v6 является последней дополнительной гипотезой после v4 по текущему Fast-First контракту.

## Следующий шаг
Implement and test the hash-bound no-grid v6 evaluator. If v6 OOS later returns `REJECT` or `INSUFFICIENT_DATA`, record `NO_FAST_EDGE_FOUND` for current Fast-First track unless the user explicitly opens a new research scope.
