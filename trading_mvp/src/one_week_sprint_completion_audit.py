from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from night_schedule_quality import _load_ledger
from night_schedule_status import evaluate_night_schedule_status


REPORT_SCHEMA = "trading_mvp_one_week_sprint_completion_audit_v1"
EXPECTED_TERMINAL_VERDICT = "NO_WEEKLY_EDGE_FOUND_MEXC_GATE"
EXPECTED_PIT_HYPOTHESIS_ID = "pit_universe_membership_drift_reversion_v1"
EXPECTED_PIT_DATA_TYPE = "PIT_UNIVERSE_V2_FORWARD"
EXPECTED_PIT_COLLECTION_STAGE = "train_accrual"
EXPECTED_PIT_TRACK = f"{EXPECTED_PIT_HYPOTHESIS_ID}|{EXPECTED_PIT_DATA_TYPE}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _implementation_hashes() -> dict[str, str]:
    source_dir = Path(__file__).resolve().parent
    sources = {
        "code:one_week_sprint_completion_audit": Path(__file__).resolve(),
        "code:night_schedule_status": source_dir / "night_schedule_status.py",
        "code:night_schedule_quality": source_dir / "night_schedule_quality.py",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise ValueError(
            "completion audit implementation source is missing: "
            + ", ".join(missing)
        )
    return {name: _sha256(path) for name, path in sources.items()}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def verify_closed_branch_evidence(
    terminal_report: dict[str, Any],
) -> list[dict[str, Any]]:
    branches = terminal_report.get("branches")
    if not isinstance(branches, list) or not branches:
        raise ValueError("terminal report has no closed branches")
    verified: list[dict[str, Any]] = []
    for branch in branches:
        if not isinstance(branch, dict):
            raise ValueError("terminal branch must be an object")
        evidence = branch.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError(f"branch evidence is missing: {branch.get('hypothesis_id')}")
        path = Path(str(evidence.get("path") or "")).expanduser().resolve()
        expected = str(evidence.get("file_sha256") or "").lower()
        if not path.is_file():
            raise ValueError(f"branch evidence file is missing: {path}")
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(
                f"branch evidence hash mismatch for {branch.get('hypothesis_id')}: "
                f"expected={expected} actual={actual}"
            )
        verified.append(
            {
                "hypothesis_id": str(branch.get("hypothesis_id")),
                "verdict": str(branch.get("verdict")),
                "reason": str(branch.get("reason")),
                "evidence_path": str(path),
                "evidence_sha256": actual,
                "verified": True,
            }
        )
    return verified


def validate_pit_contract(
    *,
    pointer: dict[str, Any],
    plan: dict[str, Any],
    ledger_entries: list[dict[str, Any]],
    ledger_path: str | Path,
) -> dict[str, str]:
    if pointer.get("status") != "ACTIVE":
        raise ValueError("PIT schedule pointer is not ACTIVE")
    if pointer.get("hypothesis_id") != EXPECTED_PIT_HYPOTHESIS_ID:
        raise ValueError("PIT schedule pointer hypothesis mismatch")
    if pointer.get("data_type") != EXPECTED_PIT_DATA_TYPE:
        raise ValueError("PIT schedule pointer data_type mismatch")
    if pointer.get("collection_stage") != EXPECTED_PIT_COLLECTION_STAGE:
        raise ValueError("PIT schedule pointer collection_stage mismatch")

    expected_ledger_path = Path(ledger_path).expanduser().resolve()
    pointer_ledger_path = Path(
        str(pointer.get("quality_ledger_path") or "")
    ).expanduser().resolve()
    if pointer_ledger_path != expected_ledger_path:
        raise ValueError("PIT schedule pointer quality ledger mismatch")

    hypothesis = plan.get("hypothesis") or {}
    sealed = plan.get("sealed_schedule") or {}
    stage = sealed.get("collection_stage") or {}
    if hypothesis.get("id") != EXPECTED_PIT_HYPOTHESIS_ID:
        raise ValueError("PIT schedule plan hypothesis mismatch")
    if hypothesis.get("required_data_type") != EXPECTED_PIT_DATA_TYPE:
        raise ValueError("PIT schedule plan data_type mismatch")
    if stage.get("name") != EXPECTED_PIT_COLLECTION_STAGE:
        raise ValueError("PIT schedule plan collection_stage mismatch")
    sealed_ledger_path = Path(
        str((stage.get("quality_ledger") or {}).get("path") or "")
    ).expanduser().resolve()
    if sealed_ledger_path != expected_ledger_path:
        raise ValueError("PIT schedule plan quality ledger mismatch")

    contract_hash = str(sealed.get("hypothesis_contract_sha256") or "")
    if not contract_hash:
        raise ValueError("PIT schedule plan contract hash is missing")
    foreign = [
        entry
        for entry in ledger_entries
        if entry.get("track_key") != EXPECTED_PIT_TRACK
        or str(entry.get("hypothesis_contract_sha256") or "") != contract_hash
    ]
    if foreign:
        raise ValueError(
            "quality ledger contains foreign hypothesis/data/contract entries"
        )
    return {
        "hypothesis_id": EXPECTED_PIT_HYPOTHESIS_ID,
        "data_type": EXPECTED_PIT_DATA_TYPE,
        "collection_stage": EXPECTED_PIT_COLLECTION_STAGE,
        "hypothesis_contract_sha256": contract_hash,
        "quality_ledger_path": str(expected_ledger_path),
    }


def validate_autopilot_binding(
    *,
    autopilot: dict[str, Any],
    autopilot_path: str | Path,
    pointer_path: str | Path,
    plan_path: str | Path,
    plan_hash: str,
    pit_contract: dict[str, str],
    accepted_dates: int,
    train_target_dates: int,
    next_segment: dict[str, Any] | None,
) -> dict[str, Any]:
    if autopilot.get("schema") != "trading_mvp_autopilot_state_v1":
        raise ValueError("autopilot state schema mismatch")
    if autopilot.get("project") != "trading_mvp":
        raise ValueError("autopilot state project mismatch")
    if not str(autopilot.get("status") or ""):
        raise ValueError("autopilot state status is missing")
    observed_at_utc = str(autopilot.get("observed_at_utc") or "")
    try:
        observed_at = datetime.fromisoformat(
            observed_at_utc.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("autopilot observed_at_utc is invalid") from exc
    if observed_at.tzinfo is None:
        raise ValueError("autopilot observed_at_utc must be timezone-aware")

    schedule_window = autopilot.get("schedule_window")
    if not isinstance(schedule_window, dict):
        raise ValueError("autopilot schedule_window is missing")

    expected_paths = {
        "pointer_path": Path(pointer_path).expanduser().resolve(),
        "plan_path": Path(plan_path).expanduser().resolve(),
    }
    for field, expected in expected_paths.items():
        observed = Path(
            str(schedule_window.get(field) or "")
        ).expanduser().resolve()
        if observed != expected:
            raise ValueError(f"autopilot schedule_window {field} mismatch")

    expected_values = {
        "plan_hash": plan_hash,
        "hypothesis_id": pit_contract["hypothesis_id"],
        "data_type": pit_contract["data_type"],
        "collection_stage": pit_contract["collection_stage"],
        "hypothesis_contract_sha256": pit_contract[
            "hypothesis_contract_sha256"
        ],
    }
    for field, expected in expected_values.items():
        if str(schedule_window.get(field) or "") != str(expected):
            raise ValueError(f"autopilot schedule_window {field} mismatch")

    try:
        bound_accepted_dates = int(schedule_window["accepted_distinct_dates"])
        bound_target_dates = int(schedule_window["stage_target_distinct_dates"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "autopilot schedule_window date counts are invalid"
        ) from exc
    if bound_accepted_dates != accepted_dates:
        raise ValueError("autopilot accepted_distinct_dates mismatch")
    if bound_target_dates != train_target_dates:
        raise ValueError("autopilot stage_target_distinct_dates mismatch")

    schedule_status = str(schedule_window.get("status") or "")
    if schedule_status in {"WAITING", "DUE"}:
        if next_segment is None:
            raise ValueError(
                "autopilot has a pending schedule window but status audit has none"
            )
        if str(schedule_window.get("run_id") or "") != str(
            next_segment.get("run_id") or ""
        ):
            raise ValueError("autopilot/status next segment run_id mismatch")
    elif schedule_status in {"STAGE_TARGET_REACHED", "NO_PENDING_SEGMENT"}:
        if next_segment is not None:
            raise ValueError(
                "autopilot has no pending schedule window but status audit found one"
            )
    else:
        raise ValueError(
            f"unsupported autopilot schedule_window status: {schedule_status!r}"
        )

    return {
        "schema": "trading_mvp_completion_audit_autopilot_binding_v1",
        "autopilot_state_path": str(
            Path(autopilot_path).expanduser().resolve()
        ),
        "observed_at_utc": observed_at_utc,
        "schedule_status": schedule_status,
        "run_id": (
            str(schedule_window.get("run_id") or "")
            if next_segment is not None
            else None
        ),
        "pointer_path": str(expected_paths["pointer_path"]),
        "plan_path": str(expected_paths["plan_path"]),
        "plan_hash": plan_hash,
        "accepted_distinct_dates": accepted_dates,
        "stage_target_distinct_dates": train_target_dates,
        "hypothesis_contract_sha256": pit_contract[
            "hypothesis_contract_sha256"
        ],
    }


def derive_goal_state(
    *,
    terminal_verdict: str,
    positive_edge_proven: bool,
    accepted_dates: int,
    train_target_dates: int,
    approval_valid: bool,
    schedule_decision: str,
    autopilot_status: str,
    next_segment_available: bool = False,
) -> dict[str, Any]:
    if terminal_verdict != EXPECTED_TERMINAL_VERDICT:
        return {
            "status": "CRITICAL_TERMINAL_VERDICT_MISMATCH",
            "next_allowed_action": "user_review_required",
            "goal_complete": False,
        }
    if positive_edge_proven:
        return {
            "status": "CRITICAL_TERMINAL_REPORT_CONTRADICTION",
            "next_allowed_action": "user_review_required",
            "goal_complete": False,
        }
    if autopilot_status.startswith("PAUSED_"):
        return {
            "status": autopilot_status,
            "next_allowed_action": "wait_for_weekly_quota_guard_to_resume",
            "goal_complete": False,
        }
    if not approval_valid:
        return {
            "status": "CRITICAL_PIT_APPROVAL_INVALID",
            "next_allowed_action": "user_review_required",
            "goal_complete": False,
        }
    if accepted_dates > train_target_dates:
        return {
            "status": "CRITICAL_PIT_TRAIN_TARGET_OVERSHOOT",
            "next_allowed_action": "user_review_required",
            "goal_complete": False,
        }
    if accepted_dates == train_target_dates:
        return {
            "status": "PIT_TRAIN_FEASIBILITY_DUE",
            "next_allowed_action": "run_visible_deterministic_train_only_feasibility",
            "goal_complete": False,
        }
    if (
        schedule_decision == "NIGHT_SEGMENT_MISSED"
        and not next_segment_available
    ):
        return {
            "status": "CRITICAL_PIT_SCHEDULE_STATE",
            "next_allowed_action": "user_review_required",
            "goal_complete": False,
        }
    if schedule_decision not in {
        "WAIT_FOR_NEXT_NIGHT_SEGMENT",
        "RUN_DUE_SEGMENT",
        "MONITOR_RUNNING_SEGMENT",
        "CERTIFY_COMPLETED_SEGMENT",
        "NIGHT_SEGMENT_DUE",
        "NIGHT_SEGMENT_RUNNING",
        "NIGHT_SEGMENT_MISSED",
    }:
        return {
            "status": "CRITICAL_PIT_SCHEDULE_STATE",
            "next_allowed_action": "user_review_required",
            "goal_complete": False,
        }
    return {
        "status": "HISTORICAL_SPRINT_TERMINAL_PIT_TRAIN_ACCRUAL",
        "next_allowed_action": "wait_for_or_run_next_approved_visible_pit_segment",
        "goal_complete": False,
    }


def audit_one_week_sprint(
    *,
    terminal_report_path: str | Path,
    expected_terminal_sha256: str,
    quality_ledger_path: str | Path,
    schedule_pointer_path: str | Path,
    approval_record_root: str | Path,
    autopilot_state_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    terminal_path = Path(terminal_report_path).expanduser().resolve()
    ledger_path = Path(quality_ledger_path).expanduser().resolve()
    pointer_path = Path(schedule_pointer_path).expanduser().resolve()
    approval_root = Path(approval_record_root).expanduser().resolve()
    autopilot_path = Path(autopilot_state_path).expanduser().resolve()
    for required in (terminal_path, ledger_path, pointer_path, autopilot_path):
        if not required.is_file():
            raise ValueError(f"required audit input is missing: {required}")

    terminal_sha256 = _sha256(terminal_path)
    expected_terminal = expected_terminal_sha256.lower()
    if terminal_sha256 != expected_terminal:
        raise ValueError(
            "terminal report hash mismatch: "
            f"expected={expected_terminal} actual={terminal_sha256}"
        )
    terminal = _load_json(terminal_path)
    if terminal.get("final") is not True:
        raise ValueError("terminal report must be final")
    verified_branches = verify_closed_branch_evidence(terminal)

    pointer = _load_json(pointer_path)
    plan_path = Path(str(pointer.get("plan_path") or "")).expanduser().resolve()
    plan_hash = str(pointer.get("plan_hash") or "")
    if not plan_path.is_file() or not plan_hash:
        raise ValueError("schedule pointer is incomplete")
    plan = _load_json(plan_path)
    schedule_status = evaluate_night_schedule_status(
        plan_path,
        plan_hash,
        approval_record_root=approval_root,
    )

    ledger_entries = _load_ledger(ledger_path)
    pit_contract = validate_pit_contract(
        pointer=pointer,
        plan=plan,
        ledger_entries=ledger_entries,
        ledger_path=ledger_path,
    )
    accepted_date_values = sorted(
        {
            str(entry["scheduled_date"])
            for entry in ledger_entries
            if entry.get("technical_quality_accepted") is True
        }
    )
    quality_policy = plan.get("sealed_schedule", {}).get("quality_policy", {})
    train_target_dates = int(quality_policy.get("train_feasibility_distinct_days") or 0)
    if train_target_dates <= 0:
        raise ValueError("train feasibility date target is missing")

    next_segment = next(
        (
            {
                "run_id": str(segment.get("run_id")),
                "status": str(segment.get("status")),
                "start_local": str(segment.get("start_local")),
                "hard_deadline_local": str(segment.get("hard_deadline_local")),
            }
            for segment in schedule_status.get("segments", [])
            if segment.get("status") in {"PLANNED", "DUE", "RUNNING"}
        ),
        None,
    )
    autopilot = _load_json(autopilot_path)
    autopilot_binding = validate_autopilot_binding(
        autopilot=autopilot,
        autopilot_path=autopilot_path,
        pointer_path=pointer_path,
        plan_path=plan_path,
        plan_hash=plan_hash,
        pit_contract=pit_contract,
        accepted_dates=len(accepted_date_values),
        train_target_dates=train_target_dates,
        next_segment=next_segment,
    )
    approval_valid = bool(schedule_status.get("approval", {}).get("valid"))
    goal_state = derive_goal_state(
        terminal_verdict=str(terminal.get("verdict")),
        positive_edge_proven=bool(terminal.get("positive_net_expectancy_edge_proven")),
        accepted_dates=len(accepted_date_values),
        train_target_dates=train_target_dates,
        approval_valid=approval_valid,
        schedule_decision=str(schedule_status.get("decision")),
        autopilot_status=str(autopilot.get("status") or "UNKNOWN"),
        next_segment_available=next_segment is not None,
    )
    evidence_hashes = {
        "terminal_report": terminal_sha256,
        "quality_ledger": _sha256(ledger_path),
        "schedule_pointer": _sha256(pointer_path),
        "schedule_plan": str(schedule_status["plan_file_sha256"]),
        "approval_record": str(schedule_status["approval"].get("record_sha256") or ""),
        "autopilot_state": _sha256(autopilot_path),
        **_implementation_hashes(),
        **{
            f"branch:{item['hypothesis_id']}": item["evidence_sha256"]
            for item in verified_branches
        },
    }
    deterministic_state = {
        "terminal_verdict": terminal.get("verdict"),
        "positive_net_expectancy_edge_proven": terminal.get(
            "positive_net_expectancy_edge_proven"
        ),
        "verified_branches": verified_branches,
        "pit_accepted_date_values": accepted_date_values,
        "pit_train_target_dates": train_target_dates,
        "pit_contract": pit_contract,
        "schedule_plan_hash": plan_hash,
        "schedule_decision": schedule_status.get("decision"),
        "approval_valid": approval_valid,
        "autopilot_status": autopilot.get("status"),
        "autopilot_binding": autopilot_binding,
        "goal_state": goal_state,
        "next_segment": next_segment,
        "evidence_hashes": evidence_hashes,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": "trading_mvp",
        "research_only": True,
        "terminal_sprint": {
            "path": str(terminal_path),
            "sha256": terminal_sha256,
            "verdict": terminal.get("verdict"),
            "positive_net_expectancy_edge_proven": terminal.get(
                "positive_net_expectancy_edge_proven"
            ),
            "closed_branches_verified": len(verified_branches),
            "branches": verified_branches,
        },
        "pit_shadow_track": {
            "quality_ledger_path": str(ledger_path),
            "accepted_distinct_dates": len(accepted_date_values),
            "accepted_distinct_date_values": accepted_date_values,
            "train_target_distinct_dates": train_target_dates,
            "hypothesis_contract_sha256": pit_contract[
                "hypothesis_contract_sha256"
            ],
            "schedule_pointer_path": str(pointer_path),
            "schedule_plan_path": str(plan_path),
            "schedule_plan_hash": plan_hash,
            "schedule_decision": schedule_status.get("decision"),
            "approval_valid": approval_valid,
            "next_segment": next_segment,
        },
        "autopilot": {
            "status": autopilot.get("status"),
            "decision": autopilot.get("decision"),
            "weekly_remaining_percent": autopilot.get("usage", {}).get(
                "remaining_percent"
            ),
            "weekly_threshold_percent": autopilot.get("usage", {}).get(
                "min_remaining_percent"
            ),
            "state_sha256": evidence_hashes["autopilot_state"],
            "schedule_binding": autopilot_binding,
        },
        "completion": {
            **goal_state,
            "historical_edge_proven": False,
            "remaining_required_gates": [
                "PIT train feasibility at 20 accepted dates",
                "chronological OOS only after train feasibility pass",
                "walk-forward, stress, economics and capacity gates",
                "execution probes and paper-forward before live review",
            ],
        },
        "evidence_hashes": evidence_hashes,
        "input_merkle_sha256": _json_hash(evidence_hashes),
        "deterministic_state_hash": _json_hash(deterministic_state),
        "returns_read": False,
        "pnl_read": False,
        "grid_search": False,
        "retune": False,
        "oos_run": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
    }
    if output_path is not None:
        _write_json_atomic(Path(output_path).expanduser().resolve(), report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit One-Week sprint closure and current PIT progress."
    )
    parser.add_argument("--terminal-report", required=True)
    parser.add_argument("--expected-terminal-sha256", required=True)
    parser.add_argument("--quality-ledger", required=True)
    parser.add_argument("--schedule-pointer", required=True)
    parser.add_argument("--approval-record-root", required=True)
    parser.add_argument("--autopilot-state", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = audit_one_week_sprint(
        terminal_report_path=args.terminal_report,
        expected_terminal_sha256=args.expected_terminal_sha256,
        quality_ledger_path=args.quality_ledger,
        schedule_pointer_path=args.schedule_pointer,
        approval_record_root=args.approval_record_root,
        autopilot_state_path=args.autopilot_state,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
