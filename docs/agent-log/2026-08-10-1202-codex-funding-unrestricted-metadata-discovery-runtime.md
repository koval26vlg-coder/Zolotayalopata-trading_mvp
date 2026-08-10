# Funding unrestricted metadata discovery runtime

- Time: 2026-08-10 12:02 +03:00.
- Agent: Codex.
- User request: implement the exact approved MEXC/Gate active-perpetual metadata discovery and permit one visible public read-only run under proposal `0ac65470...0f77`.
- Approval receipt: `docs/agent-log/approvals/2026-08-10-funding-unrestricted-metadata-discovery-v1-approval.json`; receipt hash `d0186ee9...f18b`.
- Added a standard-library-only runtime that disables environment proxies, permits only the two frozen GET endpoints, caps attempts at two per endpoint and four requests total, and never writes raw responses, funding rates or prices.
- Added fail-closed projection for active MEXC/Gate USDT perpetual metadata. Coin/category/top-N/Binance filters are absent. Shared ticker matches remain `UNRESOLVED_TICKER_MATCH_ONLY` and are not identity evidence.
- Added immutable four-file output, 300-second limit, 50 MB cap, exact proposal/receipt/runtime bindings and a minimum completeness guard of 50 active contracts per venue.
- Added the top-level visible launcher `tools/start_funding_unrestricted_metadata_discovery_visible.ps1` with an atomic launch record, one global writer claim, duplicate-owner rejection, visible `-NoExit` PowerShell and terminal `STOPPED_INCOMPLETE` no-retry behavior.
- Runtime manifest: `docs/plans/funding-unrestricted-metadata-discovery-runtime-manifest-20260810-v1.json`; manifest hash `da070dc3...f7e58`.
- TDD red state was confirmed before the runtime existed. Targeted synthetic tests pass 10/10; all funding tests pass 92/92; Ruff, `py_compile`, PowerShell parse, canonical hash checks and `git diff --check` pass.
- Latest `-PreflightOnly`: `READY_FOR_VISIBLE_SINGLE_USE`, guard `ACTIVE`, weekly remaining 51%, active gate `READY_FOR_POSTPROCESS`, no global writer, immutable output absent, HTTP requests made 0.
- No network request, collector, evaluator, OOS read, returns/PnL, grid/retune, execution probe, live/private action, capital, leverage or margin occurred during implementation.
- Next: commit and push these exact files, rerun fresh preflight, then invoke the approved top-level visible launcher once. After discovery, stop at a separate exact identity-verified candidate PlanOnly checkpoint.
