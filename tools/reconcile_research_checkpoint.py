"""Publish an offline checkpoint with immutable preimages; no launches or network."""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trading_mvp/src"))
from premarket_forward_depth_quality import canonical, decode, digest, ref
from research_checkpoint import STATUS, verify_audit
from one_week_edge_sprint_readiness import CURRENT_PERMISSION_FIELDS, READINESS_SCHEMA, READINESS_HASH_METHOD


RUNTIME_FILES = [
    "trading_mvp/src/premarket_forward_depth_quality.py",
    "trading_mvp/src/research_checkpoint.py",
    "trading_mvp/src/autopilot_guard.py",
    "trading_mvp/src/one_week_edge_sprint_readiness.py",
    "tools/trading_research_checkpoint_status.ps1",
    "tools/trading_goal_status.ps1",
    "tools/trading_next_goal_step.ps1",
    "tools/reconcile_research_checkpoint.py",
]


def immutable_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def replace_if_unchanged(path: Path, value: dict, expected_sha: str):
    if digest(path) != expected_sha:
        raise ValueError(f"concurrent change; refusing replacement: {path}")
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".staged")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if digest(path) != expected_sha:
        raise ValueError(f"concurrent change; staged file retained: {temp_name}")
    os.replace(temp_name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    out = root / "docs/analysis/strategy-reconciliation-20260929"
    policy_path = root / "docs/plans/trading-mvp-autopilot-policy-v1.json"
    pointer_path = root / "docs/agent-log/one-week-edge-sprint-readiness-pointer.json"
    policy = decode(policy_path.read_text(encoding="utf-8-sig"))
    pointer = decode(pointer_path.read_text(encoding="utf-8-sig"))
    if "research_checkpoint" in policy:
        raise ValueError("checkpoint already exists; no blind republish")
    gate = decode((root / "docs/agent-log/active-run-gate.json").read_text(encoding="utf-8-sig"))
    if gate.get("status") != "READY_FOR_POSTPROCESS":
        raise ValueError("active gate not ready")
    writer = root / "docs/agent-log/active-market-data-writer-claim.json"
    if writer.exists():
        raise ValueError("global writer claim exists")
    guard = decode((root / "docs/agent-log/trading-mvp-autopilot-state.json").read_text(encoding="utf-8-sig"))
    observed = datetime.fromisoformat(guard["observed_at_utc"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if (not 0 <= age <= 300 or guard.get("usage", {}).get("decision") != "CONTINUE"
            or guard["usage"].get("remaining_percent", 0) <= 15
            or str(guard.get("status", "")).startswith("PAUSED")):
        raise ValueError("fresh guard and quota above 15 required")
    if guard.get("decision") != "CRITICAL_STOP_CURRENT_SPRINT_READINESS_INTEGRITY":
        raise ValueError("repair applies only to the diagnosed stale parent readiness")
    quality = verify_audit(ref(args.quality_report), root)
    now = datetime.now(timezone.utc).isoformat()
    old_policy_sha, old_pointer_sha = digest(policy_path), digest(pointer_path)
    snapshots = []
    for source, name in ((policy_path, "policy-before.json"), (pointer_path, "pointer-before.json"),
                         (root / "docs/agent-log/active-run-gate.json", "gate-before.json")):
        target = out / name
        content = source.read_bytes()
        with target.open("xb") as handle:
            handle.write(content)
        if digest(source) != digest(target):
            raise ValueError("preimage changed during snapshot")
        snapshots.append(ref(target))
    previous_report = Path(pointer["readiness_path"])
    if digest(previous_report) != pointer["readiness_file_sha256"]:
        raise ValueError("old pointer report hash mismatch")
    evidence = snapshots + [ref(previous_report),
        ref(root / "docs/plans/strategy-branch-disposition-20260817-v1.json"),
        ref(root / "docs/plans/2026-09-29-strategy-audit-and-next-goal-plan.md"),
        ref(out / "README.md"), ref(out / "schedule-state-before.json")]
    report = {"schema": READINESS_SCHEMA, "status": STATUS, "project": "trading_mvp",
        "goal": "One-Week Historical Edge Sprint", "research_only": True,
        "generated_at_utc": now, "readiness_hash_method": READINESS_HASH_METHOD,
        "permissions": {field: False for field in CURRENT_PERMISSION_FIELDS},
        "checkpoint": {"primary_branch": "premarket_forward_depth",
            "schedules_remain_paused": True, "network_launch_authorized": False,
            "listing_momentum_scope": "EXTERNAL_PROJECT_NO_PARENT_EXECUTION",
            "legacy_terminal_runs_reopen_allowed": False,
            "quality_report": ref(args.quality_report),
            "primary_plan": ref(root / "docs/plans/premarket-forward-depth-planonly-20260902-v6.json"),
            "evidence": evidence,
            "implementation": [ref(root / p) for p in RUNTIME_FILES],
            "branch_dispositions": {
                "premarket_forward_depth": "INSUFFICIENT_SAMPLE_DESCRIPTIVE_ONLY_SCHEDULE_PAUSED",
                "listing_momentum": "EXTERNAL_PROJECT",
                "premarket_perp_impulse": "PAUSED_IMPLEMENTATION_BINDING_REPAIR_REQUIRED",
                "preipo_perp_event": "PAUSED_INSUFFICIENT_EVENTS",
                "spot_perp_basis_20260819": "REJECTED_INCOMPLETE_NO_CONSUMPTION",
                "slow_regime_basis_combo": "INFEASIBLE_ZERO_INTERSECTION",
                "funding_basis": "WATCHLIST_ONLY_NO_NEW_INDEPENDENT_HOLDOUT",
                "legacy_dense_pit_windows": "EXPIRED_NOT_ACTIVE_CANDIDATES",
                "closed_strategies": "PRESERVE_TERMINAL_VERDICTS_NO_RETUNE"},
            "next_experiment": {"state": "RECOMMENDATION_NOT_ACTIVATED",
                "hypothesis_changed": False, "plan_hash": quality["plan_hash"],
                "target_min_events_unchanged": 12, "proposed_calendar_horizon_days": 42,
                "checkpoint_day": 14, "forecast_is_not_guarantee": True,
                "stop_at_horizon_without_lowering_threshold": True,
                "prerequisite": "resolve_sampling_gap_and_cluster_protocol_without_return_analysis; explicit_schedule_resume"}}}
    report["readiness_hash"] = canonical(report, "readiness_hash")
    target = root / "docs/agent-log/readiness/one-week-edge-sprint-current-readiness-20260929-v25.json"
    immutable_json(target, report)
    policy["research_checkpoint"] = {"enabled": True, "mode": "OFFLINE_ONLY_SCHEDULES_PAUSED",
        "readiness_hash": report["readiness_hash"], "supersedes_parent_listing_checkpoint": True,
        "superseded_policy_file_sha256": old_policy_sha}
    policy["policy_id"] = "trading_mvp_offline_strategy_reconciliation_20260929"
    policy["effective_at"] = now
    policy["approved_by"] = "USER_20260929_APPROVED_OFFLINE_RECONCILIATION_PLAN_NO_LAUNCH"
    policy["objective_document"] = str(root / "docs/plans/2026-07-14-trading-mvp-current-goal.md")
    pointer.update({"readiness_path": str(target), "readiness_file_sha256": digest(target),
                    "readiness_hash": report["readiness_hash"], "updated_at_utc": now})
    # Policy first: an interruption before pointer promotion remains fail-closed.
    current_gate = decode((root / "docs/agent-log/active-run-gate.json").read_text(encoding="utf-8-sig"))
    if current_gate.get("status") != "READY_FOR_POSTPROCESS" or writer.exists():
        raise ValueError("active run changed before promotion; immutable artifacts retained")
    replace_if_unchanged(policy_path, policy, old_policy_sha)
    replace_if_unchanged(pointer_path, pointer, old_pointer_sha)
    receipt = {"schema": "trading_mvp_offline_reconciliation_receipt_v1", "created_at_utc": now,
               "policy": ref(policy_path), "pointer": ref(pointer_path), "readiness": ref(target),
               "preimages": snapshots, "network_requests": 0, "collectors_launched": 0,
               "schedules_changed": False, "raw_data_modified": False,
               "quality_report": ref(args.quality_report)}
    receipt["receipt_hash"] = canonical(receipt, "receipt_hash")
    immutable_json(out / "reconciliation-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
