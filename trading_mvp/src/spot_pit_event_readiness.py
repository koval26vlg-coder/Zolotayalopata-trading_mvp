from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKET_SCHEMA = "spot_pit_event_forward_collect_approval_packet_v1"
READY_DECISION = "SPOT_PIT_EVENT_FORWARD_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path.resolve()), "sha256": _sha(path), "bytes": path.stat().st_size}


def _existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if not candidate.exists():
        raise FileNotFoundError(f"no existing parent for output root: {path}")
    return candidate


def build_packet(
    *,
    plan_path: str | Path,
    preflight_path: str | Path,
    collector_path: str | Path,
    analyzer_path: str | Path,
    wrapper_path: str | Path,
    test_evidence_path: str | Path,
    packet_path: str | Path,
) -> dict[str, Any]:
    plan_file = Path(plan_path).resolve()
    preflight_file = Path(preflight_path).resolve()
    collector_file = Path(collector_path).resolve()
    analyzer_file = Path(analyzer_path).resolve()
    wrapper_file = Path(wrapper_path).resolve()
    tests_file = Path(test_evidence_path).resolve()
    target = Path(packet_path).resolve()
    plan = _load(plan_file)
    preflight = _load(preflight_file)
    tests = _load(tests_file)
    plan_hash = _sha(plan_file)
    collection = plan.get("collection") if isinstance(plan.get("collection"), dict) else {}
    output_root = Path(str(collection.get("output_root") or ""))
    disk = shutil.disk_usage(_existing_parent(output_root))
    free_gib = disk.free / 1024**3
    minimum_free_gib = float(collection.get("minimum_free_disk_gib_before_start") or 0.0)
    checks = {
        "plan_contract": plan.get("schema") == "spot_pit_event_forward_plan_v1" and plan.get("research_only") is True and plan.get("strategy_accepted") is False,
        "preflight_contract": preflight.get("schema") == "spot_pit_event_public_preflight_v1" and preflight.get("accepted") is True,
        "preflight_matches_plan": str(preflight.get("plan_sha256") or "").lower() == plan_hash.lower(),
        "preflight_checks_passed": bool(preflight.get("checks")) and all(value is True for value in preflight.get("checks", {}).values()),
        "tests_passed": tests.get("passed") is True and int(tests.get("tests_run") or 0) > 0,
        "visible_terminal_required": collection.get("visible_terminal_required") is True and collection.get("no_hidden_background_run") is True,
        "durable_resume_contract": collection.get("durable_segments") is True and collection.get("resume_same_run_id") is True and collection.get("atomic_manifest") is True,
        "disk_headroom": free_gib >= minimum_free_gib,
    }
    artifacts = {
        "plan": _artifact(plan_file),
        "preflight": _artifact(preflight_file),
        "collector": _artifact(collector_file),
        "analyzer": _artifact(analyzer_file),
        "wrapper": _artifact(wrapper_file),
        "test_evidence": _artifact(tests_file),
    }
    all_passed = all(checks.values())
    duration_sec = int(collection["duration_days"]) * 86400
    wrapper_command = (
        f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{wrapper_file}" '
        f'-ApprovalPacketPath "{target}" -ConfirmedSpotPitEventForwardCollect'
    )
    return {
        "schema": PACKET_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_POSTPROCESS" if all_passed else "REJECTED",
        "final": True,
        "rows": 1,
        "errors": 0 if all_passed else sum(int(not value) for value in checks.values()),
        "output_path": str(target),
        "decision": READY_DECISION if all_passed else "SPOT_PIT_EVENT_FORWARD_COLLECT_APPROVAL_PACKET_REJECTED_FIX_READINESS",
        "all_checks_passed": all_passed,
        "checks": checks,
        "research_only": True,
        "would_start": False,
        "actual_collect_allowed_now": False,
        "requires_explicit_user_confirmation": True,
        "strategy_accepted": False,
        "paper_forward_ready": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "artifacts": artifacts,
        "collection": {
            "output_root": str(output_root),
            "duration_sec": duration_sec,
            "interval_sec": int(collection["interval_sec"]),
            "segment_sec": int(collection["segment_sec"]),
            "checkpoint_every_cycles": int(collection.get("status_every_cycles") or 5),
            "minimum_free_disk_gib": minimum_free_gib,
            "observed_free_disk_gib": free_gib,
            "visible_terminal_required": True,
            "resume_same_run_id": True,
            "preflight_max_age_hours_for_new_run": 24,
        },
        "early_gates": plan["early_gates"],
        "normal_total_cost_bps": float(plan["economics"]["normal_total_cost_bps"]),
        "stress_total_cost_bps": float(plan["economics"]["stress_total_cost_bps"]),
        "command_after_explicit_approval": wrapper_command,
        "resume_command_template": wrapper_command + ' -RunId "<same-run-id>" -ResumeIncomplete',
        "status_command": "pwsh -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\koval\\Documents\\ZolotyayLopata\\tools\\check_active_run_gate.ps1\" -Json",
        "blocked_until_confirmation": ["actual_collect", "replay", "grid_search", "paper_forward", "live_orders", "api_keys"],
    }


def write_packet(packet: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sealed research-only approval packet for the spot PIT event forward collector.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--collector", required=True)
    parser.add_argument("--analyzer", required=True)
    parser.add_argument("--wrapper", required=True)
    parser.add_argument("--test-evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    packet = build_packet(
        plan_path=args.plan,
        preflight_path=args.preflight,
        collector_path=args.collector,
        analyzer_path=args.analyzer,
        wrapper_path=args.wrapper,
        test_evidence_path=args.test_evidence,
        packet_path=args.output,
    )
    write_packet(packet, args.output)
    print(json.dumps({"output": args.output, "decision": packet["decision"], "checks": packet["checks"]}, ensure_ascii=False, indent=2))
    return 0 if packet["all_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
