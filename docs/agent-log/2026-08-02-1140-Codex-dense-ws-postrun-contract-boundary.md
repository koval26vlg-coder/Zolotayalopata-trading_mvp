# Dense WS: contract-freeze и безопасный postrun

- Время: `2026-08-02T11:40:01+03:00`.
- Агент: Codex.
- Запрос пользователя: разрешить только contract-freeze для dense_ws signal/evaluator,
  `proposal_hash=a9ec751329e436c1ea30b63433c57cf0e9ffd35370a097735c9ce91f71bb40d7`,
  без evaluator, returns/PnL/OOS, grid/retune, paper/live/private API, капитала,
  leverage или margin.

## Что сделано

- Подтверждена неизменность frozen signal/evaluator contract:
  - contract hash: `b70975468fbd67acf550dea39aac21c116fb3a86a57ed56d400f40f0fa287954`;
  - file SHA-256: `a9ef768d6f61297d01d8fe37a9d4e00b27cf5b2d52f122ab8ca9a0c3fae5a81d`.
- Подтверждена неизменность frozen non-executable PlanOnly:
  - plan hash: `620b1711a5436c722acea99d41c4b81ba57bd317069456282814939b3eefeea2`;
  - file SHA-256: `2ae9f20892eeb65772aa40c8bee0c905935dd50af2c57e29232ecc9418168fdb`.
- Frozen PlanOnly уже содержит обязательную будущую привязку campaign manifest,
  quality report, causal materialization, regime labels, execution snapshots и
  raw BBO hashes. Второй дублирующий PlanOnly до появления данных не создавался.
- Authoritative guard получил fail-closed `dense_ws_postrun_disposition` и
  последовательно разрешает только quality, затем causal materialization, затем
  подготовку нового materialization-bound PlanOnly. Evaluator автоматически не
  запускается.
- Добавлен единый видимый postrun orchestrator
  `tools/run_dense_ws_postrun_visible.ps1`. Он имеет общий предел 1800 секунд,
  не допускает второго owner, запускает materialization только после quality PASS
  и всегда останавливается до evaluator.
- Heartbeat оставлен ACTIVE и привязан к этой последовательности; повторное
  разрешение contract-freeze или campaign launch не требуется.

## Изменённые файлы и SHA-256

- `trading_mvp/src/autopilot_guard.py`: `6246b0859397110d55e6858f8d84fd6ba9f59bd79b826c18e4e708f833b10323`.
- `trading_mvp/tests/test_autopilot_guard.py`: `f2c0bb3bf095390c14490c4f9265e54e4d22fad046cd83f6b00a7d99ee1e06b4`.
- `tools/run_dense_ws_postrun_visible.ps1`: `ea18fd8e883a45089840974a1eb138c49c7fced5fd7e3f42109ea8b5a3e5dda9`.
- `trading_mvp/tests/test_dense_ws_postrun_orchestration.py`: `9d9c12cf02fc7300aa242e20deaa65f6d46d2e184cef2044f903a4bf49686045`.
- `trading_mvp/src/fast_regression_lane.py`: `81c96e0c3c4a6d481a82c3393956b92420468e6eee08bb6064617ed10956abe7`.
- `trading_mvp/tests/test_fast_regression_lane.py`: `ef4a901c1c1966e18652b5622befea04ea4da932dcc04cb4ba3350adf4d444f1`.
- `docs/plans/trading-mvp-autopilot-policy-v1.json`: `299d6950be009258d99da101f508c886fd277490d2d94c7102a0332667751bf5`.

## Проверки

- Frozen-file validator: `VALID_FROZEN_CONTRACT_AND_NON_EXECUTABLE_PLANONLY`.
- Связанные contract-freeze/postrun tests: 10 passed.
- Полная bounded fast regression: 253 tests, 0 failures, 0 errors, 0 skipped;
  deterministic result hash
  `c4665554465f3dc8c6c2398c774d5ae72b40cdc3cb9c514bade10d00c79b4abb`.
- Python compile: passed.

## Ограничения и следующий шаг

- `evaluation_authorized=false`, `executable=false`.
- Не читались market returns, PnL или OOS; не запускались evaluator, collector,
  grid, retune, paper-forward, live/private API, капитал, leverage или margin.
- Следующий реальный шаг: утверждённый PIT n06, затем утверждённая 24-часовая
  dense_ws campaign. После завершения guard сам проведёт quality и causal
  materialization. Только после их PASS будет построен новый точный PlanOnly и
  отдельно запрошено разрешение на evaluator.

