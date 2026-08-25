"""Pre-registered evaluation contract for the exchange-expansion forward sample.

The expansion monitor's plan says it plainly: "A separate evaluator plan is required
after enough complete windows accrue." As of 2026-08-25 the expansion state carries 30
complete windows, which is exactly the pre-registered first-read minimum, so that
condition is met and this is the plan it asks for.

It deliberately does NOT restate the metrics. The computation, and above all the peeking
guard that refuses to produce any metric below the pre-registered minimum, are imported
from the forward evaluator, so the two tracks cannot drift into computing different
things and calling both a "read". Only the bindings differ: this module names the
expansion state and the expansion monitor plan.

One check exists here that the forward evaluator does not need. The expansion state
records which plan version produced it, and that plan has been reissued several times.
Evaluating a state collected under one plan while binding a different one would attach a
verdict to a contract that did not govern the collection, so the two must agree and this
module refuses when they do not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_listing_momentum_forward_evaluator import (
    FIRST_READ_MIN_COMPLETE_WINDOWS,
    HOLD_BARS,
    NORMAL_COST_BPS,
    STRESS_COST_BPS,
    TERMINAL_MIN_COMPLETE_WINDOWS,
    ForwardEvaluatorError,
    _canonical_hash_without,
    _require,
    _sha256_file,
    _validated_state_hash,
    evaluate_forward_state,
)

SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_evaluator_planonly_v1"
PLAN_ID = "slow_liquidity_listing_momentum_forward_expansion_evaluator_20260825"
EVALUATION_CLASS = "PROXY_DATE_FORWARD_EXPANSION_PREREGISTERED"
EVALUATION_SCHEMA = (
    "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_evaluation_v1"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-expansion-evaluator-planonly-20260825.json"
)
EXPANSION_STATE_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_expansion_state_20260817.json"
)
EXPANSION_MONITOR_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-expansion-planonly-20260825-v5.json"
)
EVALUATION_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_expansion_evaluation_20260825.json"
)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file(), f"{label} missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"{label} is not an object")
    return payload


def _require_state_matches_bound_plan(
    state: Mapping[str, Any], monitor_plan: Mapping[str, Any]
) -> None:
    """The state must have been collected under the plan this evaluation binds.

    Without this the read could be attached to a contract that never governed the
    collection - which is the same class of error as citing a plan whose bytes have
    since moved."""
    recorded = str(state.get("monitor") or "")
    bound = str(monitor_plan.get("plan_id") or "")
    _require(
        recorded == bound,
        "expansion state was collected under "
        f"{recorded or '<none>'} but this evaluation binds {bound or '<none>'}; "
        "re-run the expansion monitor under the bound plan before evaluating",
    )


def _build_input_binding(
    state: Mapping[str, Any],
    evaluator_plan: Mapping[str, Any],
    monitor_plan: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "state_hash": _validated_state_hash(state),
        "plan_hash": str(evaluator_plan["plan_hash"]),
        "plan_file_sha256": _sha256_file(PLAN_PATH),
        "expansion_monitor_plan_id": str(monitor_plan.get("plan_id") or ""),
        "expansion_monitor_plan_hash": str(monitor_plan.get("plan_hash") or ""),
        "expansion_monitor_plan_file_sha256": _sha256_file(EXPANSION_MONITOR_PLAN_PATH),
    }


def build_plan(generated_at_utc: str) -> dict[str, Any]:
    monitor_plan = _read_json_object(EXPANSION_MONITOR_PLAN_PATH, "expansion monitor plan")
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "PREREGISTERED_FIRST_READ_SAMPLE_REACHED",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "network_authorized": False,
        "private_api": False,
        "live_orders": False,
        "real_capital": False,
        "objective": (
            "Pre-register the evaluation contract for the exchange-expansion forward "
            "sample. The expansion monitor plan requires a separate evaluator plan once "
            "enough complete windows accrue; as of 2026-08-25 it carries 30, which is "
            "the pre-registered first-read minimum. Metrics are computed only at or "
            "above that minimum, by the same peeking guard the forward evaluator uses."
        ),
        "preregistration": {
            "evaluation_class": EVALUATION_CLASS,
            "first_read_min_complete_windows": FIRST_READ_MIN_COMPLETE_WINDOWS,
            "terminal_min_complete_windows": TERMINAL_MIN_COMPLETE_WINDOWS,
            "metrics_frozen": ["ret_24h", "ret_72h", "max_runup", "max_drawdown"],
            "strategy_proxy_frozen": {
                "rule": "long at first in-window 1h open, exit at window end",
                "hold_bars": HOLD_BARS,
                "normal_cost_bps": NORMAL_COST_BPS,
                "stress_cost_bps": STRESS_COST_BPS,
            },
            "shared_core": (
                "metrics and peeking guard imported from "
                "slow_liquidity_listing_momentum_forward_evaluator so the two tracks "
                "cannot drift into computing different things"
            ),
        },
        "acceptance_policy": {
            "acceptance_decision": "NONE_FIRST_READ_DESCRIPTIVE_ONLY",
            "first_read_authorizes": False,
            "terminal_read_authorizes": False,
            "live_trading_authorized": False,
            "note": (
                "A first read at the minimum sample is descriptive. It cannot accept a "
                "strategy, cannot authorise paper forward execution, and above all "
                "cannot authorise live trading. The terminal read at 100 windows is "
                "still only one of the stages the parent plan lists before acceptance: "
                "oos, walk_forward, stress, economics, paper_forward."
            ),
        },
        "source_bindings": {
            "expansion_monitor_plan": {
                "path": str(EXPANSION_MONITOR_PLAN_PATH),
                "plan_id": str(monitor_plan.get("plan_id") or ""),
                "plan_hash": str(monitor_plan.get("plan_hash") or ""),
                "file_sha256": _sha256_file(EXPANSION_MONITOR_PLAN_PATH),
            },
            "expansion_state": {"path": str(EXPANSION_STATE_PATH)},
        },
        "implementation": {
            "files": [
                {
                    "role": "expansion_evaluator",
                    "path": str(Path(__file__).resolve()),
                    "sha256": _sha256_file(Path(__file__).resolve()),
                },
                {
                    "role": "shared_evaluation_core",
                    "path": str(
                        REPO_ROOT
                        / "trading_mvp/src"
                        / "slow_liquidity_listing_momentum_forward_evaluator.py"
                    ),
                    "sha256": _sha256_file(
                        REPO_ROOT
                        / "trading_mvp/src"
                        / "slow_liquidity_listing_momentum_forward_evaluator.py"
                    ),
                },
            ]
        },
        "forbidden": [
            "live orders",
            "real capital",
            "private api",
            "request signing",
            "computing metrics below the pre-registered minimum",
        ],
    }
    plan["plan_hash"] = _canonical_hash_without(plan, "plan_hash")
    return plan


def validate_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "schema")
    _require(plan.get("plan_id") == PLAN_ID, "plan id")
    _require(plan.get("mode") == "PlanOnly", "mode")
    _require(plan.get("research_only") is True, "research_only")
    _require(plan.get("public_data_only") is True, "public_data_only")
    _require(plan.get("private_api") is False, "private_api")
    _require(plan.get("live_orders") is False, "live_orders")
    _require(plan.get("real_capital") is False, "real_capital")
    pre = plan.get("preregistration") or {}
    _require(
        pre.get("first_read_min_complete_windows") == FIRST_READ_MIN_COMPLETE_WINDOWS,
        "first read minimum",
    )
    _require(
        pre.get("terminal_min_complete_windows") == TERMINAL_MIN_COMPLETE_WINDOWS,
        "terminal minimum",
    )
    acceptance = plan.get("acceptance_policy") or {}
    for key in ("first_read_authorizes", "terminal_read_authorizes", "live_trading_authorized"):
        _require(acceptance.get(key) is False, f"{key} must be False")
    _require(
        plan.get("plan_hash") == _canonical_hash_without(plan, "plan_hash"),
        "plan hash",
    )
    for row in (plan.get("implementation") or {}).get("files") or []:
        path = Path(str(row.get("path") or ""))
        _require(path.is_file(), f"implementation missing: {row.get('role')}")
        _require(
            row.get("sha256") == _sha256_file(path),
            f"implementation sha256: {row.get('role')}",
        )


def write_plan(generated_at_utc: str) -> Path:
    plan = build_plan(generated_at_utc)
    validate_plan(plan)
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PLAN_PATH.exists():
        raise ForwardEvaluatorError(f"refusing to overwrite an existing plan: {PLAN_PATH}")
    PLAN_PATH.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return PLAN_PATH


def evaluate() -> dict[str, Any]:
    evaluator_plan = _read_json_object(PLAN_PATH, "expansion evaluator plan")
    validate_plan(evaluator_plan)
    monitor_plan = _read_json_object(EXPANSION_MONITOR_PLAN_PATH, "expansion monitor plan")
    state = _read_json_object(EXPANSION_STATE_PATH, "expansion state")
    _require_state_matches_bound_plan(state, monitor_plan)
    binding = _build_input_binding(state, evaluator_plan, monitor_plan)
    result = evaluate_forward_state(
        state,
        input_binding=binding,
        evaluation_class=EVALUATION_CLASS,
        schema=EVALUATION_SCHEMA,
    )
    result["evaluation_hash"] = _canonical_hash_without(result, "evaluation_hash")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-registered evaluation for the listing-momentum expansion sample"
    )
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument(
        "--generated-at-utc", default="", help="required with --write-plan"
    )
    args = parser.parse_args(argv)
    if args.write_plan:
        if not args.generated_at_utc:
            raise SystemExit("--generated-at-utc is required with --write-plan")
        path = write_plan(args.generated_at_utc)
        plan = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({"status": "PLAN_WRITTEN", "path": str(path),
                          "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]}))
        return 0
    if args.evaluate:
        result = evaluate()
        EVALUATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVALUATION_PATH.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    raise SystemExit("no authorized action requested")


if __name__ == "__main__":
    raise SystemExit(main())
