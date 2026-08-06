# Visible terminal sandbox handoff

- Exact PIT `PreflightOnly` в обычной tool sandbox упал до любых writes на `Get-CimInstance Win32_Process`: Windows отказал в доступе к CIM.
- Тот же exact `PreflightOnly` с `sandbox_permissions=require_escalated` прошёл: `READY_NOT_DUE`, `12` sealed tools, owners отсутствуют, `NO_RUN_OR_OUTPUT_WRITES`.
- Heartbeat `trading-continuous-production` обновлён через automation API. Actual launcher теперь использует escalation только как Windows permission для process inventory и отдельного видимого terminal.
- Escalation не является новым research approval, не меняет command/plan/hash/scope/gate и не разрешает actual retry после `STOPPED_INCOMPLETE`.
- Automation остаётся `ACTIVE`; TOML SHA-256 `03fabb739eca4947b9d789a1cd7ab207791abaca06cfe88dc239d821982f037e`.
- Frozen policy и launcher files не менялись. Policy SHA-256 остаётся `13c2b98d76a6486eee43b60cf37c07fa2aa2dfbad3479f6c6c5285aff57ba842`.
- Immutable evidence: `docs/agent-log/readiness/visible-terminal-sandbox-permission-handoff-20260802T1918+0300.json`, SHA-256 `1ff1e45af1f8e711d7cda0ec018b6213c4ecb1d66fe48650e0f8653ceacee905`.
- Collector, market-data read/write, returns/PnL/OOS, evaluator, grid/retune, paper/live и private API не запускались.
