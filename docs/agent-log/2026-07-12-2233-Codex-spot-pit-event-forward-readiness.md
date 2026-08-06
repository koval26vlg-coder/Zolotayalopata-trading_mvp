# Codex: spot PIT event forward readiness

## Дата и время

2026-07-12 22:33 +03:00

## Исходный запрос

Продолжить цель `trading_mvp` вручную после остановки Роя: найти, доказать или честно отвергнуть non-Binance edge с положительным net expectancy после базовых издержек, не запуская длительные процессы скрыто и не переходя к replay/grid/live без доказательств.

## План

1. Сверить gate и фактическое состояние веток.
2. Завершить durable collector/analyzer для независимой future PIT выборки.
3. Закрыть failure modes same-venue, VPN/zero-row, resume и двойного запуска.
4. Запечатать approval packet и оставить actual collect заблокированным до явного подтверждения.

## Выполнено

- Подтверждено, что Рой отменён пользователем и не перезапускался.
- Зафиксированы закрытые ветки:
  - cross-venue spot dislocation: verified rejected after base costs;
  - cross-venue lead/lag: 51,278,447 rows, 12 bases, zero fixed signals;
  - cross-sectional 4h capitulation: 307,593 rows, 40.67 days, zero fixed signals.
- Реализован `spot_pit_idiosyncratic_crash_reclaim_1m` future evidence pipeline:
  - durable 6h JSONL segments, cycle journal, state, alert, atomic manifest;
  - same `run_id` resume without overwrite;
  - current Binance spot exclusion as reference-only;
  - same-venue return, entry and exit, without venue-splicing;
  - base/VIP0 costs: 120 bps normal, 245 bps stress;
  - 2h data-quality stop remains incomplete/resumable;
  - 48h futility stop becomes final rejected when signals <10 or bases <5;
  - full 14d only when early gates pass;
  - OOS, walk-forward, stress, economics and independent audit remain mandatory.
- Zero-row network cycles are merged from `cycles.jsonl` and counted as quality failures instead of corrupting the analyzer.
- Provider forces metadata refresh on first call after resume.
- Preflight/plan hashes and sealed collection parameters fail closed.
- Visible wrapper verifies every artifact hash, preflight freshness, disk headroom, gate state and a named launch mutex before starting.
- Approval packet created; no collector was started.

## Ключевые артефакты

- Plan: `E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_planonly_20260712_2145.json`
- Public preflight: `E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_public_preflight_20260712_214801.json`
- Approval packet: `E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_approval_packet_20260712_223112.json`
- Approval SHA-256: `e1ca2ad17933c00bab2869872c17f9ae918fcb505be502a10ac7e0b3adbb0144`
- Targeted test evidence: `E:\ZolotyayLopata-data\exports\trading-mvp\analysis\spot_pit_event_forward_readiness_tests_20260712_223112.json`

## Изменённые файлы

- `trading_mvp/src/spot_pit_event_analyzer.py`
- `trading_mvp/src/spot_pit_event_collector.py`
- `trading_mvp/src/spot_pit_event_readiness.py`
- `trading_mvp/tests/test_spot_pit_event_analyzer.py`
- `trading_mvp/tests/test_spot_pit_event_collector.py`
- `trading_mvp/tests/test_spot_pit_event_readiness.py`
- `tools/start_spot_pit_event_forward_visible.ps1`
- `tools/build_spot_pit_event_forward_approval_packet.ps1`
- `tools/run_trading_tests.ps1`
- `tools/trading_next_goal_step.ps1`
- `tools/trading_goal_status.ps1`
- `docs/plans/2026-07-12-trading-mvp-current-goal.md`
- `docs/agent-log/active-run-gate.json`
- `docs/agent-log/current-run.json`

## Проверки

- Targeted readiness: 22/22 passed.
- Final fast shard: 165/165 passed in 35.174s.
- PowerShell parsing: passed.
- Visible wrapper PlanOnly: `would_start=false`, no collector/PID/run directory created.
- Gate: `READY_FOR_POSTPROCESS`, replay/grid/paper/live/API keys blocked.
- Disk E: 781.17 GiB free at readiness time.

## Риски и ограничения

- Стратегия не принята; edge ещё не доказан.
- Public REST snapshots are not HFT-grade data and cannot prove queue priority or sub-second execution.
- A fresh public preflight is required if a new run is started more than 24 hours after the sealed preflight; resume keeps the original preflight by design.
- A network/data-quality stop must resume the same `run_id`; creating a replacement run would lose the attempted-sample evidence.
- No threshold tuning is allowed on future collected data.

## Следующий шаг

Ждать явного подтверждения пользователя. После подтверждения запустить только видимую команду из approval packet. Пока подтверждения нет, разрешены status и PlanOnly preview; actual collect, replay, grid, paper-forward, live orders и API keys запрещены.
