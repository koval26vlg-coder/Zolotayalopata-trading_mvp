# Codex spot/perp public probe hardening

Дата: 2026-07-09 12:57 +03:00
Агент: Codex
Запрос: продолжить активную цель после Claude architecture check.

## Gate перед работой
- status: READY_FOR_POSTPROCESS
- next_goal_decision: SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE
- replay_allowed: false
- requires_explicit_user_approval_for_public_probe: true
- Никаких collect/replay/grid/live/API keys/paper-forward не запускалось.

## Что сделано
- trading_mvp/src/funding.py:
  - добавлен TTL для MEXC ticker cache: 300 секунд;
  - fallback RuntimeError переведен на английский текст `GET failed: ...`.
- trading_mvp/src/spot_perp_basis_public_probe.py:
  - добавлена finite/range validation для order book и paired_base_ok;
  - crossed book теперь отклоняется;
  - paired_base_ok отклоняет нулевую глубину, слишком широкий spread, невалидный funding и невалидный next_funding_ts.
- trading_mvp/tests/test_funding.py:
  - добавлен regression test для TTL MEXC ticker cache.
- trading_mvp/tests/test_spot_perp_basis_public_probe.py:
  - добавлены tests для crossed book, unusable ranges, mocked _probe_mexc и _probe_gateio.

## Проверки
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_funding trading_mvp.tests.test_spot_perp_basis_public_probe trading_mvp.tests.test_spot_perp_basis_availability -> 18 OK.
- C:\Program Files\Python313\python.exe -m unittest trading_mvp.tests.test_basis trading_mvp.tests.test_spot_perp_basis_mean_reversion trading_mvp.tests.test_funding_pairs trading_mvp.tests.test_daily_collector -> 146 OK.
- C:\Program Files\Python313\python.exe -m py_compile trading_mvp/src/funding.py trading_mvp/src/spot_perp_basis_public_probe.py trading_mvp/tests/test_funding.py trading_mvp/tests/test_spot_perp_basis_public_probe.py -> OK.

## Ограничение проверки
- Полный `unittest discover -s trading_mvp/tests` был остановлен по timeout 180s; отдельный зависший процесс `C:\Program Files\Python313\python.exe -m unittest discover -s trading_mvp/tests` PID 37028 был завершен. Aion SML python процессы не трогались.

## Gate после работы
- status: READY_FOR_POSTPROCESS
- replay_allowed: false
- next_step_after_ready: await explicit confirmation, then short public REST probe command from active-run-gate.

## Следующий шаг
- Если пользователь явно подтверждает, запустить short public REST probe из active-run-gate.
- До подтверждения не запускать collect/replay/grid/live/API keys/paper-forward.
