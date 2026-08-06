# Dense WS postrun runtime refreeze: PlanOnly proposal

- Время: 2026-08-02 13:17 +03:00
- Агент: Codex
- Кампания: `dense_ws_microstructure_regime_filter_v1_20260803_aef_24h`
- Campaign PlanOnly hash: `57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b`

## Что подготовлено

Создан только неизменяемый неисполняемый план исправления короткого postrun-лимита. Код, policy и collector не менялись.

Предлагаемый postrun:

1. Не начинать раньше завершения writer: 04.08.2026 01:30 +03:00.
2. Проверка качества: не более 1800 секунд.
3. Причинная materialization: не более 1800 секунд и только после quality PASS.
4. Общий предел: 3600 секунд.
5. Жесткое окончание postrun: 04.08.2026 02:30 +03:00.
6. Один видимый терминал и один owner; timeout или сбой не повторять без нового точного разрешения.

Разрешение не меняет длительность, PlanOnly, venue, universe, signal, cost или risk контракты collector. Оно не разрешает evaluator, returns, PnL, OOS, grid, retune, paper/live или private API.

## Hash binding

- Proposal: `docs/plans/drafts/dense-ws-postrun-runtime-refreeze-proposal-20260802-v1.json`
- Proposal hash: `0a5884a3599a52e39b6fce438e945743f5bf6bfa2a7cbea779dd0ca54cf40662`
- Proposal file SHA-256: `eef9fdee67a9dbcd23c9c66c62869ef2a041b43525306cb70c0f94fbaf88e380`
- Source calibration SHA-256: `0807cbe05706b6aa51d644d92e3d69ae4153641b0e96497d68cc01d0342fd30e`
- Canonical hash recomputation: PASS.

## Exact approval packet

`Разрешаю runtime-refreeze only по proposal_hash=0a5884a3599a52e39b6fce438e945743f5bf6bfa2a7cbea779dd0ca54cf40662 для dense_ws postrun: один видимый последовательный pipeline, quality MaxRuntimeSec=1800, causal materialization MaxRuntimeSec=1800, общий MaxRuntimeSec=3600, postrun не раньше 04.08.2026 01:30 +03:00 и hard deadline 04.08.2026 02:30 +03:00; collector PlanOnly/длительность, venue/universe/signal/cost/risk и quality/materializer code не менять; без evaluator/returns/PnL/OOS/grid/retune/paper/live/private API/real capital/leverage/margin; STOPPED_INCOMPLETE не retry без нового точного разрешения.`

## Следующий шаг

После точного ответа пользователя изменить только перечисленный в proposal operational scope, запустить targeted tests и fast regression, записать новые хеши, затем снять только postrun-предохранитель heartbeat. Ночной PIT и утвержденный collector продолжаются независимо.
