"""Validate the parent's offline checkpoint, without following external projects."""
from pathlib import Path

from premarket_forward_depth_quality import SCHEMA, canonical, decode, digest

STATUS = "PARENT_RESEARCH_RECONCILED_OFFLINE_ONLY"
DECISION = "PREMARKET_DEPTH_QUALITY_COMPLETE_INSUFFICIENT_SAMPLE"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_ref(binding: dict, root: Path) -> Path:
    path = Path(binding["path"]).resolve()
    _require(root.resolve() in path.parents, "checkpoint path escapes repository")
    _require(path.is_file() and digest(path) == binding["file_sha256"],
             f"checkpoint source hash mismatch: {path}")
    return path


def verify_audit(binding: dict, root: Path) -> dict:
    audit = decode(verify_ref(binding, root).read_text(encoding="utf-8-sig"))
    _require(audit.get("schema") == SCHEMA, "quality schema mismatch")
    _require(audit.get("report_hash") == canonical(audit, "report_hash"), "quality hash mismatch")
    _require(audit.get("input_manifest_hash") == canonical({"files": audit["inputs"]}, "unused"),
             "input manifest hash mismatch")
    for source in audit["inputs"]:
        verify_ref(source, root)
    captures = Path(audit["capture_directory"]).resolve()
    _require(root.resolve() in captures.parents, "capture directory escapes repository")
    _require({str(p.resolve()) for p in captures.glob("*.jsonl")}
             == {e["path"] for e in audit["events"]}, "capture inventory changed")
    summary = audit["summary"]
    _require(summary["current_plan_structural_candidates"] == sum(e["candidate"] is True for e in audit["events"]),
             "quality candidate count mismatch")
    for field in ("mechanism_analysis_performed", "pnl_computed", "acceptance_capable",
                  "complete_statistical_sample_certified"):
        _require(summary.get(field) is False, f"quality scope violation: {field}")
    _require(summary["current_plan_structural_candidates"] < summary["minimum_events_before_any_claim"],
             "sample changed; offline checkpoint must be reconciled")
    return audit


def resolve_checkpoint(report: dict, root: Path, writer_claim: Path) -> dict:
    _require(not writer_claim.exists(), "global writer claim exists")
    checkpoint = report["checkpoint"]
    _require(checkpoint.get("primary_branch") == "premarket_forward_depth", "primary branch mismatch")
    _require(checkpoint.get("schedules_remain_paused") is True, "schedule pause not preserved")
    _require(checkpoint.get("network_launch_authorized") is False, "offline-only checkpoint required")
    _require(checkpoint.get("listing_momentum_scope") == "EXTERNAL_PROJECT_NO_PARENT_EXECUTION",
             "external project isolation mismatch")
    _require(checkpoint.get("legacy_terminal_runs_reopen_allowed") is False, "terminal runs cannot reopen")
    for item in checkpoint["evidence"] + checkpoint["implementation"]:
        verify_ref(item, root)
    audit = verify_audit(checkpoint["quality_report"], root)
    plan = decode(verify_ref(checkpoint["primary_plan"], root).read_text(encoding="utf-8-sig"))
    _require(plan.get("plan_hash") == canonical(plan, "plan_hash") == audit["plan_hash"],
             "primary plan hash mismatch")
    _require(plan["outcome_contract"]["minimum_events_before_any_claim"]
             == audit["summary"]["minimum_events_before_any_claim"], "sample threshold mismatch")
    _require(plan["outcome_contract"]["acceptance_capable"] is False, "descriptive plan required")
    return {"status": "READY", "source_status": STATUS, "execution_authorized": False,
            "readiness_hash": report["readiness_hash"], "checkpoint": checkpoint,
            "quality_summary": audit["summary"], "approval_checkpoints": [],
            "next_safe_action": "review_bounded_accrual_recommendation_keep_schedules_paused"}
