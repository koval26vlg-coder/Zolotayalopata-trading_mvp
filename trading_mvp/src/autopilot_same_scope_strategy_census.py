from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "trading_mvp_same_scope_strategy_census_v2"
PRIOR_CENSUS_SCHEMA = "trading_mvp_same_scope_hypothesis_census_v1"
BASIS_CURRENTNESS_SCHEMA = (
    "trading_mvp_cross_venue_basis_terminal_currentness_recheck_v1"
)
GUARD_SCHEMA = "trading_mvp_autopilot_state_v1"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {target}")
    return payload


def _descriptor(path: str | Path) -> dict[str, str]:
    target = Path(path).expanduser().resolve()
    return {
        "path": str(target),
        "file_sha256": sha256_file(target),
    }


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def build_strategy_census(
    *,
    prior_census_path: str | Path,
    basis_currentness_path: str | Path,
    guard_snapshot_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    prior = _read_json(prior_census_path)
    basis = _read_json(basis_currentness_path)
    guard = _read_json(guard_snapshot_path)
    if prior.get("schema") != PRIOR_CENSUS_SCHEMA:
        raise ValueError("prior strategy census schema mismatch")
    if prior.get("selected_candidate") is not None:
        raise ValueError("prior strategy census already selected a candidate")
    if basis.get("schema") != BASIS_CURRENTNESS_SCHEMA:
        raise ValueError("basis currentness schema mismatch")
    if basis.get("status") != "PASS_BRANCHES_REMAIN_TERMINAL":
        raise ValueError("basis terminal currentness is not confirmed")
    safety = _require_mapping(basis.get("safety"), label="basis safety")
    if any(
        safety.get(key) is not False
        for key in (
            "network_access",
            "collector_started",
            "market_rows_read",
            "returns_read",
            "pnl_read",
            "oos_run",
            "grid_or_retune",
            "source_or_contract_mutated",
        )
    ):
        raise ValueError("basis currentness audit crossed a safety boundary")
    if (
        guard.get("schema") != GUARD_SCHEMA
        or guard.get("status") != "ACTIVE"
        or guard.get("stop_new_actions") is not False
    ):
        raise ValueError("guard snapshot is not active")
    schedule = _require_mapping(
        guard.get("schedule_window"), label="guard schedule"
    )
    if (
        schedule.get("classification") != "PREAPPROVED_SHORT_SEGMENT"
        or schedule.get("data_type") != "PIT_UNIVERSE_V2_FORWARD"
    ):
        raise ValueError("guard PIT schedule is not the approved shadow track")
    accepted_dates = int(schedule.get("accepted_distinct_dates") or 0)
    target_dates = int(schedule.get("stage_target_distinct_dates") or 0)
    if accepted_dates < 0 or target_dates <= 0 or accepted_dates >= target_dates:
        raise ValueError("PIT train checkpoint requires a separate decision")

    long_approval = _require_mapping(
        guard.get("long_campaign_approval"), label="long campaign approval"
    )
    dense = _require_mapping(
        guard.get("long_campaign_candidate"), label="dense candidate"
    )
    terminal_families = prior.get("terminally_closed")
    candidate_review = prior.get("materially_distinct_candidate_review")
    if not isinstance(terminal_families, list) or not isinstance(
        candidate_review, list
    ):
        raise ValueError("prior strategy census is incomplete")

    deterministic = {
        "schema": SCHEMA,
        "task_id": "same_scope_strategy_census_v2",
        "scope": {
            "venues": ["mexc", "gateio"],
            "existing_immutable_metadata_only": True,
            "new_hypothesis_created": False,
            "market_rows_read": False,
            "returns_or_pnl_read": False,
            "oos_read": False,
            "grid_or_retune": False,
        },
        "inputs": {
            "prior_census": _descriptor(prior_census_path),
            "basis_currentness": _descriptor(basis_currentness_path),
            "guard_snapshot": _descriptor(guard_snapshot_path),
        },
        "current_routes": {
            "pit_universe_membership_drift_reversion_v1": {
                "status": "NEEDS_MORE_INDEPENDENT_DATES",
                "accepted_distinct_dates": accepted_dates,
                "stage_target_distinct_dates": target_dates,
                "dates_remaining": target_dates - accepted_dates,
                "testable_now": False,
                "next_run_id": str(schedule.get("run_id") or ""),
            },
            "dense_ws_microstructure_regime_filter_v1": {
                "status": "EXPIRED_WINDOW_NEW_EXACT_PLAN_REQUIRED",
                "campaign_id": str(dense.get("campaign_id") or ""),
                "launch_window_status": str(
                    long_approval.get("launch_window_status") or ""
                ),
                "testable_now": False,
                "collector_launch_allowed": False,
            },
            "cross_venue_perp_basis": {
                "status": "TERMINAL_ON_FROZEN_CONTRACTS",
                "terminal_report_count": len(
                    basis.get("terminal_reports") or []
                ),
                "testable_now": False,
                "repeat_or_retune_allowed": False,
            },
        },
        "closed_family_count": len(terminal_families),
        "reviewed_alternatives": [
            {
                "candidate": str(item.get("candidate") or ""),
                "selected": False,
                "reason": str(item.get("reason") or ""),
            }
            for item in candidate_review
            if isinstance(item, Mapping)
        ],
        "selected_candidate": None,
        "verdict": (
            "NO_ALTERNATIVE_STRATEGY_CAN_BE_HONESTLY_TESTED_ON_CURRENT_"
            "IMMUTABLE_DATA"
        ),
        "rationale": (
            "Existing branches are terminal, need more independent PIT dates, "
            "or require a new exact data contract. Reusing the same caches for "
            "another signal would be relabeling or data snooping."
        ),
        "next_allowed_action": (
            "continue_approved_pit_schedule_or_request_exact_new_data_contract"
        ),
        "safety": {
            "network_access": False,
            "collector_started": False,
            "market_rows_read": False,
            "returns_read": False,
            "pnl_read": False,
            "oos_run": False,
            "grid_or_retune": False,
            "hypothesis_changed": False,
            "paper_forward_started": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
    }
    result = {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    if output_path is not None:
        _write_json_immutable(output_path, result)
    return result


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit whether another strategy is testable on current metadata"
    )
    parser.add_argument("--prior-census", required=True)
    parser.add_argument("--basis-currentness", required=True)
    parser.add_argument("--guard-snapshot", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = build_strategy_census(
        prior_census_path=args.prior_census,
        basis_currentness_path=args.basis_currentness,
        guard_snapshot_path=args.guard_snapshot,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
