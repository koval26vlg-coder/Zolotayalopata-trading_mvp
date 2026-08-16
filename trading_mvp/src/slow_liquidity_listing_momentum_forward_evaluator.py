from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_forward_evaluator_plan_v1"
PLAN_ID = "slow_liquidity_listing_momentum_forward_evaluator_20260816"
REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-evaluator-planonly-20260816.json"
)
FORWARD_STATE_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_state_20260816.json"
)
EVALUATION_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_evaluation_20260816.json"
)
FIRST_READ_MIN_COMPLETE_WINDOWS = 30
TERMINAL_MIN_COMPLETE_WINDOWS = 100
NORMAL_COST_BPS = 120.0
STRESS_COST_BPS = 245.0
HOLD_BARS = 72
EVALUATION_CLASS = "PROXY_DATE_FORWARD_PREREGISTERED"


class ForwardEvaluatorError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ForwardEvaluatorError(message)


def _pct(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _describe(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 6),
        "median": round(statistics.median(values), 6),
        "p10": round(_pct(values, 0.10), 6),
        "p25": round(_pct(values, 0.25), 6),
        "p75": round(_pct(values, 0.75), 6),
        "p90": round(_pct(values, 0.90), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def build_plan(generated_at_utc: str) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "PREREGISTERED_AWAITING_SAMPLE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "network_authorized": False,
        "private_api": False,
        "objective": (
            "Pre-register the evaluation contract for the survivorship-clean "
            "forward listing-momentum sample BEFORE the data accrues. The "
            "evaluator computes metrics only when the pre-registered minimum "
            "is reached; no peeking below the threshold."
        ),
        "preregistration": {
            "evaluation_class": EVALUATION_CLASS,
            "first_read_min_complete_windows": FIRST_READ_MIN_COMPLETE_WINDOWS,
            "terminal_min_complete_windows": TERMINAL_MIN_COMPLETE_WINDOWS,
            "metrics_frozen": [
                "ret_24h", "ret_72h", "max_runup", "max_drawdown",
            ],
            "strategy_proxy_frozen": {
                "rule": "long at first in-window 1h open, exit at window end",
                "hold_bars": HOLD_BARS,
                "normal_cost_bps": NORMAL_COST_BPS,
                "stress_cost_bps": STRESS_COST_BPS,
                "economic_metrics": [
                    "net_ret_72h_after_normal_cost",
                    "net_ret_72h_after_stress_cost",
                    "share_net_positive_normal",
                ],
            },
            "peeking_guard": (
                "while complete windows < first_read minimum, the evaluator "
                "reports ONLY the accrual count; no metric is computed"
            ),
            "decision_policy": (
                "evaluation output carries acceptance_decision=NONE; "
                "any ACCEPT/REJECT of the strategy requires a separate "
                "user-checkpointed plan per the forward monitor contract"
            ),
            "limitations_inherited": [
                "TRADING_START_NOT_ANNOUNCEMENT",
                "SAME_TICKER_STRING_PAIRING",
                "NO_IDENTITY_VERDICT",
                "SPOT_LONG_ONLY_PROXY",
            ],
        },
        "bindings": {
            "forward_state_path": str(FORWARD_STATE_PATH),
            "forward_monitor_plan":
                "slow-liquidity-listing-momentum-forward-monitor-planonly-20260816.json",
        },
        "forbidden": [
            "COMPUTE_METRICS_BELOW_FIRST_READ_MINIMUM",
            "GRID_OR_RETUNE",
            "EVALUATOR_OR_OOS_ON_OTHER_BRANCHES_WITH_THIS_PLAN",
            "ACCEPT_WITHOUT_SEPARATE_PLAN",
            "PRIVATE_API",
            "PAPER_OR_LIVE",
        ],
        "authorization_now": {
            "plan_freeze_allowed": True,
            "evaluation_when_sample_ready": True,
        },
        "plan_hash_method": "sha256_canonical_json_excluding_plan_hash",
    }
    plan["plan_hash"] = canonical_hash(plan)
    _validate_plan(plan)
    return plan


def _validate_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "schema")
    _require(plan.get("plan_id") == PLAN_ID, "plan id")
    _require(plan.get("mode") == "PlanOnly", "mode")
    pre = plan.get("preregistration") or {}
    _require(
        pre.get("first_read_min_complete_windows") == 30, "first read minimum"
    )
    _require(
        pre.get("terminal_min_complete_windows") == 100, "terminal minimum"
    )
    _require(
        plan.get("forbidden", [])[0] == "COMPUTE_METRICS_BELOW_FIRST_READ_MINIMUM",
        "peeking guard",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash")


def write_plan(generated_at_utc: str) -> Path:
    plan = build_plan(generated_at_utc)
    content = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if PLAN_PATH.exists():
        _require(
            PLAN_PATH.read_text(encoding="utf-8") == content,
            f"immutable artifact mismatch: {PLAN_PATH}",
        )
        return PLAN_PATH
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(content, encoding="utf-8")
    return PLAN_PATH


def evaluate_forward_state(state: Mapping[str, Any]) -> dict[str, Any]:
    windows = [
        window
        for window in state.get("windows") or []
        if window.get("window_complete")
    ]
    accrual = {
        "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_evaluation_v1",
        "evaluation_class": EVALUATION_CLASS,
        "complete_windows": len(windows),
        "first_read_min": FIRST_READ_MIN_COMPLETE_WINDOWS,
        "terminal_min": TERMINAL_MIN_COMPLETE_WINDOWS,
        "acceptance_decision": "NONE",
    }
    if len(windows) < FIRST_READ_MIN_COMPLETE_WINDOWS:
        accrual["status"] = "INSUFFICIENT_SAMPLE_NO_METRICS"
        accrual["note"] = (
            "peeking guard: metrics frozen until the pre-registered minimum "
            "is reached"
        )
        return accrual
    ret24 = [
        float(window["stats"]["ret_24h"])
        for window in windows
        if (window.get("stats") or {}).get("ret_24h") is not None
    ]
    ret72 = [
        float(window["stats"]["ret_72h"])
        for window in windows
        if (window.get("stats") or {}).get("ret_72h") is not None
    ]
    runup = [
        float(window["stats"]["max_runup"])
        for window in windows
        if (window.get("stats") or {}).get("max_runup") is not None
    ]
    drawdown = [
        float(window["stats"]["max_drawdown"])
        for window in windows
        if (window.get("stats") or {}).get("max_drawdown") is not None
    ]
    net_normal = [value - NORMAL_COST_BPS / 1e4 for value in ret72]
    net_stress = [value - STRESS_COST_BPS / 1e4 for value in ret72]
    accrual.update(
        {
            "status": "EVALUATED_DESCRIPTIVE",
            "sample_sufficient_for_terminal": len(windows)
            >= TERMINAL_MIN_COMPLETE_WINDOWS,
            "metrics": {
                "ret_24h": _describe(ret24),
                "ret_72h": _describe(ret72),
                "max_runup": _describe(runup),
                "max_drawdown": _describe(drawdown),
                "net_ret_72h_after_normal_cost": _describe(net_normal),
                "net_ret_72h_after_stress_cost": _describe(net_stress),
                "share_net_positive_normal": (
                    round(
                        sum(1 for value in net_normal if value > 0) / len(net_normal),
                        4,
                    )
                    if net_normal
                    else None
                ),
            },
            "windows_by_venue": {
                venue: sum(1 for w in windows if w.get("exchange") == venue)
                for venue in sorted({w.get("exchange") for w in windows})
            },
        }
    )
    return accrual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args(argv)
    if args.write_plan:
        generated = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        path = write_plan(generated)
        plan = json.loads(path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "status": "PLAN_WRITTEN",
                    "path": str(path),
                    "plan_hash": plan["plan_hash"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.evaluate:
        _require(FORWARD_STATE_PATH.is_file(), "forward state not present")
        state = json.loads(FORWARD_STATE_PATH.read_text(encoding="utf-8"))
        result = evaluate_forward_state(state)
        if EVALUATION_PATH.exists():
            on_disk = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
            if on_disk.get("complete_windows") == result["complete_windows"]:
                result = on_disk
            else:
                EVALUATION_PATH.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        else:
            EVALUATION_PATH.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    raise SystemExit("no authorized action requested")


if __name__ == "__main__":
    raise SystemExit(main())
