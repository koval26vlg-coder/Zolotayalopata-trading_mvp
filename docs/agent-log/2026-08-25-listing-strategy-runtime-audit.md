# Аудит runtime-стратегий листинга — 2026-08-25

## Итоговый вердикт

Исторические пять строк теперь соответствуют четырём каноническим research-runtime.
`Pre-IPO candidate / Bybit` не является пятой стратегией: это кандидат на расширение
Pre-IPO equity perpetual.

Ни один runtime сейчас не активирован для канонического автоматического сбора и ни одна
стратегия не готова к live trading. Все четыре контура остаются public-data-only,
paper/research-only и fail-closed для authenticated API, ордеров, капитала, плеча и маржи.

## Канонические стратегии

| Стратегия | Биржи и фактическая роль | Как трансформировалась | Подтверждённое состояние данных | Текущий control state | Чего не хватает |
|---|---|---|---|---|---|
| Spot Listing Momentum v2 | MEXC, Gate; discovery и описательное окно первых 72 часов | Идея «купить на первом spot-принте» заменена на causal discovery/first-days accrual; runtime вынесен в отдельный репозиторий | Baseline: 3 790 пар, MEXC 1 708, Gate 2 082. Это bias-control snapshot, не forward-выборка. Новых v2-governed тиков нет | Dedicated `main == origin/main == b77c27c1...`; PlanOnly v2 `AWAIT_GUARD_GREEN_VISIBLE_TICKS`; runtime `INACTIVE`, не routable | Установленный hash-bound registry/router, явная активация и минимум 30 новых полных provenance-bearing окон |
| Spot Listing Momentum expansion v10 | Binance, Bybit, OKX, Bitget; вспомогательный discovery/descriptive слой | После попадания tokenized equities добавлена строгая asset-class provenance; неизвестный актив больше не считается crypto token. v9 запечатал exact bytes, v10 отдельно закрепил remediation CWE-426 без изменения research scope | Legacy/pre-v8: 33 окна, 30 полных, но 0 crypto-eligible. У всех 30 нет asset provenance; 28 OKX относятся к tokenized equities, два полных Bitget остаются unclassified. v10-governed windows = 0 | PlanOnly v10 `READY_FOR_VISIBLE_EXPANSION_TICKS`, hash `911c9024...`; runtime `INACTIVE`, не routable | Положительный registry `venue/base -> CRYPTO_TOKEN`, сквозная provenance, явная активация и новая v10-выборка. Старые 30 окон нельзя переименовать в acceptance evidence |
| Crypto pre-market perpetual capture v27 | Bybit, OKX, Gate; главный контур для входа до spot `t0` и выходов `t0/+5/+15/+60s` | Crypto и equity разделены; official/proxy timestamps разделены; peak-aware exit удалён; capture отделён от replay/исполнения | Dedicated registry содержит 16 metadata-событий: 14 `EQUITY_ISSUER`, 2 `UNCLASSIFIED`, 0 `CRYPTO_TOKEN`. v27 capture не запускался. Исторический main-repo descriptive capture (417 events / 2 429 rows) не является v27 или acceptance evidence | Dedicated branch `codex/premarket-v27-accuracy-20260825`, commit `1a2c68ee...`, не merged в `main`; PlanOnly `REGISTRY_QUARANTINE_HARDENED_NO_CAPTURE`; runtime `INACTIVE` | Настоящий crypto-token event, независимая identity, official spot `t0` точностью не хуже 1 s, новый immutable capture-authorizing PlanOnly и видимый capture-launcher |
| Pre-IPO equity perpetual v11 | Активный venue set в PlanOnly: BitMEX, Gate, Kraken, OKX. Кандидаты: Binance, Bybit, Coinbase International, Crypto.com | Из OKX/Gate + Bybit-candidate стала отдельной equity LONG/SHORT стратегией. Primary `t0` — только official first trade базовой акции; launch/rebase/conversion остаются proxy; rebase value-neutral. v10 запечатал exact bytes, v11 отдельно закрепил remediation CWE-426 | Старый store: 50 377 строк, только OKX, ANTHROPIC/MOONSHOT/OPENAI. В старых строках нет official first-trade и announcement provenance; acceptance-grade official events = 0 | PlanOnly v11 `READY_FOR_BOUNDED_PUBLIC_PAPER_RESEARCH_NOT_SCHEDULER_ACTIVATED`, hash `75ef96b4...`; runtime `INACTIVE`, не routable | Official resolver с URL, announcement timestamp и точным first trade; новые v11-governed events; promotion candidate venues только после всех gates |

## Что не является отдельной стратегией

- `Pre-IPO candidate / Bybit` — candidate venue внутри Pre-IPO, не пятый runtime.
- Немедленная spot-покупка на первом принте — историческая гипотеза без executable runtime.
- Peak-aware выход — удалён как hindsight.
- `listing-event-replay` — описательный инструмент по историческим событиям, не стратегия.
- Tokenized equities из expansion исключены из crypto acceptance и не могут смешиваться с
  crypto-listing sample.
- Main-repo legacy Spot forward monitor v7 — immutable технический rebind старого внутреннего
  runtime, а не пятая стратегия и не замена dedicated Spot v2.

## Состояние автоматизации

- Все три Codex automation (`Listing Momentum`, `Pre-Market Perpetual`, `Pre-IPO`) имеют
  статус `PAUSED`.
- Windows task `ZolotyayLopata Listing Strategy Due Coordinator` включён и находится в
  состоянии `Ready`, но установленная action устарела: содержит retired
  `-CodexAutomationsRoot`, не содержит новых registry/receipt/self SHA bindings и завершает
  wake с `LastTaskResult=2`. Он fail-closed до collector/writer.
- Все четыре runtime в staging registry имеют `INACTIVE`, `scheduler_routable=false`,
  `live_trading_allowed=false`.
- Новый installer/coordinator source закрывает произвольный coordinator override,
  commit/SHA substitution, dirty runtime, junction/symlink alias, validator nonzero,
  partial-runtime success, half-published registry/receipt и подмену самого installer.
  Production task этим source ещё не переустановлен.

## Исправления текущего пакета

- Выпущены immutable Expansion PlanOnly v9/v10 и Pre-IPO PlanOnly v10/v11; все predecessors
  сохранены как committed Git blobs и exact-byte sealed без переписывания их истории.
- Два независимо достижимых CWE-426 из первого security scan устранены: PlanOnly
  validators больше не разрешают PATH-resolved Git, используют только абсолютный
  installation-owned executable и 15-секундный fail-closed timeout.
- Validator запрещает successor timestamp, который не позже predecessor, и проверяет
  одновременно raw worktree SHA и immutable predecessor Git-blob SHA.
- Pre-IPO acceptance требует active venue, official venue URL, announcement timestamp и
  official first-trade timestamp; temporal anchor стал venue-aware.
- Исправлены finite/range проверки процентов, bool-as-int counters, legacy PlanOnly SHA
  validation и terminal rerun fail-closed.
- Все обнаруженные writer/control-plane пути сведены к exact committed trust chain;
  publication registry+receipt стала атомарной и versioned.
- Installer обязан доказать собственный SHA и принадлежность тому же control-plane
  commit до регистрации Scheduled Task.
- PowerShell assertions больше не зависят от terminal line wrapping, не ослабляя product
  fail-closed поведение.

## Верификация

- Более ранний полный offline-suite на baseline пакета: `2 552` теста, `OK`, `7`
  ожидаемых skips, `0` failures/errors, длительность `1 125.387 s`. После финальных
  exact-byte successors не выдаётся за повторный full-suite.
- Финальный focused runtime suite: `59/59`.
- Canonical registry validator: `22/22`; external materializer: `20/20`, один
  ожидаемый skip.
- CWE-426 successor/lineage suite: `47/47`; derivative visible-launcher guards:
  `33/33`; повторная canonical registry/materializer выборка: `41` passed, `1` skip.
- Coordinator failure paths: `49/49`; installer smoke: `12/12`.
- Python `py_compile` и Ruff: clean для всех изменённых Python-файлов.
- PowerShell parser: `8` изменённых/новых скриптов, clean.
- Expansion v10: `PLAN_OK`, plan hash `911c9024c4fc5c6a5c145076e37678b7899944f2e748e6000b9ea7d5e8abf40f`, raw file SHA `0354af66...`.
- Pre-IPO v11: `PLAN_OK`, plan hash `75ef96b4302d0a313ee86c31eb0b3603c06945253ebb2058393501e0476ac4ff`, raw file SHA `93efec13...`.
- Runtime commit: `e56c284b5c3f349378f15e8c7c2f2b7b3670ac9a`; control-plane code commit: `317269f9857af4dc491ac3b9fa545fe74d1ea51a`.
- Staging registry v4 source raw SHA: `cbd1fbb47c8857e7a18b4673c4f7dbda855617fbf24c938af46aa933b1f809fb`; все четыре runtime остаются `INACTIVE` и не routable; external materializer должен перепривязать main-repo entries к окончательному committed HEAD.
- Первый exact-range security scan зафиксировал две medium CWE-426 (Pre-IPO и
  Expansion Git lookup) и не нашёл других concrete regressions. Обе причины устранены
  отдельными immutable successors; публикация требует чистого повторного scan уже
  окончательного remediation commit.
- `git diff --check`: clean. Независимый staged review: `GO`, без merge blockers.

## Следующий безопасный порядок

1. Материализовать внешний versioned registry+receipt из окончательного committed HEAD;
   materializer должен перепривязать main-repo runtimes к этому exact commit.
2. Проверить validator/coordinator/installer только в dry-run; Task Scheduler не менять без
   отдельного разрешения.
3. Активировать по одному runtime через новый `ACTIVE` registry. Discovery/metadata должны
   предшествовать event-window capture.
4. Собирать seconds-grade окна только для exact eligible event и только под новым immutable
   PlanOnly, который явно разрешает visible capture.
5. После достаточного числа official provenance-bearing events выполнить causal replay,
   OOS, walk-forward, stress/economics и paper-forward.
6. Authenticated execution, risk controls и реальные сделки проектируются и разрешаются
   отдельным этапом после acceptance; текущий пакет их не открывает.

Во время аудита не запускались network collector, market-data capture, replay, evaluator,
scheduler registration, authenticated API или торговое исполнение.
