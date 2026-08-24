# Pre-Market Perpetual Listing Impulse v1

## Запрос

Выделить отдельный research-only futures-трек для проверки paper LONG на pre-market perpetual до spot-листинга, с causal fill, event-relative exits и recovery на следующий интервал. Spot Listing Momentum universe и его PlanOnly не изменяются.

## Реализовано

- Immutable PlanOnly: `docs/plans/premarket-perp-listing-impulse-planonly-20260818-v1.json`.
- Venue scope: Bybit, OKX, Gate; public REST и bounded public WebSocket; private API, ключи, реальные ордера, real capital, leverage/margin execution запрещены.
- Lifecycle: scheduled, call_auction, continuous, spot_listing_pending, transitioned, cancelled, delisted, expired.
- Official/proxy source separation и отдельные exchange/received/announcement/official listing/transition timestamps.
- Нормализация BBO/depth/trades/mark/index/funding/open-interest/price limits и сопоставление pre-market contract ↔ spot symbol.
- Causal replay для cohorts `first_tradable` и `last_1_4h`, exits `t0`, `t0+5s`, `t0+15s`, `t0+60s`; peak-aware hindsight запрещён.
- Paper notional 25 USDT, 1x primary, 2x/5x liquidation stress; taker-like primary cost; existing `ws_replay` `ReplayConfig` semantics для latency, fee/slippage, maker queue и TTL sensitivity.
- Atomic latest manifest с event-file SHA-256; append-only attempts ledger и state recovery `RETRY_NEXT_INTERVAL` / `PARTIAL_RETRY_NEXT_INTERVAL`.
- Visible PowerShell orchestrator с worker-owned claim: duplicate worker возвращает `ALREADY_RUNNING`, claim держится до выхода visible worker.

## Automation

Зарегистрирована отдельная app automation: `zolotyaylopata-pre-market-perpetual-listing-impulse-monitor`, active cron с интервалом 5 минут, project `ZolotyayLopata`. Она запускает только `tools/start_premarket_perp_listing_automation_visible.ps1 -ScheduledTick -Json` и не трогает spot automation.

## Проверки

- `PLAN_OK`; plan hash `920115ec57c9e200e892c9edad3850b3f766888f838b0674f9fce5a86014fc15`.
- PowerShell parser: `PS_PARSE_OK`.
- `py_compile` для трёх новых Python-модулей.
- Targeted + regression tests: `24 passed` (`test_premarket_perp.py`, `test_perp_collector.py`, `test_perp_replay.py`).
- Fresh preflight: `ok=true`, gate `READY_FOR_POSTPROCESS`, cadence 300 sec.
- Первый hash-bound recovery после refreeze: visible worker завершился `COMPLETE`, 36 контрактов, 258 events written, `pending_retry=false`; complete listing events пока 0, acceptance не заявляется.
- Последующий scheduled fire попал в короткое окно очередного hash rebind и записал `RETRY_NEXT_INTERVAL` с сохранёнными 36/258; текущий PlanOnly снова `PLAN_OK`, worker мёртв, venue остаются в очереди следующего 5-минутного интервала.

## Official t0 resolver / materializer bounded batch

- Добавлен `trading_mvp/src/premarket_listing_resolver.py`: fixture-driven parser для официальных Bybit/OKX/Gate announcement payloads/body, строгая проверка HTTPS official host, явный `official_spot_listing_ts`, отдельный `announcement_ts`, contract/pair aliases, source URL и confidence.
- Publish/announcement time не используется как `t0`; `launchTime`, polling/received time и ellipsis/placeholder timestamp отклоняются. Одноразовый `fetch_public_announcement` принимает только caller-supplied official URL, без discovery/pagination/фонового worker, с redirect/size/timeout guard.
- `resolve_contract_listing` даёт только `official`, `proxy_only`, `ambiguous` или `unresolved`; proxy detection никогда не получает official `t0` и `acceptance_eligible`.
- `materialize_premarket_events` пишет атомарный отдельный JSONL, не меняет raw store, сортирует announcement candidates детерминированно и возвращает raw/output/result hashes.
- Локальный baseline materialization raw store с пустым official-announcement набором: `2429` строк, `matched_official=0`, `proxy_only=0`, `ambiguous=0`, `unresolved=2429`; output `exports/trading-mvp/premarket-perp/materialized_events.jsonl`, output SHA `3c54cfc392e004035ccb63f23983c55782750cf2e17801247351ac632b641c57`, result hash `fe61a6f7bb3f317cf9fccab88ea103d99c1e1a93f3ad3b7332eedd2154506b30`.
- PlanOnly rebind: resolver/materializer binding SHA `6e3675da7ac03b0f1535b15680d7fb0d96bf91123cd44ee2937f9f63182ee637`; plan hash `920915b4f427fc23611b4c4eb503f641d0035c753b36563c69b5249fcd3204f2`; plan file SHA `56d20a272ec78ead22caae5d56aadf221bcf5db74664a8060673a183e7d12b4e`; `PLAN_OK`.
- TDD/regression verification after final rebind: combined resolver + premarket + perp collector/replay suite `33 passed`; Python compile, PowerShell parser and `PLAN_OK` all green. No new network announcement fetch, replay, or manual futures tick was started.
- Между первой правкой binding и финальной записью hash scheduled fire попал в короткое окно `PLACEHOLDER_RECOMPUTE` и корректно записал `RETRY_NEXT_INTERVAL` (`plan_check_failed:plan_hash_mismatch`, attempt `deferred_20260818T092544Z`); state сохранён, worker мёртв, следующий интервал `2026-08-18T09:30:44Z` оставлен для автоматического retry. Текущий plan-файл уже `PLAN_OK`, поэтому state не очищался вручную.

## Ограничения

Официальный spot-listing timestamp не присутствует в каждом public instrument payload; такие записи остаются descriptive/proxy/incomplete и не могут самостоятельно поддержать acceptance. Требуется накопить минимум 30 independent complete official events, затем OOS/walk-forward/stress/economics проекта. Длинный ручной collector отдельно не запускался; tick выполняется только зарегистрированной visible automation.
