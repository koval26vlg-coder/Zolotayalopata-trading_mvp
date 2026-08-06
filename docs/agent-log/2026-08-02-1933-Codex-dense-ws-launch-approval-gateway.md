# Dense WS exact approval gateway

## Простое объяснение

У старого стартового скрипта была кнопка `ConfirmedLongCampaign`. Он проверял план и защитный статус, но сам не открывал и не сверял файл пользовательского разрешения. Простая передача этой кнопки была слабым местом.

Старый скрипт нельзя менять: его точный хеш уже записан в утвержденном PlanOnly. Поэтому перед ним поставлен новый внешний шлюз. Шлюз сначала сверяет guard, policy, PlanOnly, квитанцию разрешения, расписание, лимиты и все хеши. Только после полного совпадения он передает старому скрипту внутренний флаг подтверждения.

## Что изменено

- Добавлен `tools\start_exact_approved_dense_ws_campaign_visible.ps1`.
- SHA256 шлюза: `231a08cb55b47499f58906b1f164a760da1e065d60eb03ed0a823f6d8e50dcd0`.
- Heartbeat `trading-continuous-production` переведен на новый шлюз и запрещает прямой actual-вызов старого launcher.
- Старый launcher, PlanOnly, runner, quality и materializer не изменены.

## Проверка

- PowerShell parse: 0 ошибок.
- Тесты шлюза: 9/9.
- Настоящий `PreflightOnly`: `EXACT_APPROVAL_VALIDATED_PREFLIGHT_ONLY`.
- Внутренний preflight: `STRUCTURALLY_VALID_NOT_DUE`.
- Writer, postrun и evaluator не запускались; рыночные данные, returns/PnL/OOS не читались.

## Evidence

`docs\agent-log\readiness\dense-ws-launch-approval-gateway-audit-20260802T1933+0300.json`
