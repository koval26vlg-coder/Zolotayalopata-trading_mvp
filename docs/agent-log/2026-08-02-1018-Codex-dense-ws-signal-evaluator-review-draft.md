# Dense WS signal/evaluator review draft

- Observed at: `2026-08-02T10:18:00+03:00`
- Scope: bounded local PlanOnly preparation before the approved AEF campaign window.
- No campaign output, market returns, PnL, OOS, replay, grid, retune, paper-forward, live/private API, real-capital, leverage, or margin data/action was used.

## Prepared review artifact

- Draft: `docs/plans/drafts/dense-ws-signal-evaluator-review-draft-20260802-v1.json`
- Draft file SHA-256: `c3f7e1e95721adeb004a9c0ace83c94f1e756fe737a4aa31e6c77171c00526e3`
- Deterministic draft hash: `9325445a68aea9f8224658690367862662c342fc8f624a824f4c805d9c293573`
- Status: `DRAFT_NOT_FROZEN_NOT_AUTHORIZED`
- Bound campaign PlanOnly hash: `57231016ac62e79bcbef54c71ba059b330d08254683c3334ed6ae5de40335a8b`
- Next action remains `USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT`.

The draft reuses one existing cross-venue dislocation formula only inside
causal `DENSE_BOTH` snapshots. It freezes two directions, opposite-top-of-book
prices, $50 minimum executable capacity, 60-second base/direction cooldown,
69/89 bps normal/stress costs, one parameter combination, and the existing
70/30 chronological split plus 300-second embargo. Acceptance thresholds remain
explicitly unset and cannot authorize evaluation.

## Implementation and verification

- Builder/validator: `trading_mvp/src/dense_ws_signal_evaluator_contract.py`
- Builder SHA-256: `f1d6c7901ff613622717d8bf04928745200d2fdc03ad2a5562171fa0df829d8d`
- Tests: `trading_mvp/tests/test_dense_ws_signal_evaluator_contract.py`
- Tests SHA-256: `cdd76913d6fec48e1eb1e99e52b08b7f3facb507acd822b300ed666fc386886b`
- TDD red phase confirmed the missing module, then confirmed semantic gaps for hidden risk/unknown-field tampering before fixes.
- Targeted suite: `8/8` passed.
- Linked campaign/materializer/guard suite: `85/85` passed.
- Ruff `0.14.0`: clean for both new Python files.
- Real source-bound CLI validation: `VALID_REVIEW_DRAFT_NOT_AUTHORIZED`.

## Runtime state after work

- Guard: `ACTIVE`, decision `WAIT_APPROVED_LONG_CAMPAIGN_WINDOW`.
- Weekly remaining: `80%`.
- No active global writer claim.
- PIT n06 remains `WAITING` for `2026-08-03T01:00:00+03:00`.
- Long campaign approval remains `APPROVED`; its window is not due yet.
- Heartbeat remains `ACTIVE` and bound to the exact approval receipt.

## Boundary

This artifact is only a pre-registration review draft. It cannot become a
frozen evaluator contract, cannot bind future materialization outputs, and
cannot read returns/PnL/OOS without the later exact critical review.
