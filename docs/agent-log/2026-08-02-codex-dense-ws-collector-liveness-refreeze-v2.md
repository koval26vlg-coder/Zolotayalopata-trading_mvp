# Dense WS collector liveness refreeze v2

Date: 2026-08-02 21:45 +03:00

## Result

- Two independent read-only reviews rejected proposal v1 as incomplete.
- Proposal v2 now covers connection silence, exact venue/symbol/channel classification, missing expected markets, control-row inflation, segment boundaries and durable dirty-segment handling.
- Trading hypothesis, venues, universe, signal, costs, risk, 24-hour duration, 25 GB cap, causal materializer and evaluator remain unchanged.
- No production code was changed and no collector was started.

## Fail-closed state

- Old plan hash `57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b` remains suspended.
- Exact old launcher `-PreflightOnly` exits 1 with `policy.candidate.status mismatch`.
- Proposal v1 hash `cb070b3d88b23ff4a1cc46dbd68407d467f4c8ed110ee870d0fd72a5e4e5be3a` is superseded and must not be implemented.
- Current proposal v2 hash is `a3cfdf5e71da1d9485ceb0fe725aab7b35037e9eee4419a3dbb06e97aa7dbd61`.
- A separate exact launch approval will still be required after new immutable code, contract and PlanOnly hashes exist.

## Preserved work

- PIT `pit_universe_v2_forward_20260803_n06` remains preapproved for 01:00-01:20 +03:00 and keeps priority when due.
- Postrun runtime refreeze `0a5884a3599a52e39b6fce438e945743f5bf6bfa2a7cbea779dd0ca54cf40662` remains preserved but dormant until a valid dense campaign completes.

## Next step

Wait only for exact approval of proposal v2, then implement and test the bounded refreeze without network or collector launch.
