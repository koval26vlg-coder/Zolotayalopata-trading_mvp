# 2026-07-14 - Codex - trading_mvp Fast-First v4 OOS verdict

## Исходный запрос

Пользователь явно подтвердил запуск: `подтверждаю visible owned OOS на 30 минут, завершить не позднее 2026-07-14T14:00:00+03:00`.

## План

- Проверить Aion bootstrap и active-run gate.
- Запустить один visible owned no-grid OOS через `tools/run_fast_first_v4_evaluation_visible.ps1`.
- Проверить manifest, gate и evaluation artifact.
- Зафиксировать verdict и следующий разрешенный шаг.

## Что сделано

- Запущен visible owned OOS run `fast_first_v4_funding_pressure_reversal_oos_20260714_132100`.
- Команда использовала `ConfirmedResearchRun`, `MaxRuntimeSec=1800`, `ApprovedNotLaterThan=2026-07-14T14:00:00+03:00`.
- Run завершился за `15.896` секунд по gate и выполнил два deterministic evaluation cycles.
- Manifest final: `true`, errors: `0`, stop reason: `completed_two_deterministic_evaluations`.

## Артефакты

- Manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\manifests\fast_first_v4_funding_pressure_reversal_oos_20260714_132100.manifest.json`
- Evaluation: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\evaluations\fast_first_v4_funding_pressure_reversal_oos_20260714_132100.json`
- Repeat: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-v4\evaluations\fast_first_v4_funding_pressure_reversal_oos_20260714_132100.repeat.json`

## Результат

- Verdict: `INSUFFICIENT_DATA`.
- Rejection reasons: `oos_portfolio_events_total_below_minimum`, `oos_portfolio_events_below_minimum:gateio`.
- Deterministic result hash: `18bacc1aa059069ac96e5cfe9edf3af45fd040fa425c82a22a1da3e77c41ee04`.
- Plan hash: `5396885aa9abf77a461f20aa190c843b86be098b76abd6f3a5655a8f725eee60`.
- Input Merkle: `1bab335f1de674b9ce074c803fa1ac937e38356cf87852e5e04455bd1f266ab1`.

## Ключевые метрики

- OOS closed calendar days: `60`.
- Total OOS portfolio events: `18/20`.
- Gate OOS portfolio events: `1/10`.
- MEXC OOS portfolio events: `17/10`.
- Unique rebalance dates: `17/10`.
- Main OOS price-only net PnL: `-383.38272157`.
- Main OOS price-only expectancy: `-21.29904009`.
- Main OOS price-only PF: `0.88405347`.
- Main OOS positive event rate: `0.61111111`.
- Main OOS stress price-only net PnL: `-417.38272157`.
- Robustness OOS price-only net PnL: `-1161.4040304`.
- Robustness OOS price-only PF: `0.57275583`.

## Риски и ограничения

- Это не accepted edge и не paper-ready result.
- Funding total PnL был положительным в main view, но acceptance contract требовал price-only PnL; price-only отрицательный.
- Gate coverage недостаточен: Gate дал только один OOS event.
- Probe, paper-forward, live/API keys, grid и retune для этой ветки запрещены.

## Следующий шаг

Только новая независимая Fast-First hypothesis PlanOnly. Не ретюнить `venue_local_funding_pressure_reversal_v1` на текущем evidence.
