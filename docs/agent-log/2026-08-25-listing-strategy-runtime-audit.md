# Listing strategy runtime audit — 2026-08-25

## Verdict

The historical five-track description now maps to four canonical research runtimes. The old
`Pre-IPO candidate / Bybit` row is a venue-promotion backlog, not an independent strategy.
None of the four runtimes is currently performing canonical automated collection.

All runtimes remain public-data-only and paper/research-only. The live-readiness gate is
fail-closed and cannot authorize authenticated APIs, orders, leverage, margin, capital, or
execution.

## Canonical runtimes

| Runtime | Venues | Current evidence | Current control state | Blocking work |
|---|---|---|---|---|
| Spot Listing Momentum v2 | MEXC, Gate | Dedicated repository is clean at `b77c27c1b4cc84db2828d4da8049aa251b8a5bef`; canonical status `NO_TICKS_YET`. Old main-repository data is descriptive legacy evidence only. | Registry binding matches, but the runtime is `INACTIVE_NOT_ROUTABLE`; Codex automation is paused. | Activate the dedicated runtime through an ACTIVE canonical registry, then accrue new v2-governed windows. |
| Spot Listing Momentum expansion v8 | Binance, Bybit, OKX, Bitget | Persisted v5 state reports 30 complete windows, but 0/30 are crypto-eligible. All 30 lack asset provenance; 28 are declared OKX tokenized equities. | v8/v4 PlanOnly checks pass, but registry binding is staged/uncommitted and the runtime is inactive. | Populate an exact venue/base crypto registry and collect at least 30 provenance-bearing crypto windows under v8. Legacy v5 windows cannot be relabelled as acceptance evidence. |
| Crypto pre-market perpetual capture v26 | Bybit, OKX, Gate discovery universe | Dedicated repository is clean at `7dd22426db7fb35b18a0efdecf3655c1e605d3a0`; registry contains 16 metadata-only rows: 14 equity issuers, 2 unclassified, 0 crypto tokens. | `REGISTRY_QUARANTINE_HARDENED_NO_CAPTURE`; registry binding matches but runtime is inactive; Codex automation is paused. | Admit a genuine `CRYPTO_TOKEN` event with independent identity and seconds-grade official spot `t0`, then issue a new immutable PlanOnly that explicitly authorizes visible market-data capture. |
| Pre-IPO equity perpetual event v8 | Active: BitMEX, Gate, Kraken, OKX. Candidates: Bybit, Coinbase International, Crypto.com. | Existing store has 50,377 rows and 3 OKX contracts, but it was collected under old v3/proxy rules; complete official events = 0. | Persisted status is `RETRY_NEXT_INTERVAL`, but the Codex automation is paused. v8 is structurally `PLAN_OK` yet semantically not scheduler/acceptance-ready. | Issue immutable v9: declare the real scope change, preregister BitMEX/Kraken sources, bind `official_first_trade_ts` into equity cadence, and define promotion rules for all candidate venues. Then accrue new v9-governed official events. |

## Transformations and retired concepts

- The original attempt to buy spot at the first listing print and sell immediately was not
  retained as an executable strategy. Spot tracks now serve discovery and descriptive
  first-days evidence; they do not prove first-seconds fillability.
- The practical first-seconds hypothesis moved to crypto pre-market perpetual: enter before
  spot `t0`, then test fixed causal exits at `t0`, `+5s`, `+15s`, and `+60s`.
- Peak-aware exits were removed because they require hindsight.
- Pre-IPO is a separate equity-event LONG/SHORT strategy. Rebase is value-neutral accounting,
  not automatic profit. It must never be pooled with crypto-listing evidence.
- Bybit Pre-IPO was folded into `candidate_venues`; it is not a fifth runtime.

## Automation truth

- Codex automations for Listing Momentum, crypto pre-market, and Pre-IPO are all `PAUSED`.
- Windows task `ZolotyayLopata Listing Strategy Due Coordinator` is enabled, but its installed
  action still uses the retired `-CodexAutomationsRoot` argument and omits registry/self hashes.
  Its last result was `2`; it fails closed before any collector or writer work.
- Source installer now computes and pins the raw registry/coordinator hashes, performs a
  read-only `STAGED_FAIL_CLOSED / NOT_ACTIVATED` preflight, and emits no legacy production
  path override. The installed task was not changed during this audit.
- The checked-in staging registry is a fail-closed declarative source, not an installed trust
  root. Its current decision is `PARTIAL_RUNTIME_BLOCK`, `launch_allowed=false`. MEXC/Gate and
  crypto pre-market bindings match but are deliberately inactive. After the final code commit,
  a binding-complete candidate must be regenerated from committed files and stored outside all
  canonical repositories; otherwise embedding the current repo commit SHA would create an
  impossible self-reference.

## Verification

- Offline focused suites: 137/137 canonical/live/premarket tests, 92/92 expansion tests,
  122/122 Pre-IPO/derivative tests, and 94/94 tests rerun after lint cleanup.
- PowerShell coordinator/installer: 45/45. Registry preflight: 5/5.
- Python compile and Ruff checks pass for all changed source and focused test files.
- Expansion monitor v8, expansion evaluator v4, and Pre-IPO v8 all pass structural PlanOnly
  validation. Structural `PLAN_OK` is not an acceptance or activation verdict.
- `git diff --check` passes; only repository line-ending conversion warnings remain.
- The last full suite before the final lint-only cleanup ran 2,498 tests and exposed one
  package regression plus pre-existing/environment-bound failures. The package regression was
  fixed. Twelve failures and five errors remain outside this package: missing external identity
  fixtures, committed weekly-usage/readiness inconsistencies, and older PlanOnly/global-writer
  SHA drift. Therefore the repository-wide suite is not claimed globally green.

## Next safe order

1. Commit this fail-closed staging checkpoint and regenerate an external canonical-registry
   candidate against the committed Git object identities. Do not commit the generated trust-root
   bytes back into a canonical runtime repository.
2. Replace Pre-IPO v8 with immutable v9 and keep v8 as a non-acceptance development artifact.
3. Reinstall the Windows coordinator task only after explicit scheduler-mutation authorization;
   its first production outcome must still be `STAGED_FAIL_CLOSED / NOT_ACTIVATED`.
4. Promote one runtime at a time through an ACTIVE registry. Discovery/metadata comes before
   event-window capture.
5. Capture seconds-grade event windows only when an exact eligible event exists and the relevant
   immutable PlanOnly explicitly authorizes visible capture.
6. Run causal replay and acceptance gates only after sufficient official, provenance-bearing
   samples exist. Keep live readiness separate and blocked.

No network collector, registry refresh, market-data capture, replay, evaluator, scheduler
registration, authenticated API, or trade execution was run during this audit.
