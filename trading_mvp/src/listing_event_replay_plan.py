"""The replay contract the normalizer asked for, with the costs the 2026-07-08 plan set.

On 2026-07-09 the normalizer finished and named its successor exactly:
``implement_read_only_listing_event_replay_planonly_no_grid_no_live``. The replay module
was written the next day; this plan never was, and the chain has been stopped there ever
since. Two things had to be faced before it could be written honestly, and both are
recorded here rather than smoothed over.

**The module's costs contradict the pre-registered ones.** The drift-reversal PlanOnly of
2026-07-08 - issued *before* any history was collected - fixed round_trip_fee_bps 39.0 and
entry_exit_slippage_bps 30.0, and stated: "base/VIP0/no-volume only; do not accept
lower-cost sensitivity as proof". The module defaults to 10.0 and 5.0 per side, so
``cost_bps = 2*(10+5) = 30`` where the contract requires 69 - and its stress case, 50 bps,
is still cheaper than the contract's normal case. This plan therefore freezes
fee_bps_per_side at 19.5 and slippage_bps_per_side at 15.0, reproducing the contract's
39 + 30, and does not use the module's defaults. A run under these costs may show a loss
where the defaults would have shown a profit; that difference is the point.

**Most parameters were chosen after the data existed.** The history was collected
2026-07-09; the module, and with it hold_hours, entry_delay_hours and the gates, dates
from 2026-07-10. Nothing in the artifacts establishes whether they were tuned on this
sample, and a plan that called them pre-registered would be pre-registration theatre.
Only trigger_bps has an anchor: 200 exceeds the minimum_gross_move_hurdle_bps of 174 that
the 2026-07-08 plan set before collection. So the parameters are split by provenance -
``contract_anchored`` versus ``chosen_after_data`` - and the result is declared
descriptive: it cannot accept a strategy, cannot authorise paper forward, and cannot
authorise live trading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from listing_event_replay import ReplayConfig

SCHEMA = "trading_mvp_listing_event_replay_planonly_v1"
PLAN_ID = "listing_event_replay_20260825_v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "docs/plans" / "listing-event-replay-planonly-20260825-v1.json"
NORMALIZER_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "listing_event_normalizer_planonly_20260709_094518.json"
)
COST_CONTRACT_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "listing_event_drift_reversal_planonly_20260708_184450.json"
)
REPLAY_MODULE_PATH = REPO_ROOT / "trading_mvp/src/listing_event_replay.py"
EVALUATION_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "listing_event_replay_20260825_v1.json"
)

# The 2026-07-08 contract expressed cost as a round trip; the module takes it per side.
CONTRACT_ROUND_TRIP_FEE_BPS = 39.0
CONTRACT_ROUND_TRIP_SLIPPAGE_BPS = 30.0
CONTRACT_MIN_GROSS_MOVE_HURDLE_BPS = 174.0

# Frozen here, not taken from the module: ReplayConfig's defaults are the cheaper set.
FROZEN_CONFIG = ReplayConfig(
    fee_bps_per_side=CONTRACT_ROUND_TRIP_FEE_BPS / 2.0,
    slippage_bps_per_side=CONTRACT_ROUND_TRIP_SLIPPAGE_BPS / 2.0,
)

PARAMETER_PROVENANCE: dict[str, str] = {
    # Anchored: 200 bps clears the 174 bps hurdle the pre-collection plan declared.
    "trigger_bps": "contract_anchored",
    # Derived from the 2026-07-08 cost contract, not from the module defaults.
    "fee_bps_per_side": "contract_anchored",
    "slippage_bps_per_side": "contract_anchored",
    # Everything below dates from 2026-07-10, after the 2026-07-09 collection.
    "notional_quote": "chosen_after_data",
    "entry_delay_hours": "chosen_after_data",
    "hold_hours": "chosen_after_data",
    "stress_fee_multiplier": "chosen_after_data",
    "stress_slippage_multiplier": "chosen_after_data",
    "stress_haircut_bps": "chosen_after_data",
    "min_trades": "chosen_after_data",
    "min_oos_trades": "chosen_after_data",
    "min_profit_factor": "chosen_after_data",
    "min_walk_forward_pass_ratio": "chosen_after_data",
    "walk_forward_windows": "chosen_after_data",
    "train_fraction": "chosen_after_data",
}


class ListingEventReplayPlanError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingEventReplayPlanError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash_without(payload: Mapping[str, Any], excluded: str) -> str:
    body = {k: v for k, v in payload.items() if k != excluded}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def frozen_cost_bps() -> float:
    """The round-trip cost this plan applies, as the module would compute it."""
    return 2.0 * (FROZEN_CONFIG.fee_bps_per_side + FROZEN_CONFIG.slippage_bps_per_side)


def build_plan(generated_at_utc: str) -> dict[str, Any]:
    _require(NORMALIZER_PATH.is_file(), f"normalizer artifact missing: {NORMALIZER_PATH}")
    _require(COST_CONTRACT_PATH.is_file(), f"cost contract missing: {COST_CONTRACT_PATH}")
    normalizer = json.loads(NORMALIZER_PATH.read_text(encoding="utf-8"))
    _require(
        normalizer.get("decision")
        == "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY",
        "normalizer artifact is not the one that asked for this plan",
    )
    coverage = normalizer.get("history_coverage") or {}

    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "PREREGISTERED_DESCRIPTIVE_REPLAY",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "network_authorized": False,
        "private_api": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "grid_search_allowed": False,
        "objective": (
            "Replay the accepted 36-event listing history read-only, under the costs the "
            "2026-07-08 plan fixed before any data was collected, and report the result "
            "as descriptive evidence only."
        ),
        "cost_contract": {
            "source_path": str(COST_CONTRACT_PATH),
            "source_file_sha256": _sha256_file(COST_CONTRACT_PATH),
            "round_trip_fee_bps": CONTRACT_ROUND_TRIP_FEE_BPS,
            "round_trip_slippage_bps": CONTRACT_ROUND_TRIP_SLIPPAGE_BPS,
            "applied_round_trip_cost_bps": frozen_cost_bps(),
            "module_default_round_trip_cost_bps": 30.0,
            "policy": (
                "base/VIP0/no-volume only; do not accept lower-cost sensitivity as proof"
            ),
            "note": (
                "The module defaults to 10.0 fee and 5.0 slippage per side, giving 30 bps "
                "round trip where the contract requires 69, and its stress case of 50 bps "
                "is still cheaper than the contract's normal case. This plan overrides "
                "those defaults rather than inheriting them."
            ),
        },
        "frozen_parameters": {
            name: getattr(FROZEN_CONFIG, name) for name in PARAMETER_PROVENANCE
        },
        "parameter_provenance": dict(PARAMETER_PROVENANCE),
        "preregistration_honesty": {
            "history_collected_at": "2026-07-09",
            "module_written_at": "2026-07-10",
            "consequence": (
                "Every parameter marked chosen_after_data was fixed after the sample "
                "existed. Nothing in the artifacts establishes whether it was tuned on "
                "that sample, so this replay is descriptive and its result may not be "
                "cited as a pre-registered out-of-sample verdict."
            ),
            "contract_anchored_basis": (
                "trigger_bps 200 exceeds minimum_gross_move_hurdle_bps 174, declared "
                "2026-07-08 before collection; the two cost terms reproduce that plan's "
                "39 and 30 bps round trip."
            ),
        },
        "history_coverage": {
            "min_history_events": coverage.get("min_history_events"),
            "ok_events": coverage.get("ok_events"),
            "ok_unique_bases": coverage.get("ok_unique_bases"),
            "ok_exchange_count": coverage.get("ok_exchange_count"),
            "ok_events_by_exchange": coverage.get("ok_events_by_exchange"),
            "max_single_exchange_event_fraction": coverage.get(
                "max_single_exchange_event_fraction"
            ),
        },
        "acceptance_policy": {
            "acceptance_decision": "NONE_DESCRIPTIVE_ONLY",
            "replay_authorizes": False,
            "paper_forward_authorized": False,
            "live_trading_authorized": False,
            "note": (
                "A descriptive replay cannot accept a strategy, cannot authorise paper "
                "forward execution, and cannot authorise live trading. The module does "
                "compute a chronological train/test split, walk-forward and stress, but "
                "computing those stages is not the same as passing them under a contract "
                "fixed before the data."
            ),
        },
        "source_bindings": {
            "normalizer": {
                "path": str(NORMALIZER_PATH),
                "file_sha256": _sha256_file(NORMALIZER_PATH),
                "decision": normalizer.get("decision"),
                "required_next_step": normalizer.get("required_next_step"),
            }
        },
        "implementation": {
            "files": [
                {
                    "role": "replay_engine",
                    "path": str(REPLAY_MODULE_PATH),
                    "sha256": _sha256_file(REPLAY_MODULE_PATH),
                },
                {
                    "role": "replay_plan",
                    "path": str(Path(__file__).resolve()),
                    "sha256": _sha256_file(Path(__file__).resolve()),
                },
            ]
        },
        "forbidden": [
            "live orders",
            "real capital",
            "private api",
            "grid search over the frozen parameters",
            "re-running with cheaper costs and reporting the better result",
        ],
    }
    plan["plan_hash"] = _canonical_hash_without(plan, "plan_hash")
    return plan


def validate_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "schema")
    _require(plan.get("plan_id") == PLAN_ID, "plan id")
    _require(plan.get("mode") == "PlanOnly", "mode")
    for flag in ("research_only", "public_data_only"):
        _require(plan.get(flag) is True, flag)
    for flag in ("private_api", "live_orders", "real_capital", "grid_search_allowed"):
        _require(plan.get(flag) is False, flag)

    costs = plan.get("cost_contract") or {}
    _require(
        costs.get("round_trip_fee_bps") == CONTRACT_ROUND_TRIP_FEE_BPS
        and costs.get("round_trip_slippage_bps") == CONTRACT_ROUND_TRIP_SLIPPAGE_BPS,
        "cost contract must reproduce the 2026-07-08 terms",
    )
    applied = costs.get("applied_round_trip_cost_bps")
    _require(
        applied == CONTRACT_ROUND_TRIP_FEE_BPS + CONTRACT_ROUND_TRIP_SLIPPAGE_BPS,
        "applied cost must equal the contract round trip, not the module default",
    )
    _require(
        applied > costs.get("module_default_round_trip_cost_bps", 0),
        "a plan that applied the cheaper module default would be the thing the "
        "2026-07-08 policy refuses",
    )

    frozen = plan.get("frozen_parameters") or {}
    provenance = plan.get("parameter_provenance") or {}
    _require(set(frozen) == set(provenance), "every frozen parameter needs a provenance")
    _require(
        all(v in {"contract_anchored", "chosen_after_data"} for v in provenance.values()),
        "provenance must be contract_anchored or chosen_after_data",
    )
    _require(
        frozen.get("fee_bps_per_side") == CONTRACT_ROUND_TRIP_FEE_BPS / 2.0
        and frozen.get("slippage_bps_per_side") == CONTRACT_ROUND_TRIP_SLIPPAGE_BPS / 2.0,
        "frozen costs must be the contract's, per side",
    )
    _require(
        frozen.get("trigger_bps", 0) >= CONTRACT_MIN_GROSS_MOVE_HURDLE_BPS,
        "trigger must clear the pre-registered minimum gross move hurdle",
    )

    acceptance = plan.get("acceptance_policy") or {}
    for key in ("replay_authorizes", "paper_forward_authorized", "live_trading_authorized"):
        _require(acceptance.get(key) is False, f"{key} must be False")

    _require(
        plan.get("plan_hash") == _canonical_hash_without(plan, "plan_hash"), "plan hash"
    )
    for row in (plan.get("implementation") or {}).get("files") or []:
        path = Path(str(row.get("path") or ""))
        _require(path.is_file(), f"implementation missing: {row.get('role')}")
        _require(row.get("sha256") == _sha256_file(path), f"sha256: {row.get('role')}")


def write_plan(generated_at_utc: str) -> Path:
    plan = build_plan(generated_at_utc)
    validate_plan(plan)
    if PLAN_PATH.exists():
        raise ListingEventReplayPlanError(f"refusing to overwrite: {PLAN_PATH}")
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return PLAN_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-register the read-only listing-event replay contract"
    )
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args(argv)
    if not args.write_plan:
        raise SystemExit("no authorized action requested")
    if not args.generated_at_utc:
        raise SystemExit("--generated-at-utc is required")
    path = write_plan(args.generated_at_utc)
    plan = json.loads(path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": "PLAN_WRITTEN",
                "path": str(path),
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "applied_round_trip_cost_bps": plan["cost_contract"][
                    "applied_round_trip_cost_bps"
                ],
                "module_default_round_trip_cost_bps": plan["cost_contract"][
                    "module_default_round_trip_cost_bps"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
