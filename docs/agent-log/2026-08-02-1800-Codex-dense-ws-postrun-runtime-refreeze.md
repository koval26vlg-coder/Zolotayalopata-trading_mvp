# Dense WS postrun runtime-refreeze

- Пользователь одобрил только изменение лимита времени по `proposal_hash=0a5884a3599a52e39b6fce438e945743f5bf6bfa2a7cbea779dd0ca54cf40662`.
- Quality и causal materialization выполняются последовательно в одном видимом терминале: максимум `1800 + 1800 = 3600` секунд.
- Разрешённое окно postrun: `04.08.2026 01:30-02:30 +03:00`.
- Wrapper строго проверяет proposal, approval receipt, PlanOnly, policy, quality/materializer code hashes, reservation и hard deadline.
- Найдена и исправлена ошибка локального разбора даты: PowerShell сначала прочитал `2026-08-04` как 8 апреля. Теперь JSON-даты сохраняются строками и разбираются только как `yyyy-MM-dd`.
- Проверки: `5/5` orchestration, `69/69` selected и `263/263` fast regression прошли.
- Preflight вернул ожидаемое `postrun_window_not_open` и `no_run_or_output_writes=true`; postrun-папка и owner не созданы.
- Heartbeat `trading-continuous-production` активен и привязан к новым policy/orchestrator/approval hashes.
- Collector, postrun, evaluator, returns/PnL/OOS, grid/retune, paper/live и private API не запускались.
- Следующий шаг: PIT n06, затем уже одобренная 24-часовая dense WS campaign; postrun только после её точного завершения и разрешения guard.
