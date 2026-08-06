# Dense WS AEF 24h: проверка лимита хранения

- Время: 2026-08-02 12:33 +03:00
- Агент: Codex
- Контекст: после contract-freeze проверить ресурсную безопасность уже утвержденной кампании `dense_ws_microstructure_regime_filter_v1_20260803_aef_24h` без запуска collector, evaluator или анализа доходности.

## План

1. Прочитать только frozen feasibility и PlanOnly.
2. Сверить ожидаемый объем с лимитом 25 ГБ и свободным местом.
3. Проверить фактическую остановку runner на лимите.
4. Добавить локальные unit-tests, не меняя hash утвержденного runner.

## Выполнено

- Frozen feasibility подтверждает медианный технический поток `142109.331 bytes/sec` и оценку `12278246229` bytes за 24 часа.
- Immutable cap: `25000000000` bytes, запас к оценке `2.036121x`; при базовой скорости cap соответствует `48.867` часа.
- На `E:` свободно `825070010368` bytes при prelaunch-требовании `53687091200` bytes.
- Runner hash остался `ed804ff811c321e4d9a5a8f56593f24ca320c635088fe7b271eec0bdacb4a977` и совпадает с PlanOnly.
- Runner рекурсивно считает весь campaign namespace, проверяет cap до старта и каждые 10 секунд во время writer; достижение cap приводит к остановке и `STOPPED_INCOMPLETE`.
- Добавлены два unit-test для aggregate-size и preflight cap boundary.

## Проверки

- `test_dense_ws_campaign_contract`: 23/23 PASS.
- Fast regression: 262/262 PASS, deterministic result hash `afbb86736024656b0337a4406a9718796778a5337581a34c497c5ca5ad728c92`.
- Capacity audit: `docs/agent-log/readiness/dense-ws-aef-24h-capacity-audit-20260802T123248+0300.json`.
- Capacity audit SHA-256: `c18b7877f6bdb339eccf9fa550ddd5497a3771149e74179b3d15d0c439406fc3`.
- Fast regression artifact: `docs/agent-log/readiness/dense-ws-capacity-fast-regression-20260802T122955+0300.json`.

## Ограничения

- Это monitored threshold, а не файловая квота ОС: между проверками в 10 секунд и мягкой остановкой возможен небольшой выход за 25 ГБ. Такой прогон становится `STOPPED_INCOMPLETE` и не допускается в evidence pipeline.
- Старый 72h dataset использован только через frozen aggregate feasibility summary для оценки скорости; raw market rows, returns, PnL и OOS не читались.
- Collector, evaluator, grid, retune, paper/live, private API, real capital, leverage и margin не запускались.

## Следующий шаг

- Сохранить утверждение кампании активным.
- Перед ночным запуском заново выполнить exact guard/preflight; не запускать второй writer.
