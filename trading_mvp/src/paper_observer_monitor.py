from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from paper_observer_runtime import (
    MAX_RUNTIME_SEC,
    _read_json,
    _read_jsonl,
    validate_fixture_observer_plan,
)


MONITOR_SCHEMA = "trading_mvp_paper_observer_fixture_monitor_v1"


def _mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def build_monitor_snapshot(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    plan = validate_fixture_observer_plan(plan_path, expected_plan_hash)
    fixture_path = Path(plan["fixture"]["path"]).resolve()
    manifest_path = Path(plan["outputs"]["manifest_path"]).resolve()
    audit_path = Path(plan["outputs"]["audit_path"]).resolve()
    accepted_path = Path(plan["outputs"]["accepted_path"]).resolve()
    total = len(_read_jsonl(fixture_path))
    audit = _read_jsonl(audit_path)
    accepted = _read_jsonl(accepted_path)
    completed = len(audit)
    remaining = max(0, total - completed)
    manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    status = str(manifest.get("status") or ("NOT_STARTED" if not audit else "RUNNING"))
    final = manifest.get("final") is True
    interval = 5
    runtime_contract = _read_json(plan["runtime_contract"]["path"])
    runtime_settings = runtime_contract.get("runtime") or {}
    if int(runtime_settings.get("sample_interval_sec") or 0) > 0:
        interval = int(runtime_settings["sample_interval_sec"])
    eta_sec = 0 if final else remaining * interval
    last_audit = audit[-1] if audit else {}
    last_health = last_audit.get("health") if isinstance(last_audit, dict) else {}
    last_incident = last_audit.get("incident") if isinstance(last_audit, dict) else {}
    incident_state = manifest.get("incident_state")
    if not isinstance(incident_state, dict):
        incident_state = (
            dict(last_incident.get("state_after") or {})
            if isinstance(last_incident, dict)
            else {}
        )
    errors = manifest.get("errors") if isinstance(manifest.get("errors"), list) else []
    return {
        "schema": MONITOR_SCHEMA,
        "run_id": plan["run_id"],
        "plan_hash": plan["plan_hash"],
        "status": status,
        "final": final,
        "total_samples": total,
        "completed_samples": completed,
        "remaining_samples": remaining,
        "accepted_samples": len(accepted),
        "blocked_samples": completed - len(accepted),
        "progress_percent": round(completed / total * 100.0, 3) if total else 100.0,
        "eta_sec": eta_sec,
        "last_health_decision": (
            last_health.get("decision") if isinstance(last_health, dict) else None
        ),
        "last_health_reasons": (
            list(last_health.get("reasons") or [])
            if isinstance(last_health, dict)
            else []
        ),
        "incident_state": incident_state,
        "last_write_utc": {
            "manifest": _mtime(manifest_path),
            "audit": _mtime(audit_path),
            "accepted": _mtime(accepted_path),
        },
        "errors": list(errors),
        "network_access": False,
        "private_api_keys": False,
        "live_orders": False,
        "maximum_authority": "READ_ONLY_FIXTURE_MONITOR",
    }


def format_monitor_line(snapshot: dict[str, Any]) -> str:
    incident = snapshot.get("incident_state") or {}
    reasons = ",".join(snapshot.get("last_health_reasons") or []) or "-"
    errors = len(snapshot.get("errors") or [])
    return (
        f"[paper-observer] run={snapshot['run_id']} status={snapshot['status']} "
        f"progress={snapshot['completed_samples']}/{snapshot['total_samples']} "
        f"accepted={snapshot['accepted_samples']} blocked={snapshot['blocked_samples']} "
        f"eta_sec={snapshot['eta_sec']} health={snapshot.get('last_health_decision') or '-'} "
        f"incident={incident.get('current_state') or '-'} reasons={reasons} errors={errors}"
    )


def watch_monitor(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    poll_interval_sec: float = 2.0,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    emit: Callable[[str], None] = print,
    monotonic_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if poll_interval_sec <= 0:
        raise ValueError("poll_interval_sec must be positive")
    if max_runtime_sec < 1 or max_runtime_sec > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    started = monotonic_fn()
    while True:
        snapshot = build_monitor_snapshot(
            plan_path=plan_path,
            expected_plan_hash=expected_plan_hash,
        )
        emit(format_monitor_line(snapshot))
        if snapshot["final"]:
            return snapshot
        if monotonic_fn() - started >= max_runtime_sec:
            return {**snapshot, "monitor_stop_reason": "max_runtime_sec"}
        sleep_fn(poll_interval_sec)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visible fixture paper-observer monitor")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.watch:
        result = watch_monitor(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            poll_interval_sec=args.poll_interval_sec,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = build_monitor_snapshot(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        print(format_monitor_line(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
