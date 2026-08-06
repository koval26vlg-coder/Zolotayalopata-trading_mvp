# trading_mvp: Gate membership-v3 archive-source closure

- Время: 2026-07-19T18:04:46+03:00
- Агент: Codex
- Запрос: выполнить подтвержденный visible Gate archive-membership v3 public probe без payload, returns, OOS, grid, live или private API.

## Результат

Visible probe завершился за `20.654s`: `189/189` metadata tasks, `0` transport errors, `99` HTTP `200/206`, `90` HTTP `404`.

- `active_control`: `10/10` archive objects доступны.
- `known_end_delisted_control`: `5/5` archive objects доступны.
- `missing_end_delisted`: `0/10` archive objects доступны при frozen minimum `80%`.

Источник отклонен как `GATE_MEMBERSHIP_V3_ARCHIVE_SOURCE_REJECTED`. Это доказывает именно отсутствие требуемого archive-metadata источника для repair lifecycle ends, а не отсутствие рыночного edge.

## Immutable evidence

- Probe: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\probes\gate_historical_membership_v3_archive_source_20260717_0845.json`
- Probe artifact hash: `0bb761acc9efbc4bb99cb9e1004c5df7ad82f4c8aed531cee68b850f573138b4`
- Closure: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\closures\gate_membership_v3_archive_source_closure_0bb761acc9ef.closure.json`
- Closure manifest: `E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\closures\gate_membership_v3_archive_source_closure_0bb761acc9ef.closure.manifest.json`
- Closure verdict: `INSUFFICIENT_SOURCE_QUALITY`, `CLOSED_WITHOUT_HISTORY_OR_OOS`.

Closure повторно проверен по SHA-256/provenance. Он фиксирует `archive_payload_read=false`, `history_read=false`, `returns_read=false`, `pnl_read=false`, `train_read=false`, `oos_read=false` и запрещает history/train/OOS/retune/execution/paper/live для membership-v3.

## Исправление диагностики

`active-run gate`/visible launch record показал `errors=1`, хотя immutable source report содержит `quality.errors=0`. Причина: PowerShell считал отсутствующее JSON-поле `report.errors` как `@($null).Count == 1`.

Исправлен только расчет diagnostic error count в `tools/run_gate_historical_membership_v3_probe_visible.ps1`; исходный report и launch record не переписывались. Новый closure использует source artifact как авторитетный источник технического результата.

## Проверки

- TDD: новый closure-тест сначала упал из-за отсутствующего модуля, затем прошел.
- `python -m unittest -v trading_mvp.tests.test_gate_historical_membership_v3_closure` - `1/1 OK`.
- Revalidate closure manifest - OK.

## Следующий допустимый шаг

Только выбрать materially distinct PlanOnly-гипотезу или отдельный новый forward-data track. Повтор membership-v2/v3, archive payload/history, train/OOS, retune, grid, paper-forward и live не разрешены.
