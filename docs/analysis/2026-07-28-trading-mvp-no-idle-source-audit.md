# trading_mvp No-Idle Source Audit

## Decision

Do not repeat Gate archive or Tardis probes.

The official Gate historical-data archive is real and already integrated by the
project through `download.gatedata.org`. It was used by the 1h basis-v2 branch.
That branch ended with `INSUFFICIENT_EXECUTABLE_UNIVERSE`: five liquidity
survivors remained against the frozen minimum of eight. Re-downloading the same
archive cannot change that verdict.

The separate Tardis schema probe ended with `REJECTED_SOURCE_SCHEMA` because
`gate-io-futures` did not expose downloadable datasets. It cannot repair the
closed branch without a materially different provider contract.

MEXC account export is personal account/trade history, not a public historical
market-data source. It does not provide the missing cross-venue mark/index
history needed to reopen the frozen basis test.

## Evidence

- Local Gate archive implementation:
  `trading_mvp/src/gate_historical_archive.py`
- Local basis-v2 archive consumer:
  `trading_mvp/src/spot_perp_basis_history_v2_collector.py`
- Tardis terminal probe:
  `E:/ZolotyayLopata-data/exports/trading-mvp/fast-edge-track/probes/gate_momentum_public_schema_94787183_20260728.json`
- Tardis closure:
  `docs/agent-log/2026-07-28-032456-gate-momentum-schema-reject-terminal-verdict.md`
- Gate official historical-data announcement:
  `https://www.gate.com/announcements/article/21688`
- MEXC account export description:
  `https://www.mexc.com/support/article/how-to-use-mexc-s-account-data-export-function-410103096834075648`

## Operational Consequence

- Keep the approved PIT date-accrual track unchanged.
- Run bounded productive fallback work between independent dates.
- Do not rerun historical basis, Gate archive, Tardis, funding, HFT, listing,
  slow-liquidity, or spot-dislocation branches on the same evidence.
- A new market-data provider or a new strategy contract is a critical
  hypothesis checkpoint, not an automatic retry.
